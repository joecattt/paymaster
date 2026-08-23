"""Economic integrity invariants — DEFINED now, most enforced later (v5).

Per the counter-review: define the invariant before building the machinery, so
the schema and accounting can never silently violate what will later be law.
Each invariant carries a STATUS:
  ENFORCED  — a property test in the suite fails if it is violated today
  DEFINED   — stated and schema-compatible; enforced when its feature ships
"""

INVARIANTS = [
    # id, statement, status, note
    ("I1", "counter-store decision == full-ledger decision", "ENFORCED",
     "tests/test_counters.py DifferentialEquivalence"),
    ("I2", "ledger is authoritative; counters are cache and lose on mismatch", "ENFORCED",
     "counters.reconcile() overwrites cache with ledger truth"),
    ("I3", "counters are never negative", "ENFORCED", "check_nonneg()"),
    ("I4", "historical attribution never upgrades (asserted stays asserted)", "ENFORCED",
     "adapters set grade at creation; no mutation path exists"),
    ("I5", "a stamp is spendable at most once (nonce)", "ENFORCED",
     "principal.verify replay test"),
    ("I6", "spent <= authorized", "DEFINED",
     "requires reservation semantics — not built; enforcement is off"),
    ("I7", "reserved + consumed <= budget", "DEFINED", "reservation feature"),
    ("I8", "released <= reserved; refund <= settled", "DEFINED", "settlement feature"),
    ("I9", "consumed cannot become unconsumed without an explicit reversal record", "DEFINED",
     "state machine already forbids illegal back-transitions"),
    ("I10", "concurrent decisions must reserve atomically (no budget overshoot)", "DEFINED",
     "TOCTOU proven: check-then-act overshoots; reserve-then-act required BEFORE enforcement"),
]


def check_nonneg(snapshot) -> bool:
    """I3: usage counters must never go negative."""
    return all(v["tokens"] >= 0 and v["calls"] >= 0 for v in snapshot.usage.values())


def enforced():
    return [i for i in INVARIANTS if i[2] == "ENFORCED"]


def defined_not_enforced():
    return [i for i in INVARIANTS if i[2] == "DEFINED"]
