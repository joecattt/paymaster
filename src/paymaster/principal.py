"""Authenticated principal stamps (Phase 2).

The smallest cryptographic identity primitive that binds a routed event to a
principal, without becoming an identity platform. Each principal holds a local
secret (0600); it stamps HMAC(secret, principal|ts|nonce) onto each event.
Ingest verifies the stamp and grades the record `authenticated`; unstamped
events stay `asserted`. No PKI, no server, no retroactive upgrade.

THREAT BOUNDARY (stated, not hidden): a process that can READ a principal's
key file can forge that principal — the perimeter is filesystem permissions,
exactly as the raw provider keys already are. This raises impersonation from
"write any string" to "steal a specific 0600 file", nothing more.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import time

KEYDIR = os.path.expanduser("~/.local/state/paymaster/principals")
NONCE_DB = os.path.expanduser("~/.local/state/paymaster/seen-nonces.jsonl")
SKEW_TOLERANCE_S = 300  # a stamp older/newer than this is rejected (replay + clock guard)


def _keypath(pid: str) -> str:
    safe = "".join(c for c in pid if c.isalnum() or c in "-_.")
    if safe != pid or not safe:
        raise ValueError(f"unsafe principal id: {pid!r}")
    return os.path.join(KEYDIR, f"{safe}.key")


def enroll(pid: str) -> str:
    """Create a principal's secret if absent. Returns the key path. 0600."""
    os.makedirs(KEYDIR, exist_ok=True)
    os.chmod(KEYDIR, 0o700)
    path = _keypath(pid)
    if not os.path.exists(path):
        secret = hashlib.sha256(os.urandom(32)).hexdigest()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secret)
    return path


def _load_secret(pid: str) -> str:
    path = _keypath(pid)
    st = os.stat(path)  # raises FileNotFoundError -> caller maps to "no key"
    if st.st_mode & 0o077:
        raise PermissionError(f"{path}: key is group/world accessible (mode {oct(st.st_mode & 0o777)})")
    with open(path) as f:
        return f.read().strip()


def stamp(pid: str, ts: str, nonce: str | None = None) -> dict:
    """Produce a stamp a caller attaches to its event."""
    nonce = nonce or hashlib.sha256(os.urandom(16)).hexdigest()[:16]
    secret = _load_secret(pid)
    mac = hmac.new(secret.encode(), f"{pid}|{ts}|{nonce}".encode(), hashlib.sha256).hexdigest()
    return {"principal_id": pid, "ts": ts, "nonce": nonce, "hmac": mac}


def verify(stamp_obj: dict, now: float | None = None,
           record_nonce: bool = True) -> tuple[bool, str]:
    """Verify a stamp. Returns (ok, reason_code). Reason codes are stable —
    downstream and tests key on them."""
    now = now if now is not None else time.time()
    for k in ("principal_id", "ts", "nonce", "hmac"):
        if k not in stamp_obj:
            return False, "MALFORMED_STAMP"
    pid = stamp_obj["principal_id"]
    try:
        secret = _load_secret(pid)
    except FileNotFoundError:
        return False, "NO_KEY"
    except PermissionError:
        return False, "KEY_PERMISSION"
    except ValueError:
        return False, "MALFORMED_STAMP"
    expect = hmac.new(secret.encode(),
                      f"{pid}|{stamp_obj['ts']}|{stamp_obj['nonce']}".encode(),
                      hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, str(stamp_obj["hmac"])):
        return False, "BAD_HMAC"
    # freshness: a modified or stale timestamp fails here (also bounds replay window)
    try:
        from datetime import datetime
        stamp_t = datetime.fromisoformat(stamp_obj["ts"]).timestamp()
    except (ValueError, TypeError):
        return False, "MALFORMED_STAMP"
    if abs(now - stamp_t) > SKEW_TOLERANCE_S:
        return False, "STALE_OR_SKEWED"
    # replay: a (pid,nonce) pair may be spent once within the freshness window
    key = f"{pid}:{stamp_obj['nonce']}"
    if _nonce_seen(key, now):
        return False, "REPLAYED_NONCE"
    if record_nonce:
        _remember_nonce(key, now)
    return True, "OK"


def _load_nonces(now: float) -> dict:
    seen = {}
    if os.path.exists(NONCE_DB):
        with open(NONCE_DB) as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    if now - r["t"] <= SKEW_TOLERANCE_S:  # prune expired
                        seen[r["k"]] = r["t"]
    return seen


def _nonce_seen(key: str, now: float) -> bool:
    return key in _load_nonces(now)


def _remember_nonce(key: str, now: float) -> None:
    os.makedirs(os.path.dirname(NONCE_DB), exist_ok=True)
    # compact: rewrite only live nonces + this one (bounded by freshness window)
    live = _load_nonces(now)
    live[key] = now
    tmp = NONCE_DB + ".tmp"
    with open(tmp, "w") as f:
        for k, t in live.items():
            f.write(json.dumps({"k": k, "t": t}) + "\n")
    os.replace(tmp, NONCE_DB)
