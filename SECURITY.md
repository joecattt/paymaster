# Security

## What this is
A **reference implementation** for verifiable agent-spend receipts and
cross-provider reconciliation. It is research-grade evidence infrastructure,
not a production financial-control system, and its documentation is required
(RECEIPT-SPEC.md §6) to refuse claims its evidence cannot support.

## Scope
In scope: the ledger chain, principal stamps, policy gate, reconciliation,
coverage oracle, adapters, and any way to make the receipt claim more than its
evidence establishes — **overclaim bugs are security bugs here.**
Out of scope: spend by credentials that never pass a governed route (disclosed
bypass, by design); provider-side correctness of their own records.

## Known limitations (normative, not a to-do list)
- Agents holding raw provider credentials bypass this system entirely.
- Completeness is provable only in aggregate where providers expose no
  per-transaction enumeration; "all transactions accounted for" is never claimed.
- The git anchor proves repository continuity, not external witness.
- Provider-reported cost is authoritative for the reported charge *at the time
  observed* and may be corrected later; "reconciled" is not "economically final."
- The gate is shadow-mode: it observes and reports; it does not block.

## Safe by default
The test suite is offline and free. No command in this repository makes a paid
network request without an explicit `--confirm-spend` flag; live read-only
provider queries are confined to explicitly named commands (`coverage`,
`prove-nonzero`). This is an invariant, not a convention — a change that
violates it is a vulnerability.

## Reporting
Open a security advisory or issue. Reports that demonstrate the system claiming
more than its evidence supports are treated with the same severity as
traditional vulnerabilities.
