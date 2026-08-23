"""Coverage oracle (experiment 3) — the ONLY completeness signal available.

Enumeration of provider-side transactions does not exist (tested: OpenRouter has
lookup-by-id + an aggregate total, no /activity|/generations|/transactions API).
So Paymaster cannot list "all transactions" to prove completeness. What it CAN
do: compare the sum of what it knows against the provider's own aggregate total.
A positive gap proves unaccounted spend EXISTS — not what it was, not when.

This upgrades the honest claim from "the known set reconciles" (correctness) to
"and here is the bound on what we cannot see" (coverage). Two different words;
never let correctness imply coverage.
"""
from __future__ import annotations

COVERED = "COVERED"                 # known sum == provider aggregate (within tol)
UNACCOUNTED = "UNACCOUNTED"         # provider total exceeds what we recorded -> bypass/unknown spend
OVERCOUNTED = "OVERCOUNTED"         # we recorded MORE than the provider says -> our error / double-count
NO_AGGREGATE = "NO_AGGREGATE"       # provider exposes no total -> coverage unprovable, say so


def assess(known_sum, provider_aggregate, *, tol=1e-6) -> dict:
    """Compare Σ(known cost) to the provider's aggregate. Returns a verdict that
    is allowed to say coverage is unprovable rather than implying full coverage."""
    if provider_aggregate is None:
        return {"verdict": NO_AGGREGATE, "coverage_known": False, "gap": None,
                "note": "provider exposes no aggregate total; coverage cannot be established"}
    gap = round(provider_aggregate - known_sum, 10)
    if abs(gap) <= tol:
        return {"verdict": COVERED, "coverage_known": True, "gap": 0.0,
                "note": "known set sums to the provider aggregate; no unaccounted spend detected"}
    if gap > 0:
        return {"verdict": UNACCOUNTED, "coverage_known": True, "gap": gap,
                "note": f"provider aggregate exceeds known sum by {gap} — unaccounted spend EXISTS "
                        "(bypass or pre-ledger); amount known, per-transaction identity NOT"}
    return {"verdict": OVERCOUNTED, "coverage_known": True, "gap": gap,
            "note": f"known sum exceeds provider aggregate by {-gap} — local over-count/double-record"}


# Honest limits of THIS oracle against a real provider aggregate:
GRANULARITY_CAVEATS = (
    "OpenRouter /credits total_usage is account-wide and all-time: it detects "
    "cumulative unaccounted spend, NOT per-key, per-window, or per-agent. It is a "
    "coarse smoke alarm, not a per-transaction proof. A per-key/per-day aggregate "
    "would be needed to localize a bypass in time or to an agent."
)


def assess_per_key(known_by_key: dict, aggregate_by_key: dict, *, tol=1e-6) -> dict:
    """Per-principal coverage: reconcile Σ(known) against a per-key aggregate
    (e.g. LiteLLM's own per-key spend totals, or per-agent provider sub-accounts).
    This is the per-AGENT localization the account-wide oracle cannot do — it
    names WHICH principal has unaccounted spend, not just that some exists.
    Returns {key: assess(...)} plus a roll-up."""
    out = {}
    for key in set(known_by_key) | set(aggregate_by_key):
        out[key] = assess(known_by_key.get(key, 0.0),
                          aggregate_by_key.get(key), tol=tol)
    unaccounted = {k: v for k, v in out.items() if v["verdict"] == UNACCOUNTED}
    return {"per_key": out,
            "keys_with_unaccounted_spend": sorted(unaccounted),
            "clean": not unaccounted}
