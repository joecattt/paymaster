"""Capability tokens — bounded, delegable, revocable authority (v0.2).

The agent-wish congregation's convergence point, at the software level: an
agent PRESENTS a capability instead of narrating its authority. A capability
is a signed grant: issuer -> subject, scoped, bounded, expiring, revocable,
and MONOTONIC under delegation — a child capability can only be equal to or
narrower than its parent, never wider.

Invariants enforced here (and property-tested):
  I-CAP1  authority can shrink automatically; it can never grow implicitly
  I-CAP2  a subject cannot extend its own expiry, raise its own bounds, or
          mint itself authority it does not hold
  I-CAP3  revoking a capability invalidates every capability delegated under it
  I-CAP4  delegation requires the parent to permit it, and has bounded depth
  I-CAP5  verification grade is `authenticated` (HMAC by a local enrolled
          principal) — NEVER hardware-verified. Cross-org/TEE attestation is
          the missing top rung of the evidence ladder, and this module says so
          rather than simulating it.
"""
from __future__ import annotations
import hashlib
import hmac as hmac_mod
import json
import os
from datetime import datetime, timezone

from .principal import _load_secret, _keypath  # enrolled-principal keys (0600)

CAP_VERSION = "0.2"
MAX_DEPTH = 4
REVOKED_DB = os.path.expanduser("~/.local/state/paymaster/revoked-caps.jsonl")


def _canon(o) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"))


def _sign(issuer: str, body: dict) -> str:
    secret = _load_secret(issuer)
    return hmac_mod.new(secret.encode(), _canon(body).encode(), hashlib.sha256).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def issue(issuer: str, subject: str, *, scope: dict, expires: str,
          max_usd=None, max_calls=None, allow_delegate=False,
          policy_hash=None, parent: dict | None = None) -> dict:
    """Issue a capability. With `parent`, this is a DELEGATION and every bound
    is checked monotonic against the parent before signing."""
    body = {
        "cap_version": CAP_VERSION,
        "issuer": issuer,
        "subject": subject,
        "scope": dict(scope),
        "expires": expires,
        "max_usd": max_usd,
        "max_calls": max_calls,
        "allow_delegate": bool(allow_delegate),
        "depth": 0 if parent is None else parent["depth"] + 1,
        "parent_id": None if parent is None else parent["id"],
        "policy_hash": policy_hash,
        "nonce": hashlib.sha256(os.urandom(16)).hexdigest()[:16],
    }
    if parent is not None:
        _check_monotonic(parent, body)
    body["id"] = hashlib.sha256(_canon(body).encode()).hexdigest()[:32]
    body["sig"] = _sign(issuer, {k: v for k, v in body.items() if k != "sig"})
    return body


def delegate(parent: dict, issuer: str, subject: str, *, scope=None,
             expires=None, max_usd=None, max_calls=None,
             allow_delegate=False) -> dict:
    """Delegate under `parent`. The delegating issuer must BE the parent's
    subject (you can only hand down what was handed to you), the parent must
    permit delegation, and every bound is min()'d/narrowed — I-CAP1/2/4."""
    if issuer != parent["subject"]:
        raise PermissionError(f"{issuer} does not hold capability {parent['id']} "
                              f"(held by {parent['subject']}) — cannot delegate it")
    if not parent["allow_delegate"]:
        raise PermissionError(f"capability {parent['id']} does not permit delegation")
    if parent["depth"] + 1 > MAX_DEPTH:
        raise PermissionError(f"delegation depth limit ({MAX_DEPTH}) exceeded")
    eff_scope = dict(parent["scope"])
    eff_scope.update(scope or {})            # adding keys only NARROWS
    return issue(issuer, subject,
                 scope=eff_scope,
                 expires=min(expires or parent["expires"], parent["expires"]),
                 max_usd=_min_bound(max_usd, parent["max_usd"]),
                 max_calls=_min_bound(max_calls, parent["max_calls"]),
                 allow_delegate=allow_delegate and parent["allow_delegate"],
                 policy_hash=parent.get("policy_hash"),
                 parent=parent)


