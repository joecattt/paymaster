# paymaster — reference implementation for verifiable agent-spend receipts

**This is a reference implementation, not a complete financial control system.**

When software spends money on its own, someone must be able to prove afterward
what it was allowed to do, what it did, and what it actually cost — across
vendors, without trusting any single party's word. This repo is a working,
tested implementation of that evidence chain:

authenticated principal → policy-hashed decision → provider transaction →
external cost reconciliation → tamper-evident receipt — **with UNKNOWN as a
first-class state** whenever external reality hasn't answered yet.

The centerpiece demo is a receipt that **admits its own limit in the same
breath as its proof**: the known transaction reconciles to the millionth of a
cent (`reconcile: MATCH`) while the coverage field reports real spend outside
the governed route (`coverage: UNACCOUNTED, gap: $0.1996`). "The transaction we
know about reconciles" and "the account is fully covered" are different claims,
and the receipt refuses to blur them. When a provider response is lost, the
verdict is UNKNOWN — never an inferred $0.

## The seven fictions
The intellectual core — each one a mistake this implementation almost made and
caught by experiment: would-DENY ≠ prevented loss · integrity ≠ completeness ·
declaration ≠ legitimacy · fail-closed ≠ safety · local record ≠ external truth ·
known-set reconciliation ≠ coverage · model consensus ≠ market evidence.

## What it is NOT
- It does not move money, hold keys, or execute payments.
- It does not block anything (the gate is shadow-mode by design).
- **Agents holding raw provider credentials bypass it entirely.** It governs
  the routes you send through it, and says so.
- It cannot prove "all transactions accounted for" — only that the known set
  reconciles and whether aggregate drift shows unaccounted spend exists.

## Scope, painfully clear
This implementation demonstrates authorization, reconciliation, evidence
linkage, coverage-gap detection, and uncertainty handling. It does **not**
establish complete transaction coverage, does **not** control unmanaged
provider credentials, and does **not** claim production financial-control
completeness. Its git anchor proves repository continuity, not external
witness. See RECEIPT-SPEC.md for the full negative specification.

**Safe by default:** the test suite is offline and free. No command makes a
paid request without an explicit `--confirm-spend` flag.

MIT. Built by an independent researcher; adversarial review welcome — the spec
is looking for people who can break it.
