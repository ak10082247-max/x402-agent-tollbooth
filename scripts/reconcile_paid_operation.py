"""Owner-run recovery from finalized public chain evidence. No signing or /settle.

Run on the service host with its journal mounted. The payment file holds the
original public PAYMENT-SIGNATURE header, never a wallet private key. The operator
must supply the actual transaction from the facilitator or chain explorer.
"""
import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
import tollbooth_agent as service
from paid_execution import connect, recover_verified_delivery
from eth_utils import keccak


class ReconciliationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ReconciliationError(message)


def signature_message(serialized):
    count, offset, shift = 0, 0, 0
    for byte in serialized:
        count |= (byte & 127) << shift
        offset += 1
        if not byte & 128:
            break
        shift += 7
        require(shift <= 14, "Invalid signature count")
    require(count == 2 and len(serialized) > offset + 128, "Expected sponsored two-signature transaction")
    return serialized[offset:offset + 64], serialized[offset + 128:]


def prove_base(rpc, body, transaction):
    require(re.fullmatch(r"0x[0-9a-fA-F]{64}", transaction), "Invalid Base transaction hash")
    require(int(rpc("eth_chainId", []), 16) == 8453, "RPC chain is not Base mainnet")
    receipt = rpc("eth_getTransactionReceipt", [transaction])
    require(isinstance(receipt, dict) and receipt.get("transactionHash", "").lower() == transaction.lower(), "Transaction receipt is unavailable or substituted")
    require(receipt.get("status") == "0x1", "Base transaction did not succeed")
    block = rpc("eth_getBlockByNumber", [receipt["blockNumber"], False])
    finalized = rpc("eth_getBlockByNumber", ["finalized", False])
    require(block and finalized and block.get("hash") == receipt.get("blockHash") and int(finalized["number"], 16) >= int(receipt["blockNumber"], 16), "Base payment is not finalized on the canonical block")
    quote, auth = body["paymentRequirements"], body["paymentPayload"]["payload"]["authorization"]
    payer, recipient, amount = auth["from"].lower(), quote["payTo"].lower(), int(quote["amount"])
    transfer_topic = "0x" + keccak(text="Transfer(address,address,uint256)").hex()
    used_topic = "0x" + keccak(text="AuthorizationUsed(address,bytes32)").hex()
    buyer_delta, merchant_delta, authorization_seen = 0, 0, False
    for log in receipt.get("logs", []):
        if str(log.get("address", "")).lower() != quote["asset"].lower() or log.get("removed"):
            continue
        topics = [str(topic).lower() for topic in log.get("topics", [])]
        if len(topics) == 3 and topics[0] == transfer_topic:
            sender, target, value = "0x" + topics[1][-40:], "0x" + topics[2][-40:], int(log["data"], 16)
            buyer_delta += (value if target == payer else 0) - (value if sender == payer else 0)
            merchant_delta += (value if target == recipient else 0) - (value if sender == recipient else 0)
        if len(topics) == 3 and topics[0] == used_topic and "0x" + topics[1][-40:] == payer and topics[2] == auth["nonce"].lower():
            authorization_seen = True
    require(authorization_seen and buyer_delta == -amount and merchant_delta == amount, "Finalized USDC transfer or authorization nonce does not match this purchase")
    return {"chain": "base", "block_number": int(receipt["blockNumber"], 16), "block_hash": receipt["blockHash"], "commitment": "finalized"}


