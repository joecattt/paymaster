# Changelog

Versions below are grounded in actual git tags/commits — see `git log
<tag>` for the full diff behind each one. `pyproject.toml` carries the
current version (`0.5.0`); this file will get a matching tag at the next
release.

## [Unreleased] — 0.5.0

- MCP server (`mcp_server/server.py`) — 9 tools wrapping the SDK.
- Packaging: `pyproject.toml` so the library installs via `pip install -e .`.
- CI: GitHub Actions running the test suite on push/PR.
- `ORIGIN.md`, `AUTHORS.md` — provenance and credit, explicit.
- Trial + license gate (`src/paymaster/license.py`), **armed**: enforcement is
  on by default; `PAYMASTER_LICENSE=0` turns it off, which is documented in the
  README rather than hidden, because this is MIT source and the gate is a
  request rather than a lock. Warns at 80% of the cap so the wall is never the
  first a user hears of it. The read/audit surface (`report`, `verify`,
  `explain`, `coverage`, `prove-nonzero`) is never gated at any spend level — a
  tool arguing "check this yourself" cannot paywall the checking. `ingest`/`check` block
  once $50 of reconciled (priced) spend has passed through the ledger,
  unless a signed license key is activated. Ed25519 (asymmetric) signature
  check, offline, no phone-home server — consistent with the
  MIT/auditable-by-design posture. Verification uses only the public key
  embedded in the module; the private key stays operator-side
  (`~/.config/paymaster/license_signing.key`, 0600, never distributed), so
  no customer machine needs a secret that could also mint free keys — an
  HMAC/shared-secret draft of this had exactly that hole and was replaced
  before shipping. Unpriceable spend is excluded from the trial count,
  never guessed at $0. `bin/issue-license` is operator-only (not exposed
  via CLI dispatch or the MCP server), same exclusion pattern as
  `grant`/`enroll`. Requires the optional `cryptography` dependency
  (`pip install '.[license]'`); still bypassable by anyone who patches the
  enforcement call site out of the (MIT) source — that tradeoff was
  explicit, not an oversight. Pay link: $49 one-time via PayPal (JoeCat
  LLC), not a subscription — no hosted billing backend exists to justify
  recurring charges.
  Two defects found and fixed before this landed: (1) with `cryptography`
  absent, every key silently failed to verify, so an over-cap customer who
  had *paid* was locked out and told their valid key "does not verify" —
  `activate()` now names the missing package, and `check_trial()` fails OPEN
  when no key could be verified at all, per fiction 4 (a control whose
  failure mode is denial of service against legitimate users is worse than
  no control); (2) `CLAIMS.json` already carried a probe for
  `tests.test_license`, which passed locally and would have failed in any
  fresh clone, because none of these files were committed. A third:
  `bin/issue-license` could mint a key that no customer could activate if the
  signing key and the shipped `PUBLIC_KEY_HEX` ever diverged — it now verifies
  every key against the public half before printing it, and refuses rather than
  handing a buyer a dead key. The claim was
  published before the code was — exactly the failure the CLAIMS discipline
  exists to catch, caught by it a week late.

## v0.2.0 — 2026-08-24

Capability primitive: bounded, delegable, revocable authority + receipt
slots (I-CAP1–5 property-tested, 86 tests).

## v0.1.2 — 2026-08-24

Regenerated export from the consolidated dev source — fixed two-source
drift that had clobbered graceful-failure handling.

## v0.1.1 — 2026-08-24

Pre-review defect fixes: nonce-store race condition (flock), path-traversal
guard, a visible decision-link looseness, crash guards. 74 tests.

## v0.1.0 — 2026-08-24

First tagged release: graceful failure in credential-less/stateless
environments (release blockers cleared).

## 2026-08-23

Initial commit — reference implementation for verifiable agent-spend
receipts.
