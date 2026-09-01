# Verifiable Agent-Spend Receipts — draft specification v0.1

A compact, machine-verifiable record binding an autonomous actor to an authorized
action and to the external evidence of its economic outcome — with uncertainty
preserved as a first-class state.

**Status: DRAFT.** Extracted from a working reference implementation that has
reconciled real provider charges. Not a standard; a proposal seeking adversaries.

## 1. The problem

Software has started spending money on its own. Today no artifact proves — across
vendors, without trusting any single party's word — what an agent was allowed to
do, what it actually did, and what it truly cost. Provider logs attest only to
that provider. Gateway logs are the operator's self-report. Invoices arrive late
and aggregated. The receipt is the missing binding.

## 2. The receipt

Every field carries not just a value but its **source authority** — who
establishes this fact — because the fields are NOT equally trustworthy:

| field | meaning | source authority |
|---|---|---|
| `principal_id` | the acting identity | operator (see `attribution`) |
| `attribution` | `asserted` \| `authenticated` \| `signed` | how strongly the record binds to the actor |
| `policy_hash` | exact policy version governing the decision | operator, reproducible |
| `decision` + `reason_code` | ALLOW / DENY / HOLD, machine-readable why | policy engine |
| `intent` | what the actor declared it was doing | **actor — evidence, never truth** |
| `provider_txn` | provider-side transaction identity | provider |
| `local_estimate` | cost computed independently (published price × usage) | operator |
| `provider_reported_cost` | what the provider's own record says it charged | **provider — authoritative for the reported charge at the time observed; subject to later correction/adjustment** |
| `reconcile` | MATCH / MISMATCH / UNKNOWN / UNSETTLED | derived, reproducible |
| `spent_known` | boolean honesty flag | derived — false means DO NOT claim the money's fate |
| `coverage` | COVERED / UNACCOUNTED(gap) / NO_AGGREGATE | derived from provider aggregate |
| `ledger_seq`, `chain_hash` | tamper-evidence of the operator's record | operator |
| `anchor` | continuity witness — see anchor taxonomy below | varies (§3a) |
| `receipt_version`, `schema_version` | interpretation stability over time | spec |
| `authority.capability` | a VERIFIED delegation chain the actor presented | issuer keys — grade `authenticated`, never higher |
| *(attestation slot)* | reserved: hardware/TEE runtime-identity proof | **empty today — always listed as a gap, never simulated** |

### 3a. Anchor taxonomy (do not conflate)

| kind | what it actually proves |
|---|---|
| **repository anchor** (e.g. a git commit) | continuity against a repository state the operator controls — NOT external immutability |
| **external timestamp/anchor** (third-party timestamping, transparency log) | the record existed by time T, witnessed outside the operator's control |
| **provider evidence** | the provider's own assertion about its side of the transaction |
| **independent attestation** | a third party verified a specific claim |

The reference implementation currently provides only the first. Claiming more
would violate §6.8.

## 3. The evidence ladder

`asserted < authenticated < signed < independently witnessed < third-party verified`

A claim inherits the grade of its **weakest** supporting field. No surface may
render a stronger word than the grade earns.

## 4. The claim lattice

A conforming implementation may only move a claim upward with the evidence that
level requires:

`observed < attributed < authorized < executed < consumed < settled < complete`

- authorization is not execution
- execution is not consumption
- a provider response is not settlement
- settlement-at-time-T is not economic finality (refunds/corrections exist)
- reconciliation of the known set is not completeness

## 5. States

Decisions: `ALLOW · DENY · HOLD · UNKNOWN`
Reconciliation: `MATCH · MISMATCH · UNKNOWN · UNSETTLED · DISPUTED`
Coverage: `COVERED · UNACCOUNTED · NO_AGGREGATE`

`UNKNOWN` is a **valid terminal output**, not a pending error. External economic
truth is asynchronous (measured provider accounting lag: 8–30s+); during the
window, UNKNOWN is the only honest verdict. Absence of evidence is never $0.

## 6. The negative specification (normative)

A conforming implementation **MUST NOT**:

1. represent would-DENY counts as prevented loss
2. represent chain integrity as record completeness
3. represent declared intent as legitimate intent
4. represent fail-closed behavior as operational safety under load
5. represent its local record as external economic truth
6. represent known-set reconciliation as full coverage
7. represent a provider response as final settlement
8. represent tamper-evidence or a repository anchor as evidentiary independence or external witness
9. resolve a missing external record to zero cost
10. permit an actor to increase its own authority, extend its own expiration,
    or release its own quarantine

## 6b. Capability invariants (normative for the delegation chain)

- I-CAP1 authority can shrink automatically; it can never grow implicitly —
  a child capability is min()'d/narrowed against its parent on every dimension
- I-CAP2 a subject cannot extend its own expiry, raise its own bounds, or mint
  itself authority it does not hold (self-delegation only narrows)
- I-CAP3 revocation cascades: revoking a capability invalidates everything
  delegated under it
- I-CAP4 delegation requires parental permission and has bounded depth
- I-CAP5 chain verification grades at most `authenticated` (local HMAC keys) —
  runtime identity remains unproven until hardware/TEE attestation fills the slot

## 7. Known limits (also normative to disclose)

- Actions using credentials outside a governed route are **not covered**; an
  implementation must state which routes it governs.
- Where providers expose no per-transaction enumeration, completeness is
  provable only in aggregate (Σ known vs provider total bounds the unknown).
- The receipt's evidentiary value is derivative of the provider record; the
  implementation is the binding and the gap-detection, not the witness.

## 8. The fictions (why this spec exists)

Each clause of §6 was a mistake the reference implementation almost made and
caught by experiment, not by taste. 8 and 9 are not ours — they were paid for by
an operator of a pay-per-call tool marketplace who reviewed this spec in August
2026 and described two live losses of exactly this shape. They are recorded here
because the failure mode generalizes, not because it happened to us:

1. would-DENY ≠ prevented loss (82% of a real would-DENY set was legitimate batch work)
2. integrity ≠ completeness (tail truncation passed chain verification)
3. declaration ≠ legitimacy (a within-envelope mimic passed declared-intent checks)
4. fail-closed ≠ operational safety (rebuild cost turns the control into a denial-of-service)
5. local record ≠ external truth (settlement arrived 8–30s late; silence is not $0)
6. known-set reconciliation ≠ full coverage (no enumeration APIs exist; only aggregates bound the unknown)
7. model consensus ≠ market evidence (the project's own panels are hypotheses, not buyers — this spec obeys its own rule)
8. a capped result ≠ a measurement (a published "tools used in 30 days" figure
   was the length of a LIMIT-20 query — it could never exceed 20, was read as an
   inventory count, and live inventory was retired on it; the true number was 281)
9. the conservative-looking tie-break ≠ the safe one (a price disagreement
   resolved by taking the higher of two values is a one-way ratchet: a seller cut
   their price tenfold and the stale figure was quoted for nine days, until the
   seller emailed to say so)

8 and 9 are the same failure as 5 and 6 seen from the other side. In 5 and 6 a
missing measurement risks being read as zero; in 8 and 9 a *bounded or
arbitrated* measurement is read as a real one. Both are a number that cannot
mean what it is being asked to mean, presenting without a caveat. The rule that
covers all four: **a field must carry how it was obtained, not only its value**
— which is why every cost in this spec is graded (`reconciled` /
`estimated` / `asserted` / `UNKNOWN`) and why the receipt takes the grade of its
weakest populated field.

## 9. Reference implementation

This repository. 97 tests; chain proven on real (small) money; every limitation
above discovered by running it, not by theorizing.
