import asyncio
import base64
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from eth_abi import encode, decode
from eth_utils import keccak
from eth_account import Account
from eth_account.messages import encode_typed_data
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import tollbooth_agent as appmod
import live_quotes as quotes
import paid_execution as journal
from scripts import reconcile_paid_operation as recovery

# Deterministic, unfunded fixture key. Never loaded from an environment or wallet.
FIXTURE_KEY = bytes.fromhex("01" * 32)
PAYER = Account.from_key(FIXTURE_KEY).address
POOL1 = "0x2222222222222222222222222222222222222222"
POOL2 = "0x3333333333333333333333333333333333333333"


def authorization(tool="arbitrage_scan", nonce=1, **overrides):
    accepted = dict(appmod.CHALLENGE_CACHE[tool]["body"]["accepts"][0])
    body = {"x402Version": 2, "accepted": accepted, "resource": {"url": appmod.PUBLIC_BASE_URL + appmod.TOLL_ENDPOINTS[tool]["path"]}, "payload": {"signature": "0x" + "aa" * 65, "authorization": {"from": PAYER, "to": appmod.WALLET_ADDRESS, "value": appmod.TOLL_ENDPOINTS[tool]["amount_microunits"], "validAfter": "0", "validBefore": str(int(time.time())+120), "nonce": "0x" + format(nonce, "064x")}}}
    body.update(overrides)
    auth = body["payload"]["authorization"]
    typed = {"types": {"EIP712Domain": [{"name": "name", "type": "string"}, {"name": "version", "type": "string"}, {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"}], "TransferWithAuthorization": [{"name": "from", "type": "address"}, {"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}, {"name": "validAfter", "type": "uint256"}, {"name": "validBefore", "type": "uint256"}, {"name": "nonce", "type": "bytes32"}]}, "primaryType": "TransferWithAuthorization", "domain": {"name": "USD Coin", "version": "2", "chainId": appmod.CHAIN_ID, "verifyingContract": appmod.ASSET}, "message": {**auth, "value": int(auth["value"]), "validAfter": int(auth["validAfter"]), "validBefore": int(auth["validBefore"])}}
    body["payload"]["signature"] = "0x" + Account.sign_message(encode_typed_data(full_message=typed), FIXTURE_KEY).signature.hex().removeprefix("0x")
    return base64.b64encode(json.dumps(body).encode()).decode()


class RouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"PAYMENTS_DB_PATH": str(Path(self.tmp.name) / "payments.db")})
        self.env.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=appmod.app), base_url="https://test")
        self.telemetry = patch.object(appmod, "record_delivery")
        self.telemetry.start()
        self.verification = patch.object(appmod, "verify_payment_authorization", AsyncMock())
        self.verification.start()

    async def asyncTearDown(self):
        await self.client.aclose()
        self.env.stop()
        self.telemetry.stop()
        self.verification.stop()
        self.tmp.cleanup()

    async def test_unsigned_routes_challenge_both_chains(self):
        for config in appmod.TOLL_ENDPOINTS.values():
            result = await self.client.get(config["path"])
            self.assertEqual(result.status_code, 402)
            body = json.loads(base64.b64decode(result.headers["payment-required"]))
            self.assertEqual(len(body["accepts"]), 2)

    async def test_arbitrage_invalid_amount_never_settles(self):
        for amount in (0, -1, True, "NaN", "Infinity", None):
            with patch.object(appmod, "try_settle_payment") as settle:
                result = await self.client.post("/toll/arbitrage_scan", json={"amount": amount}, headers={"PAYMENT-SIGNATURE": authorization()})
                self.assertEqual(result.status_code, 400)
                settle.assert_not_called()

    async def test_chain_and_exact_amount_bound_before_settlement(self):
        for args in ({"chain": "ethereum"}, {"pair": "WETH/WETH"}, {"min_spread_bps": True}):
            with patch.object(appmod, "try_settle_payment") as settle:
                result = await self.client.post("/toll/arbitrage_scan", json=args, headers={"PAYMENT-SIGNATURE": authorization()})
                self.assertEqual(result.status_code, 400)
                settle.assert_not_called()

    async def test_accepted_resource_amount_recipient_and_auth_must_match(self):
        for field, value in (("amount", "999999"), ("asset", PAYER), ("payTo", PAYER), ("network", "eip155:1")):
            body = json.loads(base64.b64decode(authorization()))
            body["accepted"][field] = value
            with self.assertRaises(quotes.QuoteError):
                appmod.payment_identity(json.dumps(body), "arbitrage_scan")
        body = json.loads(base64.b64decode(authorization()))
        body["resource"]["url"] += "wrong"
        with self.assertRaises(quotes.QuoteError):
            appmod.payment_identity(json.dumps(body), "arbitrage_scan")

    async def test_invalid_signature_rejected_without_provider_or_payment(self):
        body = json.loads(base64.b64decode(authorization()))
        body["payload"]["signature"] = "0x" + "00" * 65
        with patch.object(appmod, "execute_tool", AsyncMock()) as execute, patch.object(appmod, "try_settle_payment") as settle:
            result = await self.client.post("/toll/arbitrage_scan", json={}, headers={"PAYMENT-SIGNATURE": json.dumps(body)})
            self.assertEqual(result.status_code, 400)
            execute.assert_not_called()
            settle.assert_not_called()

    async def test_solana_receipt_has_exact_network_amount_and_resource(self):
        fixture = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("02" * 32))
        public = fixture.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        message = bytes([128, 2, 0, 0, 2]) + appmod._decode_b58_32(appmod.SOLANA_FEE_PAYER) + public + bytes(32) + bytes([0, 0])
        transaction = bytes([2]) + bytes(64) + fixture.sign(message) + message
        payload = {"x402Version": 2, "accepted": dict(appmod.CHALLENGE_CACHE["arbitrage_scan"]["body"]["accepts"][1]), "resource": {"url": appmod.PUBLIC_BASE_URL + "/toll/arbitrage_scan"}, "payload": {"transaction": base64.b64encode(transaction).decode()}}
        settlement = {"success": True, "transaction": appmod._encode_base58(bytes.fromhex("01" * 64)), "payer": appmod._encode_base58(public), "network": appmod.SOLANA_NETWORK}
        with patch.object(appmod, "execute_tool", AsyncMock(return_value={"status": "quoted"})), patch.object(appmod, "try_settle_payment", return_value=(True, settlement, None)):
            result = await self.client.post("/toll/arbitrage_scan", json={}, headers={"PAYMENT-SIGNATURE": json.dumps(payload)})
        self.assertEqual(result.status_code, 200)
        receipt = json.loads(base64.b64decode(result.headers["payment-response"]))
        self.assertTrue(receipt["success"])
        self.assertEqual(receipt["amount"], "2000")
        self.assertEqual(receipt["network"], appmod.SOLANA_NETWORK)
        self.assertEqual(receipt["resource"], appmod.PUBLIC_BASE_URL + "/toll/arbitrage_scan")

    async def test_mismatched_or_malformed_settlement_cannot_deliver(self):
        valid = {"success": True, "transaction": "0x" + "ab" * 32, "payer": PAYER, "network": appmod.NETWORK}
        for nonce, change in enumerate(({"transaction": "invented"}, {"payer": appmod.WALLET_ADDRESS}, {"amount": "1"}, {"resource": "https://other.invalid/"}), 800):
            with patch.object(appmod, "execute_tool", AsyncMock(return_value={"status": "quoted"})), patch.object(appmod, "try_settle_payment", return_value=(True, {**valid, **change}, None)) as settle:
                header = {"PAYMENT-SIGNATURE": authorization(nonce=nonce)}
                first = await self.client.post("/toll/arbitrage_scan", json={}, headers=header)
                second = await self.client.post("/toll/arbitrage_scan", json={}, headers=header)
            self.assertEqual(first.status_code, 503)
            self.assertEqual(second.status_code, 409)
            self.assertNotIn("payment-response", first.headers)
            settle.assert_called_once()

    async def test_future_or_overlong_new_authorization_never_consumes_provider(self):
        for nonce, after, before in ((901, int(time.time()) + 30, int(time.time()) + 120), (902, 0, int(time.time()) + 1000)):
            body = json.loads(base64.b64decode(authorization(nonce=nonce)))
            body["payload"]["authorization"].update(validAfter=str(after), validBefore=str(before))
            header = authorization(nonce=nonce, payload=body["payload"])
            with patch.object(appmod, "execute_tool", AsyncMock()) as execute, patch.object(appmod, "try_settle_payment") as settle:
                result = await self.client.post("/toll/arbitrage_scan", json={}, headers={"PAYMENT-SIGNATURE": header})
            self.assertEqual(result.status_code, 400)
            execute.assert_not_called()
            settle.assert_not_called()

    async def test_blink_and_feed_cannot_fabricate_paid_or_safe_result(self):
        action = await self.client.get("/api/actions/scan")
        self.assertTrue(action.json()["disabled"])
        purchase = await self.client.post("/api/actions/scan", json={"account": "fixture"})
        self.assertEqual(purchase.status_code, 503)
        self.assertFalse(purchase.json()["charged"])
        self.assertNotIn("transaction", purchase.json())
        self.assertEqual((await self.client.get("/v1/feed/live-alerts")).json()["alerts"], [])

    async def test_dapp_uses_exact_authorization_not_unbound_transfer(self):
        page = (await self.client.get("/dapp")).text
        self.assertIn("accepted.amount !== '20000'", page)
        self.assertIn("_signTypedData", page)
        self.assertNotIn("usdc.transfer", page)

    async def test_provider_error_is_not_charged_or_liquidity_claim(self):
        with patch.object(appmod, "execute_tool", AsyncMock(side_effect=quotes.QuoteError("RPC_UNAVAILABLE", "RPC unavailable"))), patch.object(appmod, "try_settle_payment") as settle:
            result = await self.client.post("/toll/arbitrage_scan", json={"amount": "1000"}, headers={"PAYMENT-SIGNATURE": authorization()})
            self.assertEqual(result.status_code, 503)
            self.assertFalse(result.json()["charged"])
            settle.assert_not_called()

    async def test_read_only_payment_rejection_blocks_expensive_provider_and_settlement(self):
        with patch.object(appmod, "verify_payment_authorization", AsyncMock(side_effect=quotes.QuoteError("PAYMENT_NOT_VERIFIED", "Insufficient funding", 402))), patch.object(appmod, "execute_tool", AsyncMock()) as execute, patch.object(appmod, "try_settle_payment") as settle:
            result = await self.client.post("/toll/arbitrage_scan", json={}, headers={"PAYMENT-SIGNATURE": authorization()})
            self.assertEqual(result.status_code, 402)
            self.assertFalse(result.json()["charged"])
            execute.assert_not_called()
            settle.assert_not_called()

    async def test_exact_retry_recovers_without_resettling_and_conflict_rejected(self):
        result_data = {"status": "quoted", "routes": [{"amount_in_raw": "1000000"}]}
        settlement = {"success": True, "transaction": "0x" + "ab" * 32, "payer": PAYER, "network": appmod.NETWORK}
        with patch.object(appmod, "execute_tool", AsyncMock(return_value=result_data)) as execute, patch.object(appmod, "try_settle_payment", return_value=(True, settlement, None)) as settle:
            header = {"PAYMENT-SIGNATURE": authorization()}
            first = await self.client.post("/toll/arbitrage_scan", json={"amount": "1000"}, headers=header)
            second = await self.client.post("/toll/arbitrage_scan", json={"amount": "1000"}, headers=header)
            conflict = await self.client.post("/toll/arbitrage_scan", json={"amount": "2000"}, headers=header)
            self.assertEqual(first.status_code, 200)
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.headers["x-payment-recovered"], "true")
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(first.json(), second.json())
            receipt = json.loads(base64.b64decode(first.headers["payment-response"]))
            self.assertEqual(receipt["amount"], "2000")
            self.assertEqual(receipt["resource"], appmod.PUBLIC_BASE_URL + "/toll/arbitrage_scan")
            self.assertTrue(receipt["success"])
            # Recovery authenticates the same signature but does not need a still-live payment window.
            with patch.object(appmod.time, "time", return_value=int(time.time())+1000):
                recovered_expired = await self.client.post("/toll/arbitrage_scan", json={"amount": "1000"}, headers=header)
            self.assertEqual(recovered_expired.status_code, 200)
            settle.assert_called_once()
            execute.assert_awaited_once()

    async def test_unknown_settlement_retained_and_not_retried(self):
        with patch.object(appmod, "execute_tool", AsyncMock(return_value={"status": "quoted"})), patch.object(appmod, "try_settle_payment", side_effect=TimeoutError("timeout")) as settle:
            header = {"PAYMENT-SIGNATURE": authorization()}
            first = await self.client.post("/toll/arbitrage_scan", json={}, headers=header)
            second = await self.client.post("/toll/arbitrage_scan", json={}, headers=header)
            self.assertEqual(first.status_code, 503)
            self.assertEqual(second.status_code, 409)
            settle.assert_called_once()
            identity, _ = appmod.payment_identity(header["PAYMENT-SIGNATURE"], "arbitrage_scan")
            self.assertEqual(journal.claim(identity, "arbitrage_scan", {})["response"], {"status": "quoted"})

    async def test_mcp_call_challenges_then_uses_same_paid_executor(self):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "arbitrage_scan", "arguments": {"amount": "3"}}}
        result = await self.client.post("/mcp", json=body)
        self.assertEqual(result.status_code, 402)
        self.assertTrue(result.json()["result"]["isError"])
        settlement = {"success": True, "transaction": "0x" + "ab" * 32, "payer": PAYER, "network": appmod.NETWORK}
        with patch.object(appmod, "execute_tool", AsyncMock(return_value={"status": "quoted", "amount": "3"})) as execute, patch.object(appmod, "try_settle_payment", return_value=(True, settlement, None)):
            result = await self.client.post("/mcp", json=body, headers={"PAYMENT-SIGNATURE": authorization()})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["result"]["structuredContent"]["amount"], "3")
            self.assertEqual(int(result.headers["content-length"]), len(result.content))
            execute.assert_awaited_once_with("arbitrage_scan", {"amount": "3"})

    async def test_audit_without_verified_source_fails_before_charge(self):
        with patch.object(appmod, "fetch_contract_code", AsyncMock(return_value=None)), patch.object(appmod, "try_settle_payment") as settle:
            result = await self.client.post("/api/audit", json={"contractAddress": PAYER}, headers={"PAYMENT-SIGNATURE": authorization("contract_audit")})
            self.assertEqual(result.status_code, 503)
            self.assertEqual(result.json()["error"], "SOURCE_UNAVAILABLE")
            settle.assert_not_called()

    async def test_source_review_never_falls_back_to_safe(self):
        with patch.object(appmod, "ai_client", None):
            result = await appmod.analyze_source("contract T { function x() external { target.delegatecall(data); } }", False, limited_review=True)
            self.assertFalse(result["safety_proven"])
            self.assertIsNone(result["score"])
            self.assertEqual(result["findings"][0]["indicator"], "delegatecall")

    async def test_missing_model_does_not_charge_for_silent_pattern_fallback(self):
        with patch.object(appmod, "ai_client", None), patch.object(appmod, "try_settle_payment") as settle:
            response = await self.client.post("/toll/ai_intel", json={"prompt": "contract OwnerFixture {}"}, headers={"PAYMENT-SIGNATURE": authorization("ai_intel")})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.json()["charged"])
        settle.assert_not_called()

    async def test_reclaimed_preparation_fences_paused_worker_out_of_settlement(self):
        entered, resume = asyncio.Event(), asyncio.Event()
        calls = 0
        async def fulfill(*args):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                await resume.wait()
                return {"status": "quoted", "worker": "stale"}
            return {"status": "quoted", "worker": "current"}
        settled = {"success": True, "transaction": "0x" + "ab" * 32, "payer": PAYER, "network": appmod.NETWORK}
        header = {"PAYMENT-SIGNATURE": authorization(nonce=955)}
        identity, _ = appmod.payment_identity(header["PAYMENT-SIGNATURE"], "arbitrage_scan")
        with patch.object(appmod, "execute_tool", side_effect=fulfill), patch.object(appmod, "try_settle_payment", return_value=(True, settled, None)) as settle:
            first_task = asyncio.create_task(self.client.post("/toll/arbitrage_scan", json={}, headers=header))
            await asyncio.wait_for(entered.wait(), timeout=10)
            with journal.connect() as connection:
                connection.execute("UPDATE paid_fulfillments SET updated_at=? WHERE authorization_id=?", (time.time() - journal.PREPARATION_LEASE_SECONDS - 1, identity))
            current = await self.client.post("/toll/arbitrage_scan", json={}, headers=header)
            resume.set()
            stale = await first_task
        self.assertEqual(current.status_code, 200)
        self.assertEqual(current.json()["worker"], "current")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["error"], "PREPARATION_SUPERSEDED")
        settle.assert_called_once()
        self.assertEqual(journal.claim(identity, "arbitrage_scan", {})["response"]["worker"], "current")

    async def test_version_revision(self):
        with patch.dict(os.environ, {"RENDER_GIT_COMMIT": "revision-under-test"}):
            response = await self.client.get("/version")
            self.assertEqual(response.json()["revision"], "revision-under-test")


class RecoveryProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"PAYMENTS_DB_PATH": str(Path(self.temp.name) / "recover.db")})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def retain(self, raw):
        identity, _ = appmod.payment_identity(raw, "arbitrage_scan")
        owner = journal.claim(identity, "arbitrage_scan", {})["owner"]
        journal.prepare(identity, {"status": "quoted", "retained": "actual requested result"}, owner)
        journal.finish(identity, "settlement_unknown", owner=owner)
        return identity

    def base_rpc(self, raw, *, wrong_nonce=False):
        auth = json.loads(base64.b64decode(raw))["payload"]["authorization"]
        topic = lambda address: "0x" + address[2:].lower().rjust(64, "0")
        block_hash = "0x" + "cc" * 32
        transaction = "0x" + "ab" * 32
        logs = [
            {"address": appmod.ASSET, "topics": ["0x" + keccak(text="Transfer(address,address,uint256)").hex(), topic(PAYER), topic(appmod.WALLET_ADDRESS)], "data": hex(2000)},
            {"address": appmod.ASSET, "topics": ["0x" + keccak(text="AuthorizationUsed(address,bytes32)").hex(), topic(PAYER), "0x" + "00" * 32 if wrong_nonce else auth["nonce"]], "data": "0x"},
        ]
        def rpc(method, params):
            if method == "eth_chainId":
                return "0x2105"
            if method == "eth_getTransactionReceipt":
                return {"transactionHash": transaction, "status": "0x1", "blockHash": block_hash, "blockNumber": "0x123", "logs": logs}
            if method == "eth_getBlockByNumber":
                return {"hash": block_hash, "number": "0x123"}
            self.fail("Recovery may only read public chain evidence")
        return transaction, rpc

    def test_finalized_base_transfer_and_nonce_recover_retained_delivery_without_settlement(self):
        raw = authorization(nonce=998)
        identity = self.retain(raw)
        transaction, rpc = self.base_rpc(raw)
        with patch.object(appmod, "try_settle_payment", side_effect=AssertionError("Recovery must never settle")):
            result = recovery.reconcile(raw, "arbitrage_scan", transaction, rpc)
        self.assertEqual(result["new_settlements_submitted"], 0)
        recovered = journal.claim(identity, "arbitrage_scan", {})
        self.assertEqual(recovered["state"], "delivered")
        self.assertEqual(recovered["response"]["retained"], "actual requested result")
        self.assertEqual(recovered["receipt"]["operator_reconciliation"]["commitment"], "finalized")

    def test_same_value_transfer_with_different_nonce_cannot_recover_purchase(self):
        raw = authorization(nonce=999)
        identity = self.retain(raw)
        transaction, rpc = self.base_rpc(raw, wrong_nonce=True)
        with self.assertRaises(recovery.ReconciliationError):
            recovery.reconcile(raw, "arbitrage_scan", transaction, rpc)
        self.assertEqual(journal.claim(identity, "arbitrage_scan", {})["state"], "settlement_unknown")

    def test_solana_recovery_requires_exact_signed_message_and_usdc_debit_credit(self):
        # Fully synthetic RPC fixture; no Solana transfer is submitted.
        fixture = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("02" * 32))
        public = fixture.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        message = bytes([128, 2, 0, 0, 2]) + appmod._decode_b58_32(appmod.SOLANA_FEE_PAYER) + public + bytes(32) + bytes([0, 0])
        buyer_signature = fixture.sign(message)
        signed = bytes([2]) + bytes(64) + buyer_signature + message
        payload = {"x402Version": 2, "accepted": dict(appmod.CHALLENGE_CACHE["arbitrage_scan"]["body"]["accepts"][1]), "payload": {"transaction": base64.b64encode(signed).decode()}}
        raw = json.dumps(payload)
        identity = self.retain(raw)
        transaction = appmod._encode_base58(bytes.fromhex("03" * 64))
        actual = bytes([2]) + bytes.fromhex("03" * 64) + buyer_signature + message
        payer = appmod._encode_base58(public)
        entry = lambda owner, amount: {"owner": owner, "mint": appmod.SOLANA_USDC_MINT, "uiTokenAmount": {"decimals": 6, "amount": str(amount)}}
        result = {"slot": 1234, "transaction": [base64.b64encode(actual).decode(), "base64"], "meta": {"err": None, "preTokenBalances": [entry(payer, 3000), entry(appmod.SOLANA_WALLET_ADDRESS, 0)], "postTokenBalances": [entry(payer, 1000), entry(appmod.SOLANA_WALLET_ADDRESS, 2000)]}}
        def rpc(method, params):
            return "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d" if method == "getGenesisHash" else result
        result["meta"]["postTokenBalances"][1] = entry(appmod.SOLANA_WALLET_ADDRESS, 1999)
        with self.assertRaises(recovery.ReconciliationError):
            recovery.reconcile(raw, "arbitrage_scan", transaction, rpc)
        self.assertEqual(journal.claim(identity, "arbitrage_scan", {})["state"], "settlement_unknown")
        result["meta"]["postTokenBalances"][1] = entry(appmod.SOLANA_WALLET_ADDRESS, 2000)
        recovered = recovery.reconcile(raw, "arbitrage_scan", transaction, rpc)
        self.assertEqual(recovered["state"], "delivered")


class ModelCostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"PAYMENTS_DB_PATH": str(Path(self.temp.name) / "costs.db")})
        self.environment.start()

    async def asyncTearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    async def test_counted_input_and_maximum_output_fit_actual_endpoint_budget(self):
        calls = []
        def generate(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(text='{"findings": []}', usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=100, thoughts_token_count=0))
        client = SimpleNamespace(models=SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(total_tokens=100), generate_content=generate))
        # Fixture rates are test inputs, not a claim about provider prices.
        with patch.object(appmod, "ai_client", client), patch.dict(os.environ, {"AUDIT_INPUT_USD_PER_MILLION": "0.3", "AUDIT_OUTPUT_USD_PER_MILLION": "2.5", "AUDIT_MAX_PROVIDER_COST_RATIO": "0.5", "AUDIT_MAX_OUTPUT_TOKENS": "2048"}):
            result = await appmod.analyze_source("contract T {}", revenue_usdc="0.001")
        self.assertLessEqual(calls[0]["config"]["max_output_tokens"], 188)
        self.assertEqual(calls[0]["config"]["thinking_config"]["thinking_budget"], 0)
        self.assertEqual(result["provider_usage"]["estimated_provider_cost_usd"], "0.00028")
        self.assertFalse(result["provider_usage"]["accounting_profit_proven"])

    async def test_unaffordable_input_never_starts_model_generation(self):
        from unittest.mock import Mock
        generate = Mock()
        client = SimpleNamespace(models=SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(total_tokens=100000), generate_content=generate))
        with patch.object(appmod, "ai_client", client), patch.dict(os.environ, {"AUDIT_INPUT_USD_PER_MILLION": "0.3", "AUDIT_OUTPUT_USD_PER_MILLION": "2.5", "AUDIT_MAX_PROVIDER_COST_RATIO": "0.5", "AUDIT_MAX_OUTPUT_TOKENS": "2048"}):
            with self.assertRaises(quotes.QuoteError) as raised:
                await appmod.analyze_source("contract T {}", revenue_usdc="0.02")
        self.assertEqual(raised.exception.code, "AUDIT_COST_LIMIT_EXCEEDED")
        generate.assert_not_called()

    async def test_missing_pricing_policy_never_counts_or_generates(self):
        from unittest.mock import Mock
        models = Mock()
        with patch.object(appmod, "ai_client", SimpleNamespace(models=models)), patch.dict(os.environ, {"AUDIT_MODEL": "unreviewed-fixture-model"}, clear=True):
            with self.assertRaises(quotes.QuoteError) as raised:
                await appmod.analyze_source("contract T {}")
        self.assertEqual(raised.exception.code, "AUDIT_COST_POLICY_UNCONFIGURED")
        models.assert_not_called()
        models.count_tokens.assert_not_called()
        models.generate_content.assert_not_called()

    async def test_named_default_profile_uses_verified_paid_rates(self):
        with patch.dict(os.environ, {}, clear=True):
            input_rate, output_rate, budget, limit, pricing = appmod._audit_cost_policy("0.001", "gemini-2.5-flash")
        self.assertEqual(str(input_rate), "0.30")
        self.assertEqual(str(output_rate), "2.50")
        self.assertEqual(str(budget), "0.0005")
        self.assertEqual(pricing["pricing_verified_on"], "2026-10-27")

    async def test_invalid_model_json_still_records_measured_operating_cost(self):
        client = SimpleNamespace(models=SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(total_tokens=100), generate_content=lambda **kw: SimpleNamespace(text="incomplete JSON", usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=10, thoughts_token_count=0))))
        with patch.object(appmod, "ai_client", client), patch.dict(os.environ, {"AUDIT_MODEL": "gemini-2.5-flash"}):
            with self.assertRaises(quotes.QuoteError):
                await appmod.analyze_source("contract T {}")
        with journal.connect() as connection:
            row = connection.execute("SELECT state,metadata_json FROM provider_cost_events").fetchone()
        self.assertEqual(row[0], "measured_estimate")
        self.assertEqual(json.loads(row[1])["output_tokens"], 10)
        self.assertFalse(json.loads(row[1])["customer_revenue_confirmed"])

    async def test_generation_failure_preserves_unknown_usage_reservation(self):
        from unittest.mock import Mock
        client = SimpleNamespace(models=SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(total_tokens=100), generate_content=Mock(side_effect=TimeoutError("fixture"))))
        with patch.object(appmod, "ai_client", client), patch.dict(os.environ, {"AUDIT_MODEL": "gemini-2.5-flash"}):
            with self.assertRaises(quotes.QuoteError):
                await appmod.analyze_source("contract T {}")
        with journal.connect() as connection:
            row = connection.execute("SELECT state,metadata_json FROM provider_cost_events").fetchone()
        self.assertEqual(row[0], "reserved_usage_unknown")
        self.assertNotIn("estimated_provider_cost_usd", json.loads(row[1]))

    async def test_unexpected_thinking_usage_is_counted_and_cannot_be_sold(self):
        client = SimpleNamespace(models=SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(total_tokens=100), generate_content=lambda **kw: SimpleNamespace(text='{"findings":[]}', usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=100, thoughts_token_count=100))))
        with patch.object(appmod, "ai_client", client), patch.dict(os.environ, {"AUDIT_MODEL": "gemini-2.5-flash"}):
            with self.assertRaises(quotes.QuoteError) as raised:
                await appmod.analyze_source("contract T {}", revenue_usdc="0.001")
        self.assertEqual(raised.exception.code, "AUDIT_PROVIDER_BUDGET_EXCEEDED")