def prove_solana(rpc, body, transaction):
    require(isinstance(transaction, str) and re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{80,90}", transaction), "Invalid Solana transaction signature")
    require(rpc("getGenesisHash", []) == "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d", "RPC genesis is not Solana mainnet")
    response = rpc("getTransaction", [transaction, {"encoding": "base64", "commitment": "finalized", "maxSupportedTransactionVersion": 0}])
    require(isinstance(response, dict) and isinstance(response.get("meta"), dict) and "err" in response["meta"] and response["meta"]["err"] is None, "Solana transaction is unavailable, unfinalized or unsuccessful")
    raw = base64.b64decode(response["transaction"][0], validate=True)
    sponsor_signature, actual_message = signature_message(raw)
    require(service._encode_base58(sponsor_signature) == transaction, "Returned transaction signature differs from requested transaction")
    signed = base64.b64decode(body["paymentPayload"]["payload"]["transaction"], validate=True)
    _, expected_message = signature_message(signed)
    require(actual_message == expected_message, "Settled Solana message differs from the signed purchase")
    quote, payer = body["paymentRequirements"], service._canonical_payer(body)
    balances = {}
    for direction, name in ((-1, "preTokenBalances"), (1, "postTokenBalances")):
        require(isinstance(response["meta"].get(name), list), "USDC token-balance proof is unavailable")
        for entry in response["meta"][name]:
            if entry.get("mint") != quote["asset"]:
                continue
            require(entry.get("uiTokenAmount", {}).get("decimals") == 6 and isinstance(entry.get("owner"), str), "Invalid USDC token-balance metadata")
            owner = entry["owner"]
            balances[owner] = balances.get(owner, 0) + direction * int(entry["uiTokenAmount"]["amount"])
    amount = int(quote["amount"])
    require(balances.get(payer) == -amount and balances.get(quote["payTo"]) == amount, "Finalized Solana USDC debit and credit differ from this purchase")
    require(type(response.get("slot")) is int and response["slot"] > 0, "Missing finalized Solana slot")
    return {"chain": "solana", "slot": response["slot"], "commitment": "finalized", "message_matches_signed_purchase": True}


def reconcile(raw_header, tool, transaction, rpc):
    identity, network = service.payment_identity(raw_header, tool)
    body = service.canonical_payment(raw_header, tool)
    # Inspect the retained operation before consuming RPC resources or mutating it.
    with connect() as connection:
        row = connection.execute("SELECT tool,state,response_json FROM paid_fulfillments WHERE authorization_id=?", (identity,)).fetchone()
    require(row and row[0] == tool and row[1] in ("settling", "settlement_unknown") and row[2], "No matching retained operation awaits reconciliation")
    proof = (prove_base if network == service.NETWORK else prove_solana)(rpc, body, transaction)
    receipt = service.validate_paid_receipt({"success": True, "transaction": transaction, "payer": service._canonical_payer(body), "network": network}, raw_header, tool)
    prepared = json.loads(row[2])
    if isinstance(prepared.get("method"), str):
        receipt["fulfillment_method"] = prepared["method"]
    receipt["operator_reconciliation"] = proof
    recover_verified_delivery(identity, tool, receipt)
    return {"authorization_id": identity, "state": "delivered", "transaction": transaction, "proof": proof, "new_settlements_submitted": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payment-file", required=True, type=Path)
    parser.add_argument("--tool", required=True, choices=service.TOLL_ENDPOINTS)
    parser.add_argument("--transaction", required=True)
    args = parser.parse_args()
    require(args.payment_file.stat().st_size <= 65536, "Payment header file is too large")
    raw = args.payment_file.read_text(encoding="utf-8").strip()
    _, network = service.payment_identity(raw, args.tool)
    rpc_url = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org") if network == service.NETWORK else os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    with httpx.Client(timeout=15.0, follow_redirects=False) as client:
        def rpc(method, params):
            require(method in {"eth_chainId", "eth_getTransactionReceipt", "eth_getBlockByNumber", "getGenesisHash", "getTransaction"}, "Only allowlisted read-only RPC methods are supported")
            response = client.post(rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            require(response.status_code == 200, "Read-only RPC is unavailable")
            data = response.json()
            require(isinstance(data, dict) and not data.get("error") and "result" in data, "Read-only RPC did not return valid evidence")
            return data["result"]
        print(json.dumps(reconcile(raw, args.tool, args.transaction, rpc), indent=2))


if __name__ == "__main__":
    try:
        main()
    except ReconciliationError as exc:
        print(json.dumps({"error": str(exc), "new_settlements_submitted": 0}), file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        # Provider URLs can contain credentials; never print exception details.
        print(json.dumps({"error": type(exc).__name__, "new_settlements_submitted": 0}), file=sys.stderr)
        raise SystemExit(1)
