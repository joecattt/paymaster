"""Adapter: LiteLLM_SpendLogs -> SpendRecords (the gateway integration).

Coded against LiteLLM's real schema.prisma LiteLLM_SpendLogs model (fields
verbatim: request_id, api_key, spend, prompt_tokens, completion_tokens, model,
custom_llm_provider, startTime, agent_id, user, team_id, cache_hit, status).
This lets Paymaster sit BESIDE a customer's existing gateway — the path real
agents actually use — instead of only its author's `delegate`.

Why this matters: LiteLLM computes per-request `spend` and carries `agent_id`,
so per-AGENT attribution is native (the thing a personal OpenRouter account
could not give). Paymaster's added value on top of LiteLLM is the tamper-
evident chain, reconciliation of LiteLLM's computed spend against the upstream
provider's own record, coverage, and UNKNOWN honesty — none of which LiteLLM does.
"""
from __future__ import annotations
from ..schema import record, make_id


def from_spendlog(row: dict) -> dict:
    """Map one LiteLLM_SpendLogs row (as dict, e.g. from the DB or a callback)
    to a canonical SpendRecord. `spend` is LiteLLM's computed cost — provider-
    reported at the gateway; still reconciled upstream, never treated as truth."""
    principal = row.get("agent_id") or row.get("api_key") or row.get("user") or "unattributed"
    provider = row.get("custom_llm_provider") or "unknown"
    ok = (row.get("status") or "success").lower() in ("success", "", "ok")
    return record(
        ts=row["startTime"],
        rail="api-billing",
        provider=provider,
        principal=principal,
        # api_key is a HASHED token, not a signature -> asserted, not authenticated
        attribution="asserted",
        state="DELIVERED" if ok else "FAILED",
        model=row.get("model", ""),
        tokens_in=row.get("prompt_tokens", 0) or 0,
        tokens_out=row.get("completion_tokens", 0) or 0,
        usd=float(row.get("spend", 0.0) or 0.0),
        currency="USD",
        evidence=f"litellm:request_id={row['request_id']}"
                 + (";cache_hit" if str(row.get("cache_hit", "")).lower() in ("true", "1") else ""),
        rid=make_id("litellm", row["request_id"]),
    )


def fetch(rows, seen_ids=None):
    """Yield SpendRecords from an iterable of LiteLLM_SpendLogs rows, skipping
    already-known ids (idempotent ingest)."""
    seen = seen_ids or set()
    for row in rows:
        rec = from_spendlog(row)
        if rec["id"] not in seen:
            yield rec