class SettlementBoundaryTests(unittest.TestCase):
    def test_cdp_timeout_and_server_error_never_submit_to_second_settler(self):
        for failure in (httpx.ReadTimeout("fixture"), httpx.Response(500, json={"error": "post-broadcast failure"}), httpx.Response(200, json={"success": "true"})):
            reply = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
            with patch.object(appmod, "load_cdp_credentials", return_value=("fixture", "fixture")), patch.object(appmod, "generate_cdp_jwt", return_value="fixture"), patch.object(appmod.httpx.Client, "post", **reply) as post, patch.object(appmod, "_settle_via_relay") as relay:
                ok, _, error = appmod.settle_via_cdp_facilitator({}, {})
            self.assertFalse(ok)
            self.assertIn("SETTLEMENT_UNKNOWN", error)
            post.assert_called_once()
            relay.assert_not_called()

    def test_missing_cdp_credentials_use_direct_public_payai_once(self):
        settled = {"success": True, "transaction": "0x" + "ab" * 32, "payer": PAYER, "network": appmod.NETWORK}
        header = authorization()
        with patch.object(appmod, "load_cdp_credentials", return_value=(None, None)), patch.object(appmod.httpx.Client, "post", return_value=httpx.Response(200, json=settled)) as post:
            ok, result, error = appmod.try_settle_payment(header, "arbitrage_scan")
        self.assertTrue(ok)
        self.assertEqual(result, settled)
        self.assertIsNone(error)
        self.assertEqual(post.call_args.args[0], appmod.PAYAI_FACILITATOR_URL + "/settle")
        self.assertEqual(post.call_args.kwargs["json"], appmod.canonical_payment(header, "arbitrage_scan"))
        post.assert_called_once()

    def test_client_cannot_change_version_quote_timeout_or_extra(self):
        for field, value in (("version", 1), ("timeout", 3600), ("extra", {"name": "substituted"})):
            decoded = json.loads(base64.b64decode(authorization()))
            if field == "version":
                decoded["x402Version"] = value
            else:
                decoded["accepted"]["maxTimeoutSeconds" if field == "timeout" else "extra"] = value
            with self.assertRaises(quotes.QuoteError):
                appmod.payment_identity(json.dumps(decoded), "arbitrage_scan")


class QuoteAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_payment_verification_uses_only_canonical_read_only_verify(self):
        requests = []
        def reply(request):
            requests.append(request)
            body = json.loads(request.content)
            self.assertTrue(str(request.url).endswith("/verify"))
            self.assertEqual(body["paymentRequirements"]["amount"], "2000")
            self.assertEqual(body["paymentRequirements"]["network"], appmod.NETWORK)
            self.assertEqual(body["paymentPayload"]["resource"]["url"], appmod.PUBLIC_BASE_URL + "/toll/arbitrage_scan")
            return httpx.Response(200, json={"isValid": True, "payer": PAYER})
        real_client = httpx.AsyncClient
        with patch.object(appmod.httpx, "AsyncClient", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(reply), **kwargs)):
            await appmod.verify_payment_authorization(authorization(), "arbitrage_scan", appmod.NETWORK)
        self.assertEqual(len(requests), 1)

    async def test_solana_unsigned_quote_binds_raw_amount_decimals_mints_and_route(self):
        sol, usdc = quotes.SOLANA_TOKENS["SOL"], quotes.SOLANA_TOKENS["USDC"]
        requests = []
        def reply(request):
            requests.append(request)
            if request.method == "POST":
                body = json.loads(request.content)
                if body["method"] == "getGenesisHash":
                    result = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
                else:
                    result = {"context": {"slot": 1234}, "value": [{"owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "data": {"parsed": {"type": "mint", "info": {"decimals": d}}}} for d in (9, 6)]}
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})
            params = request.url.params
            self.assertEqual(params["amount"], "10000000")
            self.assertEqual(params["inputMint"], sol)
            self.assertEqual(params["outputMint"], usdc)
            return httpx.Response(200, json={"id": "quote-fixture", "success": True, "data": {"swapType": "BaseIn", "inputMint": sol, "outputMint": usdc, "inputAmount": "10000000", "outputAmount": "1000000", "otherAmountThreshold": "995000", "slippageBps": 50, "priceImpactPct": 0.01, "routePlan": [{"poolId": sol, "inputMint": sol, "outputMint": usdc, "feeMint": sol, "feeAmount": "1000"}]}})
        real_client = httpx.AsyncClient
        with patch.object(quotes.httpx, "AsyncClient", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(reply), **kwargs)):
            result = await quotes.compute_quote("smart_router", {"chain": "solana", "tokenIn": "SOL", "tokenOut": "USDC", "amount": "0.01"})
        self.assertEqual(result["amount_in_raw"], "10000000")
        self.assertEqual(result["optimal_routes"][0]["decimals_out"], 6)
        self.assertEqual(result["mint_metadata_slot"], 1234)
        self.assertIsNone(result["block_number"])
        self.assertTrue(all("transaction/swap" not in str(request.url) for request in requests))

    async def test_solana_rpc_failure_is_not_missing_mint(self):
        real_client = httpx.AsyncClient
        with patch.object(quotes.httpx, "AsyncClient", side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(lambda request: httpx.Response(503)), **kwargs)):
            with self.assertRaises(quotes.QuoteError) as raised:
                await quotes.compute_quote("smart_router", {"chain": "solana", "amount": "0.01"})
        self.assertEqual(raised.exception.code, "SOLANA_RPC_UNAVAILABLE")

    async def test_round_trip_uses_actual_first_leg_output_and_no_invented_net_profit(self):
        tin, tout = quotes.TOKENS["USDC"].lower(), quotes.TOKENS["WETH"].lower()
        calls = []
        class Engine:
            def __init__(self, client):
                self.decimals = {tin: 6, tout: 18}
                self.block = "0x123"
                self.block_info = {"hash": "0x" + "ab" * 32}
            async def setup(self, *args): return self
            async def discover(self, *args): return [{"pool": POOL1, "dex": "uniswap"}, {"pool": POOL2, "dex": "aerodrome"}], []
            async def quote(self, pool, token_in, token_out, amount):
                calls.append((pool["pool"], token_in, token_out, amount))
                output = 777 if token_in == tin else 10010000
                return {"pool": pool["pool"], "dex": pool["dex"], "amount_in_raw": str(amount), "amount_out_raw": str(output), "lp_fee_included": True}
        with patch.object(quotes, "BaseQuotes", Engine):
            result = await quotes.compute_quote("arbitrage_scan", {"pair": "USDC/WETH", "amount": "10"})
        self.assertEqual(len(result["routes"]), 2)
        self.assertTrue(all(call[3] == 777 for call in calls if call[1] == tout))
        self.assertEqual(result["top_route"]["gross_profit_raw"], "10000")
        self.assertFalse(result["is_profitable"])
        self.assertIsNone(result["net_spread_bps"])

    async def test_decimal_precision_must_not_round_or_underflow(self):
        tin, tout = quotes.TOKENS["USDC"].lower(), quotes.TOKENS["WETH"].lower()
        class Engine:
            def __init__(self, client): self.decimals = {tin: 6, tout: 18}
            async def setup(self, *args): return self
        with patch.object(quotes, "BaseQuotes", Engine):
            with self.assertRaises(quotes.QuoteError) as raised:
                await quotes.compute_quote("smart_router", {"tokenIn": "USDC", "tokenOut": "WETH", "amount": "0.0000001"})
        self.assertEqual(raised.exception.code, "INVALID_AMOUNT_PRECISION")

    async def test_canonical_quoter_exact_amount_decimal_and_block(self):
        observed = []
        tin, tout = quotes.TOKENS["USDC"].lower(), quotes.TOKENS["WETH"].lower()
        def reply(request):
            if request.method == "GET":
                # Deliberately mismatched/foreign pools must not be quoted.
                return httpx.Response(200, json=[{"chainId": "base", "pairAddress": POOL2, "dexId": "uniswap", "baseToken": {"address": tin}, "quoteToken": {"address": PAYER}}, {"chainId": "ethereum", "pairAddress": POOL2, "baseToken": {"address": tin}, "quoteToken": {"address": tout}}])
            data = json.loads(request.content)
            method, params = data["method"], data["params"]
            if method == "eth_chainId": result = "0x2105"
            elif method == "eth_blockNumber": result = "0x123"
            elif method == "eth_getBlockByNumber": result = {"hash": "0x" + "aa" * 32}
            else:
                self.assertEqual(params[1], "0x123")
                target, call_data = params[0]["to"].lower(), params[0]["data"]
                selector = call_data[:10]
                if selector == "0x" + keccak(text="decimals()")[:4].hex():
                    result = "0x" + encode(("uint8",), (6 if target == tin else 18,)).hex()
                elif selector == "0x" + keccak(text="getPool(address,address,uint24)")[:4].hex():
                    fee = decode(("address", "address", "uint24"), bytes.fromhex(call_data[10:]))[2]
                    result = "0x" + encode(("address",), (POOL1 if fee == 500 else "0x" + "00" * 20,)).hex()
                elif selector == "0x" + keccak(text="token0()")[:4].hex(): result = "0x" + encode(("address",), (tin,)).hex()
                elif selector == "0x" + keccak(text="token1()")[:4].hex(): result = "0x" + encode(("address",), (tout,)).hex()
                elif selector == "0x" + keccak(text="fee()")[:4].hex(): result = "0x" + encode(("uint24",), (500,)).hex()
                else:
                    values = decode(("(address,address,uint256,uint24,uint160)",), bytes.fromhex(call_data[10:]))[0]
                    observed.append(values)
                    result = "0x" + encode(("uint256", "uint160", "uint32", "uint256"), (10**16, 2**96, 2, 100000)).hex()
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})
        transport = httpx.MockTransport(reply)
        real_client = httpx.AsyncClient
        with patch.object(quotes.httpx, "AsyncClient", side_effect=lambda **kwargs: real_client(transport=transport, **kwargs)):
            result = await quotes.compute_quote("smart_router", {"tokenIn": "USDC", "tokenOut": "WETH", "amount": "12.345678"})
        self.assertEqual(observed[0][2], 12345678)
        self.assertEqual(result["amount_in_raw"], "12345678")
        self.assertEqual(result["block_number"], 291)
        self.assertEqual(result["quoted_pools"], 1)
        self.assertEqual(result["optimal_routes"][0]["initialized_ticks_crossed"], 2)
        self.assertIsNone(result["estimated_slippage_bps"])

    async def test_provider_failure_not_no_liquidity(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
            engine = quotes.BaseQuotes(client)
            with self.assertRaises(quotes.QuoteError) as raised:
                await engine.setup(quotes.TOKENS["USDC"].lower(), quotes.TOKENS["WETH"].lower())
            self.assertEqual(raised.exception.code, "RPC_UNAVAILABLE")

    async def test_unusable_precision_rejected(self):
        with self.assertRaises(quotes.QuoteError):
            quotes.positive_decimal("NaN")


if __name__ == "__main__":
    unittest.main()
