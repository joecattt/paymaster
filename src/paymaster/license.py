"""Trial metering + local license check (honor-system, no server).

Design (panel decision, 2026-08-28 — see CHANGELOG):
  - credit unit  = dollars of reconciled spend seen through the ledger,
                   not action count (matches paymaster's own pricing.py math,
                   not gameable by issuing free/zero-token calls)
  - enforcement  = local Ed25519-signed license key, checked offline. No
                   phone-home server: this is MIT source, a hosted check
                   would be both bypassable-by-patching AND a black-box trust
                   requirement from a tool whose entire pitch is refusing to
                   ask you to trust unverifiable claims.

                   Asymmetric, not HMAC: verification uses only the PUBLIC
                   key embedded below, so any machine can check a key
                   offline without holding anything that could mint new
                   ones. The PRIVATE key never leaves the operator's
                   machine (PRIVATE_KEY_PATH, 0600, gitignored) — that's
                   what `bin/issue-license` needs and customers never see.
                   A shared-secret (HMAC) scheme was the first draft and
                   was wrong: it would have required either shipping the
                   secret (letting anyone self-issue free keys, no patching
                   needed) or leaving customer machines unable to verify a
                   real key at all.
  - trial cap    = TRIAL_LIMIT_USD, below. Once Σ(priced spend) crosses it
                   without an activated license, gated commands print a
                   pay link and exit nonzero. Spend that prices to None
                   (unpriceable) does NOT count against the trial — it is
                   excluded, not silently charged as zero (see pricing.py's
                   own honesty rule: never guess a price).

Still an honor-system gate: anyone who reads and patches this file's
enforcement call site can bypass it. What asymmetric signing buys you is
narrower — a bypass requires editing code, not just reading a shared
secret out of the installed package.

This module does not move money and does not contact any server. It only
computes a number from the local ledger and checks a signature.
"""
from __future__ import annotations
import base64
import json
import os
import time

from . import pricing as P

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey,
    )
    from cryptography.exceptions import InvalidSignature
    _HAVE_CRYPTO = True
except ImportError:
    _HAVE_CRYPTO = False

TRIAL_LIMIT_USD = 50.00
PAY_LINK = "https://www.paypal.com/ncp/payment/AE8CZW8NUUQQ2"  # $49 one-time, JoeCat LLC

# Enforcement ships DORMANT. The public repository is MIT and is currently
# being read by reviewers who were invited to audit it; a live paywall on
# `ingest`/`check` would contradict that invitation before any distribution
# decision has actually been made. The mechanism is complete, tested, and one
# environment variable away from active:
#
#     PAYMASTER_LICENSE=1 paymaster ingest
#
# Turning it on for a commercial distribution is a business decision, not a
# code change. Until it is made, nothing is gated.
ENFORCE_ENV = "PAYMASTER_LICENSE"


def enforcement_enabled() -> bool:
    return os.environ.get(ENFORCE_ENV, "") == "1"

# Operator-only. Never distributed, never committed. bin/issue-license reads
# this to mint keys; customers running `paymaster license activate` never
# need it — verify_license below checks against PUBLIC_KEY_HEX instead.
PRIVATE_KEY_PATH = os.path.expanduser("~/.config/paymaster/license_signing.key")

# Safe to ship: this key can only VERIFY signatures, not mint them. Generated
# once alongside PRIVATE_KEY_PATH; if you rotate keys, update both together
# or every previously-issued license key stops verifying.
PUBLIC_KEY_HEX = "4f8325bef45020401524a3b7fd9d9802669ed1ce308ce69539530708a0c93199"


def _require_crypto():
    if not _HAVE_CRYPTO:
        raise RuntimeError(
            "license signing/verification needs the 'cryptography' package "
            "(pip install cryptography, or: pip install '.[license]')"
        )


def _load_private_key() -> "Ed25519PrivateKey":
    _require_crypto()
    if not os.path.exists(PRIVATE_KEY_PATH):
        raise FileNotFoundError(
            f"no signing key at {PRIVATE_KEY_PATH} — this machine cannot "
            "issue licenses. Only the operator's machine should have this "
            "file; customers never need it to activate a key."
        )
    with open(PRIVATE_KEY_PATH, "rb") as f:
        return Ed25519PrivateKey.from_private_bytes(f.read())


def reconciled_spend_usd(ledger, table=None) -> float:
    """Σ priced spend across the ledger. Records that price to None (unknown
    provider/model) are excluded — never guessed, never charged as $0."""
    table = table if table is not None else P.load()
    total = 0.0
    for rec in ledger.records():
        usd = P.price(rec, table)
        if usd is not None:
            total += usd
    return round(total, 6)


def sign_license(email: str, plan: str = "lifetime") -> str:
    """Operator-only: mint a license key. Requires PRIVATE_KEY_PATH to exist."""
    priv = _load_private_key()
    payload = {"email": email, "plan": plan, "issued": int(time.time())}
    body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode().rstrip("=")
    sig = priv.sign(body.encode())
    sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"PM1.{body}.{sig_b64}"


def verify_license(key: str) -> dict | None:
    """Return the decoded payload if the signature checks out, else None.
    Never raises on malformed input — a bad key is just not a license.
    Uses only PUBLIC_KEY_HEX — works on any machine, mints nothing."""
    if not _HAVE_CRYPTO:
        return None
    try:
        _, body, sig_b64 = key.strip().split(".", 2)
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX))
        sig = base64.urlsafe_b64decode(sig_b64 + "=" * (-len(sig_b64) % 4))
        pub.verify(sig, body.encode())
        padded = body + "=" * (-len(body) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, InvalidSignature, json.JSONDecodeError):
        return None


def _license_path(state_dir: str) -> str:
    return os.path.join(state_dir, "license.json")


def activate(key: str, state_dir: str) -> dict:
    """Verify and persist a license key locally. Raises ValueError on a bad key.

    Checks for the crypto dependency FIRST: without it every key fails to
    verify, and telling a paying customer their valid key "does not verify"
    when the real problem is a missing package is the worst error message this
    module could produce.
    """
    _require_crypto()
    payload = verify_license(key)
    if payload is None:
        raise ValueError("license key does not verify — check for typos, or it wasn't issued for this build")
    os.makedirs(state_dir, exist_ok=True)
    with open(_license_path(state_dir), "w") as f:
        json.dump({"key": key, **payload}, f)
    return payload


def is_licensed(state_dir: str) -> bool:
    path = _license_path(state_dir)
    if not os.path.exists(path):
        return False
    with open(path) as f:
        saved = json.load(f)
    return verify_license(saved.get("key", "")) is not None


def check_trial(ledger, state_dir: str) -> dict:
    """Returns {ok, spent, limit, remaining, licensed, enforceable}. ok=False
    means a gated command should refuse to run and point at PAY_LINK.

    Fails OPEN when the crypto dependency is absent. Without it no key can be
    verified, so enforcing would lock out a customer who has paid and cannot
    activate — the tool denying service to the person who bought it. That is
    fiction 4 of the receipt spec ("fail-closed is not operational safety")
    applied to this module: a control whose failure mode is a denial of service
    against legitimate users is a worse control than none.
    """
    licensed = is_licensed(state_dir)
    spent = reconciled_spend_usd(ledger)
    remaining = round(TRIAL_LIMIT_USD - spent, 6)
    return {
        "ok": licensed or spent < TRIAL_LIMIT_USD or not _HAVE_CRYPTO,
        "spent": spent,
        "limit": TRIAL_LIMIT_USD,
        "remaining": max(0.0, remaining),
        "licensed": licensed,
        "enforceable": _HAVE_CRYPTO,
    }
