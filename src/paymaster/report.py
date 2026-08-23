"""CFO view: where did the agents' spend go. Text, dense, no dashboard."""
from __future__ import annotations
from collections import defaultdict

from .pricing import price


def rollup(records: list, pricing_table: dict, days: int | None = None):
    from datetime import datetime, timedelta, timezone
    cutoff = None
    if days:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    agg = defaultdict(lambda: {"calls": 0, "tin": 0, "tout": 0, "usd": 0.0,
                               "usd_known": True, "fail": 0})
    for r in records:
        if cutoff and r["ts"] < cutoff:
            continue
        a = agg[(r["rail"], r["provider"])]
        a["calls"] += r["calls"]
        a["tin"] += r["tokens_in"]
        a["tout"] += r["tokens_out"]
        a["fail"] += 0 if r["ok"] else 1
        usd = price(r, pricing_table)
        if usd is None:
            a["usd_known"] = False
        else:
            a["usd"] += usd
    return dict(agg)


def render(agg: dict, title: str) -> str:
    lines = [title,
             f"{'rail':<12}{'provider':<34}{'calls':>7}{'tok_in':>12}{'tok_out':>10}{'fail':>6}{'usd':>10}"]
    tot_usd, all_known = 0.0, True
    for (rail, prov), a in sorted(agg.items(), key=lambda kv: -kv[1]["calls"]):
        usd = f"{a['usd']:.4f}" if a["usd_known"] else "?"
        if a["usd_known"]:
            tot_usd += a["usd"]
        else:
            all_known = False
        lines.append(f"{rail:<12}{prov[:33]:<34}{a['calls']:>7}{a['tin']:>12}"
                     f"{a['tout']:>10}{a['fail']:>6}{usd:>10}")
    lines.append(f"{'TOTAL usd':<69}{('%.4f' % tot_usd) if all_known else ('>=%.4f (some unpriced)' % tot_usd):>21}")
    return "\n".join(lines)
