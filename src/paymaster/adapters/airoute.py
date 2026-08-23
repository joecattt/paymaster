"""Adapter: ai-route telemetry (routing.db events table) -> SpendRecords.

Reads the EXISTING ledger of every delegate/ai-route call on this machine —
no parallel tracker, no double-entry. Cursor on sqlite rowid makes ingestion
idempotent.
"""
from __future__ import annotations
import os
import sqlite3

from ..schema import record, make_id

DB = os.path.expanduser("~/.local/state/ai-route/routing.db")


def fetch(since_rowid: int = 0, db_path: str = DB):
    """Yield (rowid, SpendRecord) for events after the cursor."""
    if not os.path.exists(db_path):
        return
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cur = con.execute(
            "SELECT rowid, ts, caller, task_class, provider, model, ok,"
            " tokens_in, tokens_out FROM events WHERE rowid > ? ORDER BY rowid",
            (since_rowid,))
        for (rowid, ts, caller, task_class, provider, model, ok,
             t_in, t_out) in cur:
            yield rowid, record(
                ts=ts,
                rail="api-billing",
                provider=provider or "unknown",
                principal=caller or "unattributed",
                # caller is self-reported telemetry — the weakest identity
                # tier, and the record says so rather than hiding it.
                attribution="asserted",
                # DELIVERED, not VERIFIED: the provider asserted completion;
                # nothing independent has checked the work.
                state="DELIVERED" if ok else "FAILED",
                task_class=task_class or "",
                model=model or "",
                tokens_in=t_in or 0,
                tokens_out=t_out or 0,
                usd=None,  # priced later by pricing.py, never here
                evidence=f"routing.db#rowid={rowid}",
                rid=make_id("airoute", rowid, ts, provider),
            )
    finally:
        con.close()
