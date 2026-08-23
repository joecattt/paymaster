"""Budgets are the purchase orders of v1: a scope, a window, limits.

A record is IN a budget's scope if every scope key it sets matches.
Findings: BREACH (over a limit), ORPHAN (spend matching no budget at all).
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT = os.path.join(os.path.dirname(__file__), "..", "..", "config", "budgets.json")
WINDOWS = ("day", "month", "total")


def load(path: str = DEFAULT) -> list:
    with open(path) as f:
        budgets = json.load(f)["budgets"]
    for b in budgets:
        if b["window"] not in WINDOWS:
            raise ValueError(f"budget {b['id']}: bad window {b['window']}")
    return budgets


def load_tz(path: str = DEFAULT) -> str:
    """The operator's accounting timezone — a budget system that disagrees
    with its operator about what 'today' means is performance art."""
    with open(path) as f:
        return json.load(f).get("timezone", "UTC")


def _in_scope(rec: dict, scope: dict) -> bool:
    return all(rec.get(k) == v for k, v in scope.items())


def _win_key(ts: str, window: str, tz: str = "UTC") -> str:
    if window == "total":
        return "total"
    zone = timezone.utc if tz == "UTC" else ZoneInfo(tz)
    d = datetime.fromisoformat(ts).astimezone(zone)
    return d.strftime("%Y-%m") if window == "month" else d.strftime("%Y-%m-%d")


def evaluate(records: list, budgets: list, pricing_table: dict, now=None,
             tz: str = "UTC"):
    """Return (findings, usage). Breaches fire for EVERY window that holds
    records, not just the current one — late-arriving spend must not slip a
    day budget just because it was ingested after midnight (Ox review #1,
    2026-08-22). A past breach is still a finding until the config changes."""
    from .pricing import price
    usage, findings = {}, []
    for rec in records:
        matched = False
        for b in budgets:
            if not _in_scope(rec, b.get("scope", {})):
                continue
            matched = True
            key = (b["id"], _win_key(rec["ts"], b["window"], tz))
            u = usage.setdefault(key, {"tokens": 0, "usd": 0.0, "calls": 0,
                                       "usd_known": True})
            u["tokens"] += rec["tokens_in"] + rec["tokens_out"]
            u["calls"] += rec["calls"]
            usd = price(rec, pricing_table)
            if usd is None:
                u["usd_known"] = False
            else:
                u["usd"] += usd
        if not matched:
            findings.append({"kind": "ORPHAN", "record": rec["id"],
                             "detail": f"{rec['provider']}/{rec['principal']} matches no budget",
                             "evidence": rec["evidence"]})
    by_budget = {b["id"]: b for b in budgets}
    for (bid, wkey), u in sorted(usage.items()):
        b = by_budget[bid]
        for limit_key, used_key in (("limit_tokens", "tokens"),
                                    ("limit_usd", "usd"),
                                    ("limit_calls", "calls")):
            lim = b.get(limit_key)
            if lim is None:
                continue
            if limit_key == "limit_usd" and not u["usd_known"]:
                findings.append({"kind": "UNPRICEABLE", "budget": bid,
                                 "detail": f"usd limit set but unpriced records in {b['window']} {wkey} — gate cannot certify"})
                continue
            if u[used_key] > lim:
                findings.append({"kind": "BREACH", "budget": bid,
                                 "detail": f"{used_key}={u[used_key]:.4g} > {limit_key}={lim} in {b['window']} {wkey}"})
    return findings, usage