def _min_bound(child, parent):
    if parent is None:
        return child
    if child is None:
        return parent
    return min(child, parent)


def _check_monotonic(parent: dict, child: dict) -> None:
    """I-CAP1: child ⊆ parent, on every dimension."""
    if child["expires"] > parent["expires"]:
        raise PermissionError("child capability outlives its parent")
    for k, v in parent["scope"].items():
        if child["scope"].get(k) != v:
            raise PermissionError(f"child scope loosens parent scope key {k!r}")
    for bound in ("max_usd", "max_calls"):
        p, c = parent[bound], child[bound]
        if p is not None and (c is None or c > p):
            raise PermissionError(f"child {bound} exceeds parent")
    if child["allow_delegate"] and not parent["allow_delegate"]:
        raise PermissionError("child grants delegation its parent denies")


def _revoked_ids() -> set:
    out = set()
    if os.path.exists(REVOKED_DB):
        with open(REVOKED_DB) as f:
            for line in f:
                if line.strip():
                    out.add(json.loads(line)["id"])
    return out


def revoke(cap_id: str, reason: str = "") -> None:
    os.makedirs(os.path.dirname(REVOKED_DB), exist_ok=True)
    with open(REVOKED_DB, "a") as f:
        f.write(_canon({"id": cap_id, "reason": reason,
                        "ts": _now().isoformat(timespec="seconds")}) + "\n")
        f.flush(); os.fsync(f.fileno())


def verify_chain(chain: list, *, now: datetime | None = None) -> dict:
    """Verify a delegation chain [root, ..., leaf]. Returns
    {valid, grade, effective, reason}. Grade is at most `authenticated` —
    this proves possession of local HMAC keys, not runtime identity (I-CAP5).
    Revocation cascades: a revoked ancestor invalidates the whole tail (I-CAP3)."""
    now = now or _now()
    revoked = _revoked_ids()
    if not chain:
        return {"valid": False, "grade": "missing", "reason": "EMPTY_CHAIN"}
    prev = None
    for i, cap in enumerate(chain):
        body = {k: v for k, v in cap.items() if k != "sig"}
        try:
            expect = _sign(cap["issuer"], body)
        except (FileNotFoundError, ValueError):
            return {"valid": False, "grade": "missing", "reason": f"NO_ISSUER_KEY[{i}]"}
        if not hmac_mod.compare_digest(expect, cap.get("sig", "")):
            return {"valid": False, "grade": "missing", "reason": f"BAD_SIGNATURE[{i}]"}
        if cap["id"] in revoked:
            return {"valid": False, "grade": "missing", "reason": f"REVOKED[{i}] (cascades)"}
        if cap["expires"] <= now.isoformat(timespec="seconds"):
            return {"valid": False, "grade": "missing", "reason": f"EXPIRED[{i}]"}
        if prev is not None:
            if cap["parent_id"] != prev["id"]:
                return {"valid": False, "grade": "missing", "reason": f"BROKEN_LINK[{i}]"}
            if cap["issuer"] != prev["subject"]:
                return {"valid": False, "grade": "missing", "reason": f"ISSUER_NOT_HOLDER[{i}]"}
            try:
                _check_monotonic(prev, cap)
            except PermissionError as e:
                return {"valid": False, "grade": "missing", "reason": f"NON_MONOTONIC[{i}]: {e}"}
        prev = cap
    leaf = chain[-1]
    return {"valid": True, "grade": "authenticated",
            "effective": {"subject": leaf["subject"], "scope": leaf["scope"],
                          "max_usd": leaf["max_usd"], "max_calls": leaf["max_calls"],
                          "expires": leaf["expires"], "depth": leaf["depth"]},
            "reason": "OK"}
