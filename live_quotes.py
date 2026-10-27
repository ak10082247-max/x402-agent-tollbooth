"""Read-only Base quotes. Discovery is not execution evidence; eth_call is.

No key loading, approvals, transaction construction, signing, or broadcasting.
"""
import asyncio
import os
import re
import time
from decimal import Decimal, InvalidOperation, localcontext
from datetime import datetime, timezone

import httpx
from eth_abi import encode, decode
from eth_utils import keccak

TOKENS = {
    "WETH": "0x4200000000000000000000000000000000000006",
    "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "AERO": "0x940181a94A35A4569E4529A3CDfB74e38FD98631",
}
SOLANA_TOKENS = {"SOL": "So11111111111111111111111111111111111111112", "WSOL": "So11111111111111111111111111111111111111112", "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"}
SOLANA_CHAIN = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
UNI_FACTORY = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
UNI_QUOTER = "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a"
AERO_FACTORY = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


class QuoteError(Exception):
    def __init__(self, code, message, http_status=503):
        super().__init__(message)
        self.code, self.http_status = code, http_status


def solana_address(value):
    if not isinstance(value, str):
        raise QuoteError("INVALID_TOKEN", "Solana token must be a mint address or SOL/USDC", 400)
    address = SOLANA_TOKENS.get(value.upper(), value)
    try:
        number = 0
        for char in address:
            number = number * 58 + B58.index(char)
        length = len(number.to_bytes((number.bit_length()+7)//8, "big")) + len(address)-len(address.lstrip("1"))
        if length != 32:
            raise ValueError()
    except (ValueError, TypeError):
        raise QuoteError("INVALID_TOKEN", "Expected a valid Solana mint address or SOL/USDC", 400)
    return address


def token_address(value):
    if not isinstance(value, str):
        raise QuoteError("INVALID_TOKEN", "Token must be a Base address or supported symbol", 400)
    address = TOKENS.get(value.upper(), value)
    if not ADDRESS.fullmatch(address):
        raise QuoteError("INVALID_TOKEN", "Use WETH, USDC, AERO or an exact Base token address", 400)
    return address.lower()


def positive_decimal(value):
    try:
        if isinstance(value, bool) or value is None:
            raise InvalidOperation()
        if len(str(value)) > 128:
            raise InvalidOperation()
        number = Decimal(str(value))
        if not number.is_finite() or number <= 0 or number > Decimal("1e30"):
            raise InvalidOperation()
        return number
    except (InvalidOperation, TypeError, ValueError):
        raise QuoteError("INVALID_AMOUNT", "amount must be a positive finite decimal at most 1e30", 400)


def validate_request(tool, args):
    if not isinstance(args, dict):
        raise QuoteError("INVALID_INPUT", "Input must be a JSON object", 400)
    chain = args.get("chain", "base")
    if chain not in ("base", "eip155:8453", 8453, "solana", SOLANA_CHAIN):
        raise QuoteError("UNSUPPORTED_CHAIN", "Trading quotes support Base and Solana mainnet", 400)
    if tool == "arbitrage_scan":
        pair = args.get("pair", "SOL/USDC" if chain in ("solana", SOLANA_CHAIN) else "WETH/USDC")
        if not isinstance(pair, str) or len(pair.split("/")) != 2:
            raise QuoteError("INVALID_PAIR", "pair must contain exactly two tokens separated by /", 400)
        tin, tout = pair.split("/")
    else:
        tin, tout = args.get("tokenIn", "SOL" if chain in ("solana", SOLANA_CHAIN) else "WETH"), args.get("tokenOut", "USDC")
    resolve = solana_address if chain in ("solana", SOLANA_CHAIN) else token_address
    tin, tout = resolve(tin), resolve(tout)
    if tin == tout:
        raise QuoteError("INVALID_PAIR", "Input and output tokens must differ", 400)
    amount = positive_decimal(args.get("amount", "1"))
    threshold = args.get("min_spread_bps", 0)
    if isinstance(threshold, bool) or not isinstance(threshold, int) or not 0 <= threshold <= 100000:
        raise QuoteError("INVALID_THRESHOLD", "min_spread_bps must be an integer from 0 to 100000", 400)
    slippage = args.get("slippage_bps", 50)
    if isinstance(slippage, bool) or not isinstance(slippage, int) or not 1 <= slippage <= 1000:
        raise QuoteError("INVALID_SLIPPAGE", "slippage_bps must be an integer from 1 to 1000", 400)
    return tin, tout, amount, threshold


class BaseQuotes:
    def __init__(self, client):
        self.client = client
        self.rpc_url = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")
        self.rpc_urls = list(dict.fromkeys([self.rpc_url, "https://base-rpc.publicnode.com", "https://mainnet.base.org"]))
        self.block = None
        self.pool_metadata = {}

    async def rpc(self, method, params):
        # Fixed trusted fallback hosts; environment-provided credentials are never returned.
        failures = []
        for url in self.rpc_urls:
            try:
                response = await self.client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                if response.status_code != 200:
                    failures.append("HTTP_ERROR")
                    continue
                payload = response.json()
                if payload.get("error"):
                    # A deterministic revert is not a transport outage.
                    if "revert" in str(payload["error"]).lower():
                        raise QuoteError("QUOTE_REVERTED", "Read-only contract quote reverted")
                    failures.append("RPC_ERROR")
                    continue
                if "result" not in payload:
                    failures.append("INVALID_RPC_RESPONSE")
                    continue
                return payload["result"]
            except QuoteError:
                raise
            except (httpx.HTTPError, ValueError, TypeError):
                failures.append("RPC_UNAVAILABLE")
        raise QuoteError("RPC_UNAVAILABLE", "Base RPC acquisition failed on configured and public fallback providers")

    async def call(self, address, signature, types=(), values=(), outputs=("uint256",)):
        data = "0x" + (keccak(text=signature)[:4] + encode(types, values)).hex()
        raw = await self.rpc("eth_call", [{"to": address, "data": data}, self.block])
        try:
            return decode(outputs, bytes.fromhex(raw.removeprefix("0x")))
        except (ValueError, TypeError, OverflowError) as exc:
            raise QuoteError("INVALID_CONTRACT_RESPONSE", "Contract returned malformed quote data") from exc
        except Exception as exc:
            raise QuoteError("INVALID_CONTRACT_RESPONSE", "Contract response could not be ABI decoded") from exc

    async def setup(self, tin, tout):
        if int(await self.rpc("eth_chainId", []), 16) != 8453:
            raise QuoteError("WRONG_RPC_CHAIN", "RPC is not Base mainnet")
        self.block = await self.rpc("eth_blockNumber", [])
        self.block_info = await self.rpc("eth_getBlockByNumber", [self.block, False])
        if not isinstance(self.block_info, dict) or not self.block_info.get("hash"):
            raise QuoteError("INVALID_BLOCK", "RPC did not return the quoted block")
        self.decimals = {}
        for token in (tin, tout):
            decimals = (await self.call(token, "decimals()", outputs=("uint8",)))[0]
            self.decimals[token] = decimals
        return self

    async def discover(self, tin, tout):
        pools, errors = [], []
        # Official per-token endpoint avoids symbol search ambiguity and truncation.
        try:
            response = await self.client.get(f"https://api.dexscreener.com/token-pairs/v1/base/{tin}")
            if response.status_code != 200:
                errors.append({"provider": "dexscreener", "code": "HTTP_ERROR", "http_status": response.status_code})
            else:
                payload = response.json()
                if not isinstance(payload, list):
                    raise ValueError("Expected array")
                for pool in payload:
                    actual = {str((pool.get(k) or {}).get("address", "")).lower() for k in ("baseToken", "quoteToken")}
                    if pool.get("chainId") == "base" and actual == {tin, tout} and ADDRESS.fullmatch(str(pool.get("pairAddress", ""))):
                        pools.append({"pool": pool["pairAddress"].lower(), "dex": pool.get("dexId", "unknown"), "labels": pool.get("labels") or []})
        except (httpx.HTTPError, ValueError, TypeError):
            errors.append({"provider": "dexscreener", "code": "DISCOVERY_UNAVAILABLE"})
        # On-chain Uniswap factory is a separate acquisition path, not dependent on discovery.
        for fee in (100, 500, 3000, 10000):
            try:
                pool = (await self.call(UNI_FACTORY, "getPool(address,address,uint24)", ("address", "address", "uint24"), (tin, tout, fee), ("address",)))[0]
                if int(pool, 16):
                    pools.append({"pool": pool.lower(), "dex": "uniswap", "labels": ["v3"], "fee": fee})
            except QuoteError as exc:
                errors.append({"provider": "uniswap_factory", "code": exc.code, "fee": fee})
        unique = {p["pool"]: p for p in pools}
        supported = [p for p in unique.values() if p["dex"] in ("uniswap", "aerodrome") and not (p["dex"] == "aerodrome" and any("slip" in str(x).lower() or "cl" == str(x).lower() for x in p.get("labels", [])))]
        return supported[:6], errors

    async def quote(self, pool, tin, tout, amount):
        address = pool["pool"]
        if address not in self.pool_metadata:
            actual0 = (await self.call(address, "token0()", outputs=("address",)))[0].lower()
            actual1 = (await self.call(address, "token1()", outputs=("address",)))[0].lower()
            self.pool_metadata[address] = {"token0": actual0, "token1": actual1}
        meta = self.pool_metadata[address]
        actual0, actual1 = meta["token0"], meta["token1"]
        if {actual0, actual1} != {tin, tout}:
            raise QuoteError("POOL_TOKEN_MISMATCH", "On-chain pool tokens do not match requested tokens")
        if pool["dex"] == "uniswap" and ("v3" in pool["labels"] or "fee" in pool):
            if "fee" not in meta:
                fee = (await self.call(address, "fee()", outputs=("uint24",)))[0]
                factory_pool = (await self.call(UNI_FACTORY, "getPool(address,address,uint24)", ("address", "address", "uint24"), (tin, tout, fee), ("address",)))[0].lower()
                if factory_pool != address:
                    raise QuoteError("UNTRUSTED_POOL", "Pool does not belong to the canonical Uniswap factory")
                meta["fee"] = fee
            fee = meta["fee"]
            result = await self.call(UNI_QUOTER, "quoteExactInputSingle((address,address,uint256,uint24,uint160))", ("(address,address,uint256,uint24,uint160)",), ((tin, tout, amount, fee, 0),), ("uint256", "uint160", "uint32", "uint256"))
            out, sqrt_after, ticks, gas = result
            detail = {"method": "uniswap_v3_quoter_v2", "fee_ppm": fee, "sqrt_price_x96_after": str(sqrt_after), "initialized_ticks_crossed": ticks, "gas_units_quote_estimate": gas}
        elif pool["dex"] == "aerodrome" and not any("slip" in x.lower() or "cl" == x.lower() for x in pool["labels"]):
            if "aero_verified" not in meta:
                registered = (await self.call(AERO_FACTORY, "isPool(address)", ("address",), (address,), ("bool",)))[0]
                if not registered:
                    raise QuoteError("UNTRUSTED_POOL", "Pool does not belong to the canonical Aerodrome factory")
                stable = (await self.call(address, "stable()", outputs=("bool",)))[0]
                fee_bps = (await self.call(AERO_FACTORY, "getFee(address,bool)", ("address", "bool"), (address, stable)))[0]
                meta.update(aero_verified=True, fee_bps=fee_bps, stable=stable)
            out = (await self.call(address, "getAmountOut(uint256,address)", ("uint256", "address"), (amount, tin)))[0]
            detail = {"method": "aerodrome_pool_getAmountOut", "fee_bps": meta["fee_bps"], "stable": meta["stable"], "gas_units_quote_estimate": None}
        else:
            raise QuoteError("UNSUPPORTED_POOL", "Pool family has no reviewed read-only quote adapter")
        if out <= 0:
            raise QuoteError("ZERO_OUTPUT", "Contract quote returned zero output")
        return {"dex": pool["dex"], "pool": address, "token_in": tin, "token_out": tout, "amount_in_raw": str(amount), "amount_out_raw": str(out), "decimals_in": self.decimals[tin], "decimals_out": self.decimals[tout], "lp_fee_included": True, **detail}


async def compute_quote(tool, args):
    try:
        async with asyncio.timeout(45):
            if isinstance(args, dict) and args.get("chain") in ("solana", SOLANA_CHAIN):
                return await compute_solana_quote(tool, args)
            return await _compute_quote(tool, args)
    except TimeoutError as exc:
        raise QuoteError("QUOTE_TIMEOUT", "Quote acquisition exceeded 45 seconds; no liquidity or profit conclusion was produced") from exc


async def compute_solana_quote(tool, args):
    start = time.perf_counter()
    tin, tout, amount, threshold = validate_request(tool, args)
    urls = list(dict.fromkeys([os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"), "https://solana-rpc.publicnode.com", "https://api.mainnet-beta.solana.com"]))
    async with httpx.AsyncClient(timeout=8.0) as client:
        async def rpc(method, params):
            for url in urls:
                try:
                    response = await client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                    payload = response.json() if response.status_code == 200 else {}
                    if "result" in payload and not payload.get("error"):
                        return payload["result"]
                except (httpx.HTTPError, ValueError, TypeError):
                    pass
            raise QuoteError("SOLANA_RPC_UNAVAILABLE", "Solana RPC could not acquire validated mainnet mint metadata")
        if await rpc("getGenesisHash", []) != "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d":
            raise QuoteError("WRONG_RPC_CHAIN", "Solana RPC is not mainnet")
        accounts = await rpc("getMultipleAccounts", [[tin, tout], {"encoding": "jsonParsed", "commitment": "confirmed"}])
        try:
            decimals = {}
            for mint, account in zip((tin, tout), accounts["value"]):
                if account is None:
                    raise QuoteError("MINT_NOT_FOUND", f"Mainnet mint does not exist: {mint}", 400)
                if account["owner"] not in ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb") or account["data"]["parsed"]["type"] != "mint":
                    raise QuoteError("INVALID_MINT", "Account is not an SPL token mint", 400)
                decimals[mint] = account["data"]["parsed"]["info"]["decimals"]
            if len(decimals) != 2 or any(isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 255 for d in decimals.values()):
                raise ValueError()
            slot = accounts["context"]["slot"]
        except QuoteError:
            raise
        except (ValueError, KeyError, TypeError):
            raise QuoteError("INVALID_MINT_RESPONSE", "Solana RPC returned malformed mint metadata")
        with localcontext() as context:
            context.prec = 600
            raw_decimal = amount * Decimal(10) ** decimals[tin]
        if raw_decimal != raw_decimal.to_integral_value() or raw_decimal > Decimal(2) ** 64 - 1:
            raise QuoteError("INVALID_AMOUNT_PRECISION", "amount exceeds SPL mint decimals or uint64", 400)
        raw = int(raw_decimal)
        async def ray_quote(mint_in, mint_out, quantity):
            params = {"inputMint": mint_in, "outputMint": mint_out, "amount": str(quantity), "slippageBps": args.get("slippage_bps", 50), "txVersion": "V0"}
            try:
                response = await client.get("https://transaction-v1.raydium.io/compute/swap-base-in", params=params)
                if response.status_code != 200:
                    raise QuoteError("RAYDIUM_HTTP_ERROR", f"Raydium quote acquisition returned HTTP {response.status_code}")
                payload = response.json()
                if payload.get("success") is not True:
                    raise QuoteError("RAYDIUM_QUOTE_REJECTED", "Raydium did not produce an amount-dependent route; no market-wide liquidity conclusion is asserted")
                data = payload["data"]
                if not isinstance(payload.get("id"), str) or not payload["id"]:
                    raise ValueError("Missing quote identifier")
                if data.get("inputMint") != mint_in or data.get("outputMint") != mint_out or str(data.get("inputAmount")) != str(quantity) or data.get("swapType") != "BaseIn" or data.get("slippageBps") != params["slippageBps"]:
                    raise ValueError("Quote does not match requested input")
                output = int(data["outputAmount"])
                minimum = int(data["otherAmountThreshold"])
                plan = data["routePlan"]
                if output <= 0 or minimum < 0 or minimum > output or not isinstance(plan, list) or not plan or len(plan) > 12:
                    raise ValueError("Malformed route")
                if abs(minimum - output * (10000-params["slippageBps"]) // 10000) > 1:
                    raise ValueError("Minimum output does not match requested slippage")
                # Validate route continuity, amount and fee identity; never accept substituted mints.
                expected = mint_in
                for hop in plan:
                    solana_address(hop["poolId"])
                    solana_address(hop["outputMint"])
                    if hop["inputMint"] != expected or int(hop["feeAmount"]) < 0:
                        raise ValueError("Invalid route path")
                    if hop["feeMint"] not in (hop["inputMint"], hop["outputMint"]):
                        raise ValueError("Unrelated fee mint")
                    expected = hop["outputMint"]
                if expected != mint_out:
                    raise ValueError("Route terminates in an unrequested mint")
                return {"provider": "raydium_trade_api", "quote_id": payload.get("id"), "method": "read_only_exact_input_quote", "token_in": mint_in, "token_out": mint_out, "amount_in_raw": str(quantity), "amount_out_raw": str(output), "minimum_output_raw": str(minimum), "decimals_in": decimals[mint_in], "decimals_out": decimals[mint_out], "slippage_bps": params["slippageBps"], "price_impact_pct": data.get("priceImpactPct"), "route_plan": plan, "lp_fee_included": True, "observed_at": datetime.now(timezone.utc).isoformat(), "quote_sha256": __import__("hashlib").sha256(__import__("json").dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
            except QuoteError:
                raise
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                raise QuoteError("INVALID_RAYDIUM_QUOTE", "Raydium quote was unavailable or failed request and route validation")
        buy = await ray_quote(tin, tout, raw)
        base = {"status": "quoted", "service": "x402-agent-tollbooth", "chain": "solana", "tokenIn": tin, "tokenOut": tout, "amount": str(amount), "amount_in_raw": str(raw), "mint_metadata_slot": slot, "execution": "read_only_provider_quote", "provider_scope": "Raydium routing only", "block_number": None, "limits": ["Provider quote is not pinned to mint metadata slot", "No transaction was built, simulated, signed or sent", "No total execution gas/priority/rent, token transfer-tax or MEV guarantee", "Raydium routing is not a proof of a global or cross-DEX optimum"], "profitable_routes": 0, "is_profitable": False, "net_spread_bps": None}
        if tool == "smart_router":
            return {**base, "status": "success", "quoted_pools": len(buy["route_plan"]), "optimal_routes": [{**buy, "allocation_pct": 100}], "latency_ms": round((time.perf_counter()-start)*1000, 2)}
        sell = await ray_quote(tout, tin, int(buy["amount_out_raw"]))
        shared = {h["poolId"] for h in buy["route_plan"]} & {h["poolId"] for h in sell["route_plan"]}
        gross = (Decimal(sell["amount_out_raw"])-raw)*10000/raw
        route = {"buy": buy, "sell": sell, "gross_profit_raw": str(int(sell["amount_out_raw"])-raw), "gross_spread_bps": float(gross), "shared_pools": sorted(shared), "independent_pool_paths": not shared, "net_spread_bps": None, "is_profitable": False, "cost_status": "execution_costs_unproven", "meets_gross_threshold": gross >= threshold and not shared}
        return {**base, "pair": args.get("pair", "SOL/USDC"), "quoted_pools": len({h["poolId"] for leg in (buy,sell) for h in leg["route_plan"]}), "routes": [route] if not shared else [], "acquired_legs": [buy,sell], "top_route": route if not shared else None, "status": "quoted" if not shared else "no_independent_route", "gross_candidates": int(gross >= threshold and not shared), "latency_ms": round((time.perf_counter()-start)*1000, 2)}


async def _compute_quote(tool, args):
    start = time.perf_counter()
    tin, tout, amount, threshold = validate_request(tool, args)
    async with httpx.AsyncClient(timeout=8.0) as client:
        engine = await BaseQuotes(client).setup(tin, tout)
        with localcontext() as context:
            context.prec = 600
            raw_decimal = amount * (Decimal(10) ** engine.decimals[tin])
        if raw_decimal != raw_decimal.to_integral_value() or raw_decimal >= Decimal(2) ** 256:
            raise QuoteError("INVALID_AMOUNT_PRECISION", "amount exceeds token decimals or uint256", 400)
        raw = int(raw_decimal)
        pools, errors = await engine.discover(tin, tout)
        quotes = []
        for pool in pools:
            try:
                quotes.append((pool, await engine.quote(pool, tin, tout, raw)))
            except QuoteError as exc:
                errors.append({"provider": pool["dex"], "pool": pool["pool"], "code": exc.code})
        base = {"service": "x402-agent-tollbooth", "chain": "base", "tokenIn": tin, "tokenOut": tout, "amount": str(amount), "amount_in_raw": str(raw), "pairs_scanned": len(pools), "quoted_pools": len(quotes), "provider_errors": errors, "block_number": int(engine.block, 16), "block_hash": engine.block_info["hash"], "observed_at": datetime.now(timezone.utc).isoformat(), "execution": "read_only_eth_call", "latency_ms": round((time.perf_counter()-start)*1000, 2), "limits": ["Quotes are not executed trades or guaranteed fills", "No token-transfer taxes, MEV or transaction total gas cost are proven", "Only supported direct Base pools are evaluated; no global or split-route optimum is claimed"]}
        if not quotes:
            if errors:
                raise QuoteError("QUOTE_ACQUISITION_FAILED", "No usable amount-dependent quotes; provider or adapter errors prevent a liquidity conclusion")
            return {**base, "status": "no_liquidity", "optimal_routes": [], "routes": [], "profitable_routes": 0, "is_profitable": False, "top_route": None}
        if tool == "smart_router":
            best = max((q for _, q in quotes), key=lambda q: int(q["amount_out_raw"]))
            return {**base, "status": "success", "optimal_routes": [{**best, "allocation_pct": 100}], "candidate_quotes": [q for _, q in quotes], "optimization_scope": "best acquired direct quote for the exact requested amount", "estimated_slippage_bps": None}
        routes = []
        for buy_pool, buy in quotes:
            for sell_pool in pools:
                if sell_pool["pool"] == buy_pool["pool"]:
                    continue
                try:
                    sell = await engine.quote(sell_pool, tout, tin, int(buy["amount_out_raw"]))
                    returned = int(sell["amount_out_raw"])
                    gross = (Decimal(returned)-raw) * 10000 / raw
                    routes.append({"buy": buy, "sell": sell, "round_trip_output_raw": str(returned), "gross_profit_raw": str(returned-raw), "gross_spread_bps": float(gross), "meets_gross_threshold": gross >= threshold, "net_spread_bps": None, "is_profitable": False, "cost_status": "execution_gas_and_other_costs_unproven"})
                except QuoteError as exc:
                    errors.append({"provider": sell_pool["dex"], "pool": sell_pool["pool"], "leg": "return", "code": exc.code})
        if not routes:
            raise QuoteError("INSUFFICIENT_ROUND_TRIP_QUOTES", "No distinct-pool round-trip quote could be acquired")
        routes.sort(key=lambda route: int(route["round_trip_output_raw"]), reverse=True)
        return {**base, "latency_ms": round((time.perf_counter()-start)*1000, 2), "pair": args.get("pair", "WETH/USDC"), "status": "quoted", "routes": routes, "top_route": routes[0], "profitable_routes": 0, "gross_candidates": sum(r["meets_gross_threshold"] for r in routes), "net_spread_bps": None, "is_profitable": False}
