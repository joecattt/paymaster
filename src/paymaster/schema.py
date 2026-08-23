"""Canonical SpendRecord — one normalized row per unit of agent spend.

v3 (2026-08-22, operator counter-review): the record's primitive is a
TRANSACTION STATE, not a success boolean — payment, delivery, verification
and reconciliation are separate economic facts, and `ok: true` was the data
model lying about them. The state machine is defined before any payment rail
is integrated, deliberately.

Identity: `principal` is a DISPLAY LABEL. `principal_id` is the economic
actor, and `attribution` says how strongly the record is bound to it:
  asserted — self-reported metadata (routing telemetry's caller string)
  signed   — cryptographically bound (an x402 authorization signature)
Existing telemetry can never be upgraded retroactively; labeling its weakness
honestly is the point — a corpus must not look more authoritative than its
attribution mechanism is.
"""
from __future__ import annotations
import hashlib
import json

RAILS = ("api-billing", "x402")

STATES = ("INTENT", "AUTHORIZED", "QUOTED", "SUBMITTED", "PAYMENT_PENDING",
          "PAID", "DELIVERING", "DELIVERED", "VERIFIED", "RECONCILED",
          "DISPUTED", "REFUNDED", "FAILED")

# Legal forward transitions. Terminal-ish states can still move (a DELIVERED
# charge can be DISPUTED; a DISPUTE resolves to REFUNDED or back to VERIFIED).
TRANSITIONS = {
    "INTENT": {"AUTHORIZED", "FAILED"},
    "AUTHORIZED": {"QUOTED", "SUBMITTED", "FAILED"},
    "QUOTED": {"SUBMITTED", "FAILED"},
    "SUBMITTED": {"PAYMENT_PENDING", "PAID", "DELIVERING", "FAILED"},
    "PAYMENT_PENDING": {"PAID", "FAILED"},
    "PAID": {"DELIVERING", "DELIVERED", "DISPUTED", "FAILED"},
    "DELIVERING": {"DELIVERED", "FAILED"},
    "DELIVERED": {"VERIFIED", "RECONCILED", "DISPUTED"},
    "VERIFIED": {"RECONCILED", "DISPUTED"},
    "RECONCILED": {"DISPUTED"},
    "DISPUTED": {"REFUNDED", "VERIFIED", "FAILED"},
    "REFUNDED": set(),
    "FAILED": set(),
}

ATTRIBUTIONS = ("asserted", "authenticated", "signed")  # asserted=self-report, authenticated=HMAC stamp, signed=x402 sig

# States that count as live spend for budget purposes: money moved or the
# work was done. FAILED calls still consumed attempts (calls budgets see
# them); REFUNDED money came back.
SPEND_STATES = {"PAID", "DELIVERING", "DELIVERED", "VERIFIED", "RECONCILED",
                "DISPUTED"}

REQUIRED = ("id", "ts", "rail", "provider", "principal", "principal_id",
            "state", "attribution")


def can_transition(a: str, b: str) -> bool:
    return b in TRANSITIONS.get(a, set())


def make_id(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def record(*, ts, rail, provider, principal, state, attribution,
           principal_id=None, task_class="", model="", tokens_in=0,
           tokens_out=0, calls=1, usd=None, currency="USD", evidence="",
           rid=None) -> dict:
    if rail not in RAILS:
        raise ValueError(f"unknown rail: {rail}")
    if state not in STATES:
        raise ValueError(f"unknown state: {state}")
    if attribution not in ATTRIBUTIONS:
        raise ValueError(f"unknown attribution: {attribution}")
    r = {
        "id": rid or make_id(ts, rail, provider, principal, tokens_in,
                             tokens_out, evidence),
        "ts": ts,
        "rail": rail,
        "provider": provider,
        "principal": principal,          # display label
        "principal_id": principal_id or principal,  # the economic actor
        "attribution": attribution,      # how strongly bound to that actor
        "state": state,                  # the economic fact, not a boolean
        "task_class": task_class,
        "model": model,
        "tokens_in": int(tokens_in or 0),
        "tokens_out": int(tokens_out or 0),
        "calls": int(calls),
        "usd": usd,
        "currency": currency,
        "ok": state not in ("FAILED", "DISPUTED"),  # derived convenience only
        "evidence": evidence,
    }
    validate(r)
    return r


def validate(r: dict) -> None:
    for k in REQUIRED:
        if not r.get(k) and r.get(k) != 0:
            raise ValueError(f"SpendRecord missing {k}: {json.dumps(r)[:200]}")
    if r["state"] not in STATES:
        raise ValueError(f"bad state {r['state']}")
    if r["usd"] is not None and r["usd"] < 0:
        raise ValueError("negative usd")
    if r["tokens_in"] < 0 or r["tokens_out"] < 0:
        raise ValueError("negative tokens")
