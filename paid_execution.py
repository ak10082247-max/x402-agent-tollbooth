"""Request-bound, recoverable paid fulfillment using an atomic SQLite journal."""
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from contextlib import contextmanager


def db_path():
    return os.environ.get("PAYMENTS_DB_PATH", str(Path(__file__).with_name("payments.db")))


@contextmanager
def connect():
    conn = sqlite3.connect(db_path(), timeout=10, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""CREATE TABLE IF NOT EXISTS paid_fulfillments (
        authorization_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
        tool TEXT NOT NULL, state TEXT NOT NULL, response_json TEXT,
        receipt_json TEXT, updated_at REAL NOT NULL)""")
    try:
        yield conn
    finally:
        conn.close()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def claim(authorization_id, tool, args):
    bound = digest({"tool": tool, "arguments": args})
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        found = conn.execute("SELECT request_hash,state,response_json,receipt_json FROM paid_fulfillments WHERE authorization_id=?", (authorization_id,)).fetchone()
        if found:
            conn.commit()
            if found[0] != bound:
                return {"state": "conflict"}
            return {"state": found[1], "response": json.loads(found[2]) if found[2] else None, "receipt": json.loads(found[3]) if found[3] else None}
        conn.execute("INSERT INTO paid_fulfillments VALUES(?,?,?,'preparing',NULL,NULL,?)", (authorization_id, bound, tool, time.time()))
        conn.commit()
    return {"state": "claimed"}


def release_unpaid(authorization_id):
    # Preparation failure occurs before a facilitator call; this claim is safe to retry.
    with connect() as conn:
        conn.execute("DELETE FROM paid_fulfillments WHERE authorization_id=? AND state='preparing'", (authorization_id,))


def prepare(authorization_id, response):
    with connect() as conn:
        changed = conn.execute("UPDATE paid_fulfillments SET state='settling',response_json=?,updated_at=? WHERE authorization_id=? AND state='preparing'", (json.dumps(response, allow_nan=False), time.time(), authorization_id)).rowcount
        if changed != 1:
            raise RuntimeError("Authorization preparation state changed")


def finish(authorization_id, state, receipt=None):
    if state not in ("delivered", "rejected", "settlement_unknown"):
        raise ValueError("Invalid fulfillment state")
    with connect() as conn:
        changed = conn.execute("UPDATE paid_fulfillments SET state=?,receipt_json=?,updated_at=? WHERE authorization_id=? AND state='settling'", (state, json.dumps(receipt) if receipt else None, time.time(), authorization_id)).rowcount
        if changed != 1:
            raise RuntimeError("Authorization settlement state changed")
