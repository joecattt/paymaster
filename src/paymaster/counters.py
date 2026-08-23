"""Compacted per-window counter store — the FAST derived index (v5).

THE ONE INVARIANT THIS FILE EXISTS TO UPHOLD:
    ledger is authoritative; counters are a cache.
A decision computed from counters MUST equal the decision computed from a full
ledger walk, or the cache is wrong and loses — automatically, on every reconcile.

Mechanism: persist the Snapshot usage dict plus the ledger checkpoint it was
built at (seq + tail hash + policy hash). On load, apply only the ledger delta
since the checkpoint (cheap). A policy change invalidates the derived state and
forces a full rebuild — a stale counter under a new policy would be fiction.
"""
from __future__ import annotations
import json
import os

from . import budgets as B
from .gate import Snapshot, policy_hash
from .ledger import Ledger

STORE = os.path.expanduser("~/.local/state/paymaster/counters.json")
LEDGER = os.path.expanduser("~/.local/state/paymaster/spend.jsonl")


def _key(bid, wkey):        # dict keys must be strings on disk
    return f"{bid}\x1f{wkey}"


def _unkey(k):
    bid, wkey = k.split("\x1f", 1)
    return bid, wkey


def build_snapshot(budgets, tz, records) -> Snapshot:
    return Snapshot(budgets, tz).build(records)


def rebuild(budgets, tz, ledger_path=LEDGER) -> Snapshot:
    """Authoritative path: full ledger walk. Slow, always correct."""
    return build_snapshot(budgets, tz, Ledger(ledger_path).records())


def load_fast(budgets, tz, ledger_path=LEDGER, store_path=STORE) -> tuple[Snapshot, str]:
    """Fast path: load cached counters, apply the ledger delta, return a
    Snapshot equivalent to a full rebuild. Returns (snapshot, provenance)
    where provenance ∈ {cold-rebuild, policy-changed-rebuild, delta, cache-hit}.
    Any inconsistency falls back to a full rebuild — never to stale fiction."""
    led = Ledger(ledger_path)
    tail_seq, tail_hash = led._tail()
    phash = policy_hash(budgets)
    snap = Snapshot(budgets, tz)

    cache = None
    if os.path.exists(store_path):
        try:
            with open(store_path) as f:
                cache = json.load(f)
        except (OSError, ValueError):
            cache = None

    if cache is None or cache.get("policy_hash") != phash or cache.get("tz") != tz:
        # no cache, or policy/tz changed -> derived state invalid -> full rebuild
        snap = rebuild(budgets, tz, ledger_path)
        _persist(snap, tail_seq, tail_hash, tz, store_path)
        return snap, ("cold-rebuild" if cache is None else "policy-changed-rebuild")

    cseq = cache.get("ledger_seq", 0)
    if cseq > tail_seq:
        # ledger shrank under the cache (rewrite/rollback) -> cache invalid
        snap = rebuild(budgets, tz, ledger_path)
        _persist(snap, tail_seq, tail_hash, tz, store_path)
        return snap, "ledger-shrank-rebuild"

    # load cached usage, apply the delta records (seq > cseq) only
    for k, v in cache.get("usage", {}).items():
        bid, wkey = _unkey(k)
        snap.usage[(bid, wkey)] = dict(v)
    if cseq == tail_seq:
        return snap, "cache-hit"
    # apply delta
    delta = _records_after(ledger_path, cseq)
    for rec in delta:
        for b in budgets:
            if all(rec.get(kk) == vv for kk, vv in b.get("scope", {}).items()):
                wk = B._win_key(rec["ts"], b["window"], tz)
                u = snap.usage.setdefault((b["id"], wk), {"tokens": 0, "calls": 0})
                u["tokens"] += rec["tokens_in"] + rec["tokens_out"]
                u["calls"] += rec["calls"]
    _persist(snap, tail_seq, tail_hash, tz, store_path)
    return snap, "delta"


def _records_after(ledger_path, seq):
    out = []
    with open(ledger_path) as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            if row["seq"] > seq:
                out.append(row["rec"])
    return out


def _persist(snap, seq, tail_hash, tz, store_path):
    data = {"ledger_seq": seq, "ledger_hash": tail_hash, "tz": tz,
            "policy_hash": snap.phash,
            "usage": {_key(bid, wk): v for (bid, wk), v in snap.usage.items()}}
    os.makedirs(os.path.dirname(store_path), exist_ok=True)
    tmp = store_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, store_path)


def reconcile(budgets, tz, ledger_path=LEDGER, store_path=STORE) -> tuple[bool, str]:
    """Rebuild counters from the authoritative ledger and compare to the cached
    fast path. The cache loses on any mismatch. Run this on a schedule."""
    truth = rebuild(budgets, tz, ledger_path)
    fast, prov = load_fast(budgets, tz, ledger_path, store_path)
    tk = {k: v for k, v in truth.usage.items() if v["tokens"] or v["calls"]}
    fk = {k: v for k, v in fast.usage.items() if v["tokens"] or v["calls"]}
    if tk != fk:
        # cache loses: overwrite with truth
        _persist(truth, *truth_checkpoint(ledger_path), tz, store_path)
        diff = set(tk) ^ set(fk)
        return False, f"counter/ledger MISMATCH on {len(diff)} keys — cache overwritten with ledger truth"
    return True, f"counters == ledger ({len(tk)} live windows, via {prov})"


def truth_checkpoint(ledger_path):
    return Ledger(ledger_path)._tail()
