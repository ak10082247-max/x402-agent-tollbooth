"""Request-bound, recoverable paid fulfillment using an atomic SQLite journal."""
import hashlib
import json
import os
import sqlite3
import time
import secrets
from pathlib import Path
from contextlib import contextmanager


class OperationSuperseded(Exception):
    """This worker no longer owns the right to submit the authorization."""


PREPARATION_LEASE_SECONDS = 120


def db_path():
    return os.environ.get("PAYMENTS_DB_PATH", str(Path(__file__).with_name("payments.db")))


@contextmanager
def connect():
    path = Path(db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""CREATE TABLE IF NOT EXISTS paid_fulfillments (
            authorization_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
            tool TEXT NOT NULL, state TEXT NOT NULL, response_json TEXT,
            receipt_json TEXT, updated_at REAL NOT NULL, owner TEXT)""")
        # Additive migration retains all previously delivered/unknown purchases.
        if "owner" not in {row[1] for row in conn.execute("PRAGMA table_info(paid_fulfillments)")}:
            conn.execute("ALTER TABLE paid_fulfillments ADD COLUMN owner TEXT")
        conn.commit()
        yield conn
    finally:
        conn.close()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def lookup(authorization_id, tool, args):
    """Authenticate retained delivery terms without claiming or reclaiming work."""
    bound = digest({"tool": tool, "arguments": args})
    with connect() as conn:
        found = conn.execute("SELECT request_hash,state,response_json,receipt_json FROM paid_fulfillments WHERE authorization_id=?", (authorization_id,)).fetchone()
    if not found:
        return {"state": "missing"}
    if found[0] != bound:
        return {"state": "conflict"}
    return {"state": found[1], "response": json.loads(found[2]) if found[2] else None, "receipt": json.loads(found[3]) if found[3] else None}


def claim(authorization_id, tool, args):
    bound = digest({"tool": tool, "arguments": args})
    owner, now = secrets.token_hex(16), time.time()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        found = conn.execute("SELECT request_hash,state,response_json,receipt_json,updated_at FROM paid_fulfillments WHERE authorization_id=?", (authorization_id,)).fetchone()
        if found:
            if found[0] != bound:
                conn.commit()
                return {"state": "conflict"}
            if found[1] == "preparing" and found[4] < now - PREPARATION_LEASE_SECONDS:
                # Only unpaid preparation may be reclaimed. Changing owner fences
                # the paused worker out of prepare(), hence out of settlement.
                conn.execute("UPDATE paid_fulfillments SET owner=?,updated_at=? WHERE authorization_id=? AND state='preparing'", (owner, now, authorization_id))
                conn.commit()
                return {"state": "claimed", "owner": owner}
            conn.commit()
            return {"state": found[1], "response": json.loads(found[2]) if found[2] else None, "receipt": json.loads(found[3]) if found[3] else None}
        conn.execute("INSERT INTO paid_fulfillments(authorization_id,request_hash,tool,state,response_json,receipt_json,updated_at,owner) VALUES(?,?,?,'preparing',NULL,NULL,?,?)", (authorization_id, bound, tool, now, owner))
        conn.commit()
    return {"state": "claimed", "owner": owner}


def release_unpaid(authorization_id, owner):
    # Preparation failure occurs before a facilitator call; this claim is safe to retry.
    with connect() as conn:
        conn.execute("DELETE FROM paid_fulfillments WHERE authorization_id=? AND owner=? AND state='preparing'", (authorization_id, owner))


def prepare(authorization_id, response, owner):
    with connect() as conn:
        changed = conn.execute("UPDATE paid_fulfillments SET state='settling',response_json=?,updated_at=? WHERE authorization_id=? AND owner=? AND state='preparing'", (json.dumps(response, allow_nan=False), time.time(), authorization_id, owner)).rowcount
        if changed != 1:
            raise OperationSuperseded("Authorization preparation belongs to another worker")


def finish(authorization_id, state, receipt=None, *, owner):
    if state not in ("delivered", "rejected", "settlement_unknown"):
        raise ValueError("Invalid fulfillment state")
    with connect() as conn:
        changed = conn.execute("UPDATE paid_fulfillments SET state=?,receipt_json=?,updated_at=? WHERE authorization_id=? AND owner=? AND state='settling'", (state, json.dumps(receipt) if receipt else None, time.time(), authorization_id, owner)).rowcount
        if changed != 1:
            raise RuntimeError("Authorization settlement state changed")


def recover_verified_delivery(authorization_id, expected_tool, receipt):
    """Operator-only CAS after independent chain proof; never resubmits a payment.

    The offline reconciliation command validates the original signed authorization,
    canonical USDC transfer and chain evidence before calling this function.
    """
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT tool,state,response_json FROM paid_fulfillments WHERE authorization_id=?", (authorization_id,)).fetchone()
        if not row or row[0] != expected_tool or row[1] not in ("settling", "settlement_unknown") or not row[2]:
            raise ValueError("Operation is not a retained settlement awaiting recovery")
        response = json.loads(row[2])
        if not isinstance(response, dict):
            raise ValueError("Retained result is invalid")
        changed = conn.execute("UPDATE paid_fulfillments SET state='delivered',receipt_json=?,updated_at=? WHERE authorization_id=? AND tool=? AND state=?",
                               (json.dumps(receipt, allow_nan=False), time.time(), authorization_id, expected_tool, row[1])).rowcount
        if changed != 1:
            raise OperationSuperseded("Operation changed during verified recovery")
        conn.commit()


def reserve_provider_cost(metadata):
    """Durably retain the upper estimate even if generation times out or fails.

    These are operating-cost records, never inferred customer revenue or profit.
    A delivered fulfillment can be joined through provider_usage.cost_event_id.
    """
    event_id = secrets.token_hex(16)
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS provider_cost_events (
            event_id TEXT PRIMARY KEY, state TEXT NOT NULL,
            metadata_json TEXT NOT NULL, updated_at REAL NOT NULL)""")
        conn.execute("INSERT INTO provider_cost_events VALUES(?,'reserved_usage_unknown',?,?)", (event_id, json.dumps(metadata, allow_nan=False), time.time()))
    return event_id


def measure_provider_cost(event_id, metadata):
    with connect() as conn:
        changed = conn.execute("UPDATE provider_cost_events SET state='measured_estimate',metadata_json=?,updated_at=? WHERE event_id=? AND state='reserved_usage_unknown'",
                               (json.dumps(metadata, allow_nan=False), time.time(), event_id)).rowcount
        if changed != 1:
            raise ValueError("Provider cost reservation is unavailable")
