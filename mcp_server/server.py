"""MCP server for paymaster — exposes the CLI's read/reconcile surface as
MCP tools. Thin wrapper: every tool below shells out to bin/paymaster, the
same binary the Quickstart and CLAIMS.json probes exercise. No engine logic
lives here.

Deliberately excludes grant / revoke-cap / enroll (capability minting and
principal key management) and x402 (needs on-disk payment-payload files) —
those stay CLI-only, human-invoked. This mirrors paymaster's own design law:
detective, not preventive; it doesn't hand an agent the keys to itself.

Run:
  python -m mcp_server.server
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("paymaster")

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BIN = _REPO_ROOT / "bin" / "paymaster"


def _run(*args: str) -> dict:
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT / "src")}
    proc = subprocess.run(
        ["python3", str(_BIN), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return {
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


@mcp.tool()
def ingest() -> dict:
    """Pull new ai-route events into the ledger (idempotent; auto-anchors).
    Does not move money — appends to the local hash-chained ledger only."""
    return _run("ingest")


@mcp.tool()
def check() -> dict:
    """Evaluate budgets as purchase orders. exit_code 2 means BREACH, ORPHAN,
    or UNPRICEABLE spend exists (fail-closed gate; this tool only reports it,
    it does not block anything)."""
    return _run("check")


@mcp.tool()
def report(days: int | None = None) -> dict:
    """Spend rollup by rail/provider. Pass days to limit the window."""
    args = ["report"]
    if days is not None:
        args += ["--days", str(days)]
    return _run(*args)


@mcp.tool()
def consider(days: int | None = None) -> dict:
    """Provider consideration/reliability per principal, derived from
    fallback telemetry."""
    args = ["consider"]
    if days is not None:
        args += ["--days", str(days)]
    return _run(*args)


@mcp.tool()
def coverage(provider: str | None = None) -> dict:
    """Compare the known (ledger) sum against the provider's own aggregate.
    exit_code 2 means unaccounted spend exists outside the governed route."""
    args = ["coverage"]
    if provider:
        args.append(provider)
    return _run(*args)


@mcp.tool()
def verify() -> dict:
    """Verify the tamper-evident hash chain and its git-anchored tail.
    exit_code 2 means the chain is broken, torn, or reordered."""
    return _run("verify")


@mcp.tool()
def explain(record_id_or_seq: str) -> dict:
    """Decision Receipt for one record: who/what/authority/cost/reconcile/gaps,
    with each field graded by its evidence source. Returns parsed JSON."""
    result = _run("explain", record_id_or_seq, "--json")
    if result["exit_code"] == 0 and result["stdout"]:
        import json

        try:
            result["receipt"] = json.loads(result["stdout"])
        except json.JSONDecodeError:
            pass
    return result


@mcp.tool()
def reconcile_counters() -> dict:
    """Rebuild the counter cache from the ledger and compare; exit_code 2 on
    drift (the ledger is authoritative, the counter cache is disposable)."""
    return _run("reconcile-counters")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
