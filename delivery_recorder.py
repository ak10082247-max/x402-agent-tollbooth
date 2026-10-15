import json
import os
import time
from datetime import datetime
from typing import Dict, Any, List

MAX_MEMORY_RECORDS = 200
_MEMORY_STORE: List[Dict[str, Any]] = []
_LOG_FILE_PATH = os.path.join(os.path.dirname(__file__), "deliveries.jsonl")

def decode_payer_from_header(raw_header: str) -> Dict[str, Any]:
    if not raw_header:
        return {"payer": "unpaid_probe", "amount": 0.0}
    try:
        import base64
        cleaned = raw_header.strip()
        if not cleaned.startswith("{"):
            cleaned = base64.b64decode(cleaned).decode("utf-8")
        data = json.loads(cleaned)
        
        # Check EIP-3009 transferWithAuthorization structure
        auth = data.get("authorization") or data
        if "from" in auth:
            val_raw = int(auth.get("value", 1000))
            return {"payer": auth["from"].lower(), "amount": val_raw / 1e6}
        if "payer" in data:
            return {"payer": data["payer"].lower(), "amount": float(data.get("amount", 0.001))}
    except Exception:
        pass
    return {"payer": "unknown_signer", "amount": 0.001}

def record_delivery(
    endpoint: str,
    method: str,
    status_code: int,
    latency_ms: float,
    user_agent: str,
    client_ip: str,
    referer: str,
    request_input: Any,
    raw_payment_header: str = None,
    payment_response_header: str = None,
    response_preview: str = ""
):
    # Ignore internal health pings
    if endpoint in ["/health", "/ping", "/favicon.ico"]:
        return

    payer_info = decode_payer_from_header(raw_payment_header)
    resolved_payer = payer_info["payer"]
    resolved_amount = payer_info["amount"] if status_code == 200 else 0.0

    if payment_response_header:
        try:
            import base64
            cleaned_resp = payment_response_header.strip()
            if not cleaned_resp.startswith("{"):
                cleaned_resp = base64.b64decode(cleaned_resp).decode("utf-8")
            data_resp = json.loads(cleaned_resp)
            if "payer" in data_resp:
                resolved_payer = data_resp["payer"].lower()
            if "amount" in data_resp:
                resolved_amount = float(data_resp["amount"]) / 1e6
        except Exception:
            pass

    record = {
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "payer_wallet": resolved_payer,
        "amount_usdc": resolved_amount,
        "endpoint": endpoint,
        "method": method,
        "user_agent": user_agent or "none",
        "client_ip": client_ip or "unknown",
        "referer": referer or "direct",
        "request_input": request_input,
        "http_status": status_code,
        "latency_ms": round(latency_ms, 2),
        "response_preview": (response_preview or "")[:300]
    }

    _MEMORY_STORE.insert(0, record)
    if len(_MEMORY_STORE) > MAX_MEMORY_RECORDS:
        _MEMORY_STORE.pop()

    try:
        with open(_LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass

def get_recent_deliveries() -> List[Dict[str, Any]]:
    return list(_MEMORY_STORE)
