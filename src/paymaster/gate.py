"""Shadow policy gate (Phase 3) — decide, log, never block (yet).

At the routing choke point: identify principal, load a bounded policy snapshot,
evaluate the proposed action against current-window usage, emit a reproducible
ALLOW/DENY decision to a chained decision log, then let execution continue.
SHADOW mode is the only mode this file implements — enforcement is a separate,
human-signed flip that lives elsewhere.

Correctness of the in-memory snapshot is reconcilable: the decision log records
the policy hash used, and `snapshot` is rebuildable from the full ledger, so
any decision can be replayed against the exact policy that produced it.
"""
from __future__ import annotations
import hashlib
import json
import os
import time
from datetime import datetime, timezone

from . import budgets as B, pricing as P
from .ledger import Ledger
from .schema import make_id

DECISIONS = os.path.expanduser("~/.local/state/paymaster/decisions.jsonl")


def policy_hash(budgets: list) -> str:
    return hashlib.sha256(
        json.dumps(budgets, sort_keys=True).encode()).hexdigest()[:16]


class Snapshot:
    """Bounded in-memory usage state — current-window counters per (budget,
    window-key). Built once from the ledger, then advanced per decision so the
    hot path never re-walks history. Max staleness = age since `built_at`."""

    def __init__(self, budgets, tz="UTC"):
        self.budgets = budgets
        self.tz = tz
        self.phash = policy_hash(budgets)
        self.usage = {}          # (bid, wkey) -> {tokens,calls}
        self.built_at = None

    def build(self, records):
        by = {b["id"]: b for b in self.budgets}
        for rec in records:
            for b in self.budgets:
                if all(rec.get(k) == v for k, v in b.get("scope", {}).items()):
                    wk = B._win_key(rec["ts"], b["window"], self.tz)
                    u = self.usage.setdefault((b["id"], wk), {"tokens": 0, "calls": 0})
                    u["tokens"] += rec["tokens_in"] + rec["tokens_out"]
                    u["calls"] += rec["calls"]
        self.built_at = time.time()
        return self

    def staleness_s(self):
        return None if self.built_at is None else time.time() - self.built_at

    def decide(self, *, principal, provider, tokens=0, calls=1, now=None):
        """Return a decision dict. Pure function of the snapshot + proposal —
        does NOT mutate usage (caller advances it only if the action proceeds)."""
        now = now or datetime.now(timezone.utc)
        ts = now.isoformat(timespec="seconds")
        matched = None
        for b in self.budgets:
            scope = b.get("scope", {})
            hit = True
            for k, v in scope.items():
                actual = principal if k == "principal" else (provider if k == "provider" else None)
                if actual != v:
                    hit = False
                    break
            if hit:
                matched = b
                break
        if matched is None:
            return self._d(principal, provider, "DENY", "ORPHAN_NO_BUDGET", ts, None)
        wk = B._win_key(ts, matched["window"], self.tz)
        u = self.usage.get((matched["id"], wk), {"tokens": 0, "calls": 0})
        proj_calls = u["calls"] + calls
        proj_tokens = u["tokens"] + tokens
        if matched.get("limit_calls") is not None and proj_calls > matched["limit_calls"]:
            return self._d(principal, provider, "DENY", "OVER_CALL_LIMIT", ts, matched["id"],
                           f"{proj_calls}>{matched['limit_calls']}")
        if matched.get("limit_tokens") is not None and proj_tokens > matched["limit_tokens"]:
            return self._d(principal, provider, "DENY", "OVER_TOKEN_LIMIT", ts, matched["id"],
                           f"{proj_tokens}>{matched['limit_tokens']}")
        return self._d(principal, provider, "ALLOW", "WITHIN_BUDGET", ts, matched["id"])

    def advance(self, principal, provider, tokens, calls, ts):
        for b in self.budgets:
            scope = b.get("scope", {})
            actual = {"principal": principal, "provider": provider}
            if all(actual.get(k) == v for k, v in scope.items()):
                wk = B._win_key(ts, b["window"], self.tz)
                u = self.usage.setdefault((b["id"], wk), {"tokens": 0, "calls": 0})
                u["tokens"] += tokens
                u["calls"] += calls

    def _d(self, principal, provider, decision, reason, ts, budget, detail=""):
        return {"decision": decision, "reason_code": reason, "principal_id": principal,
                "provider": provider, "budget": budget, "policy_hash": self.phash,
                "ts": ts, "detail": detail, "mode": "shadow"}


def evaluate(principal, provider, *, tokens=0, calls=1, attribution="asserted",
             now=None, tz=None, budgets=None):
    """Single-decision convenience: load policy, build snapshot, decide, log.
    Fail-closed: any failure to reach a verdict yields DENY/GATE_UNAVAILABLE
    (recorded; in shadow that is data, not a block)."""
    t0 = time.time()
    try:
        budgets = budgets if budgets is not None else B.load()
        tz = tz or B.load_tz()
        from . import counters as _C  # lazy: counters imports gate
        snap, prov = _C.load_fast(budgets, tz)
        d = snap.decide(principal=principal, provider=provider, tokens=tokens,
                        calls=calls, now=now)
        d["snapshot_via"] = prov
        d["snapshot_staleness_s"] = round(snap.staleness_s() or 0, 3)
    except Exception as e:
        d = {"decision": "DENY", "reason_code": "GATE_UNAVAILABLE",
             "principal_id": principal, "provider": provider, "budget": None,
             "policy_hash": None, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "detail": f"{type(e).__name__}: {e}"[:120], "mode": "shadow"}
    d["attribution"] = attribution
    d["decide_ms"] = int((time.time() - t0) * 1000)
    _log(d)
    return d


def _log(d: dict) -> None:
    """Append decision to a chained log — same integrity model as the ledger,
    separate file so decisions and spend don't interleave."""
    try:
        os.makedirs(os.path.dirname(DECISIONS), exist_ok=True)
        prev = "0" * 64
        if os.path.exists(DECISIONS):
            with open(DECISIONS, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                f.seek(max(0, size - 4096))
                tail = f.read().decode("utf-8", "replace").splitlines()
                if tail:
                    prev = json.loads(tail[-1]).get("hash", prev)
        row = dict(d)
        row["prev"] = prev
        row["hash"] = hashlib.sha256(
            (prev + json.dumps(d, sort_keys=True)).encode()).hexdigest()
        with open(DECISIONS, "a") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass  # in shadow, a logging failure must not take down routed work
