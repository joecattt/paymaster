"""External-truth reconciliation (audit finding: ledger record != external economic truth).

The ledger is INTERNAL accounting truth. It is not proof the provider charged us.
This reconciles three independent facts about one economic action:

    LOCAL_RECORDED   what paymaster wrote down
    PROVIDER_REPORTED what the provider's own API says it charged
    SETTLED          what actually left an account (credits/bank delta)

and returns a verdict that is allowed to say UNKNOWN. It never infers "no spend"
from missing evidence — the lost-response case is the whole reason this exists.
"""
from __future__ import annotations

# verdicts
MATCH = "MATCH"                       # local == provider (== settled if present)
MISMATCH = "MISMATCH"                 # local and provider disagree on amount
UNKNOWN_PROVIDER = "UNKNOWN_PROVIDER" # we acted but have no provider record — MAY have been charged
UNSETTLED = "UNSETTLED"              # provider reported a charge; no settlement evidence yet
NO_ACTION = "NO_ACTION"              # nothing recorded anywhere


def reconcile(local_cost, provider_cost, settled_cost=None, *,
              authorized: bool, response_received: bool, tol=1e-9) -> dict:
    """Return {verdict, spent_known, amount, note}. `spent_known` is the
    honesty flag: False means the system must NOT claim to know money's fate."""
    def d(v, spent_known, amount, note):
        return {"verdict": v, "spent_known": spent_known, "amount": amount, "note": note}

    if not authorized and local_cost is None and provider_cost is None:
        return d(NO_ACTION, True, 0.0, "nothing authorized, nothing recorded")

    # We authorized and dispatched, but never saw the response: the dangerous case.
    if authorized and not response_received and provider_cost is None:
        return d(UNKNOWN_PROVIDER, False, None,
                 "authorized+dispatched, response lost, no provider record — "
                 "provider MAY have executed and charged. Cannot conclude no-spend.")

    if provider_cost is None:
        # have a local record but no external confirmation
        return d(UNKNOWN_PROVIDER, False, local_cost,
                 "local record exists but provider has not confirmed — unverified")

    if local_cost is not None and abs(local_cost - provider_cost) > tol:
        return d(MISMATCH, True, provider_cost,
                 f"local {local_cost} != provider {provider_cost}; provider is authoritative for charge")

    # local agrees with provider (or no local, provider-only)
    if settled_cost is None:
        return d(UNSETTLED, False, provider_cost,
                 "provider reported charge; settlement (account delta) not yet evidenced")
    if abs(settled_cost - provider_cost) > tol:
        return d(MISMATCH, True, settled_cost,
                 f"provider {provider_cost} != settled {settled_cost}")
    return d(MATCH, True, provider_cost, "local == provider == settled")
