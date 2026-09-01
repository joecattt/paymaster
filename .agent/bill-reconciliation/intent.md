# intent — reconcile a metered upstream bill against the provider's usage record

Status: DRAFT, awaiting the operator's approval. Not started.
Originated: 2026-09-01, from a named external review (see Provenance).

## What is wanted

Today paymaster reconciles two sources: the ledger's own per-transaction record
against the provider's per-transaction record (`reconcile_external.py`), plus a
coarse completeness check of Σ(known) against the provider's account-wide
aggregate (`coverage.assess`).

A third source exists in every real deployment and paymaster ignores it: **the
bill**. The invoice a provider actually charges is not the same artifact as the
usage figures their API reports, and they can disagree — through tiering,
committed-use discounts, credits, rounding at the line level, taxes, or a plain
billing error. Nobody currently checks.

Wanted: given a provider's metered bill for a period, produce a verdict on
whether that bill agrees with the provider's own usage record for the same
period, and where it doesn't, by how much and against which line.

## Why

The request is external and specific, from an operator running a pay-per-call
marketplace who reviewed this repo:

> if you take it further I would read a version that reconciles a metered
> upstream bill against a provider's own usage record. That is the case I
> actually have and cannot currently close.

They also declined to integrate, plainly and for reasons that have nothing to do
with this feature (small team, will not put a research tool in a settlement
path). So this is **not** built to close that deal, and shipping it should not be
read as a reason to re-approach them. It is built because it is the first
externally-reported gap this project has received from someone with the problem
in production, and because it completes the source triangle the receipt model
already implies: local estimate ↔ provider usage record ↔ provider bill. Two of
three legs exist.

It is also the honest next step after ANSWERS.md conceded that a self-witnessed
git anchor is not third-party proof: a bill is an adversarial document in the
useful sense — the provider authors it against their own interest to overstate,
and it is the artifact a finance function will actually be handed in a dispute.

## Constraints

- **UNKNOWN stays first-class.** A bill that cannot be parsed, or a period the
  usage record does not cover, produces `UNKNOWN`, never an inferred agreement.
  Fiction 5 applies directly: silence is not $0.
- **Fictions 8 and 9 apply hard here.** A bill line that is bounded (a capped
  tier, a truncated export, a paginated CSV) must never present as a
  measurement, and any disagreement between bill and usage must NOT be resolved
  by picking one — no max(), no "conservative" default. Disagreement is a
  reported verdict, not an input to be tie-broken.
- Reconciliation is post-hoc and periodic by nature. It must not be wired into
  any real-time path.
- No new network dependency in the default path: the bill is a file the operator
  supplies. Do not build provider-specific billing-API scrapers as step one.
- Every claim added to a doc gets a `CLAIMS.json` row with a probe, per the
  repo's existing discipline.

## Explicitly out of scope

- Disputing, filing, or acting on a discrepancy. This reports; it does not
  enforce — the same line the rest of the project holds.
- Multi-provider bill normalization. One provider format, proven end to end,
  beats a generic parser that works on none.
- Currency conversion and tax treatment. Report them as unreconciled components
  rather than pretending to model them.

## Open questions for the operator

1. Which provider's bill first? OpenRouter is where the existing reconciliation
   evidence lives, but its billing artifact is thin — a richer bill (AWS-style,
   or an invoice with line items) exercises the actual problem better.
2. Is the input a file the operator drops in, or an API pull? File-first is the
   constraint above, but confirm that matches the real workflow.
3. What is "done"? Proposed: one real bill, reconciled against one real usage
   period, producing a verdict that correctly reports a *known* discrepancy
   planted by hand — plus a passing verdict on a period with none.

## Next stage

`spec.md` — interfaces, verdict vocabulary, and what a bill-level `UNKNOWN`
means as distinct from a transaction-level one. Do not start it until questions
1 and 3 have answers; guessing them is how scope inflates.

## Provenance

External review received 2026-08-31 by email from an operator of a pay-per-call
tool marketplace, quoted with permission pending. The same review supplied
fictions 8 and 9 in RECEIPT-SPEC.md §8 and the end-to-end example that now opens
the README. Their identifying details are deliberately absent from the public
files until they confirm attribution is welcome.
