# Origin

Created by Joseph Anthony Reyna (JoeCat) in 2026. This repository is the
original reference implementation of **paymaster** — a verifiable
agent-spend receipt: who acted, under what authority, what it cost, and
what the provider's own records confirm, with `UNKNOWN` as a first-class
state rather than an assumed zero.

If you're implementing this model elsewhere, the reference is here first —
this repo's git history, not a fork or a rewrite of it, is the canonical
record.

## History

- **2026-08-23** — first commit: `paymaster: reference implementation for
  verifiable agent-spend receipts`.
- **2026-08-27** — first public (MIT) release, CI added, MCP server added.

Full commit-by-commit history is intentionally left as-is, including the
early, rougher commits — they're evidence of how the design actually
developed, not just the final shape of it. See `git log` for the complete
record; nothing has been squashed or rewritten to look cleaner in hindsight.

## What's canonical

- **Code**: this repository, `github.com/joecattt/paymaster`, `main`/`master`
  branch.
- **License**: MIT (`LICENSE`), copyright JoeCat, 2026.
- **Design record**: `RECEIPT-SPEC.md` (the receipt format and its negative
  specification — what it deliberately does NOT claim), `REVIEW-PACKET.md`
  (adversarial review notes), `CHANGELOG.md` (released versions).
- **Credit**: `AUTHORS.md`.

## What this doesn't claim

Copyright protects this implementation — the actual code. It doesn't grant
a monopoly on the underlying idea (a graded, tamper-evident receipt for
autonomous agent actions). Someone else can build a different implementation
of a similar concept without infringing anything here, and that's fine —
this document exists to make priority and provenance unambiguous, not to
claim exclusivity over an idea.
