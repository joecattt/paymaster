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

from .capability import verify_chain

# verdicts
MATCH = "MATCH"                       # local == provider (== settled if present)
MISMATCH = "MISMATCH"                 # local and provider disagree on amount
UNKNOWN_PROVIDER = "UNKNOWN_PROVIDER" # we acted but have no provider record — MAY have been charged
UNSETTLED = "UNSETTLED"              # provider reported a charge; no settlement evidence yet
NO_ACTION = "NO_ACTION"              # nothing recorded anywhere
UNAUTHORIZED_SPEND = "UNAUTHORIZED_SPEND"  # money/dispatch observed, no currently-valid capability chain


def reconcile(local_cost, provider_cost, settled_cost=None, *,
              authorized: bool, response_received: bool, tol=1e-9,
              capability_chain: list | None = None) -> dict:
    """Return {verdict, spent_known, amount, note}. `spent_known` is the
    honesty flag: False means the system must NOT claim to know money's fate.

    Authorization is DERIVED here from `capability_chain` via verify_chain
    (PM-003), never from the caller. `authorized` only says "we dispatched /
    intended to act"; it cannot grant authority. Missing, invalid, revoked or
    expired chain + any observed money or dispatch => UNAUTHORIZED_SPEND.

    LIMITATION (not solved): validity is evaluated against CURRENT state
    (now, current revocation list). It is NOT as-of the time of the act, so a
    spend that was legitimate when made but whose capability was later revoked
    or expired is reported UNAUTHORIZED_SPEND, and the converse is
    unprovable. As-of authority is the absent temporal semantic."""
    def d(v, spent_known, amount, note):
        return {"verdict": v, "spent_known": spent_known, "amount": amount, "note": note}

    if not authorized and local_cost is None and provider_cost is None:
        return d(NO_ACTION, True, 0.0, "nothing authorized, nothing recorded")

    acted = bool(authorized) or local_cost is not None or provider_cost is not None
    if acted:
        try:
            cap = verify_chain(capability_chain) if capability_chain else \
                {"valid": False, "reason": "NO_CAPABILITY_CHAIN"}
        except (TypeError, AttributeError, KeyError):   # malformed chain: fail closed
            cap = {"valid": False, "reason": "MALFORMED_CAPABILITY_CHAIN"}
        if not cap["valid"]:
            amount = provider_cost if provider_cost is not None else local_cost
            return d(UNAUTHORIZED_SPEND, provider_cost is not None, amount,
                     f"money or dispatch observed without a currently-valid capability "
                     f"({cap['reason']}); validity is current-state, not as-of the act")

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
