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
