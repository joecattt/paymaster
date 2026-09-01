import base64
import json
import os
import tempfile
import unittest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from paymaster import license as L
from paymaster.ledger import Ledger

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False


@unittest.skipUnless(HAVE_CRYPTO, "cryptography package not installed")
class TestLicense(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Isolated test keypair — never touches the operator's real signing
        # key at ~/.config/paymaster/license_signing.key.
        priv = Ed25519PrivateKey.generate()
        priv_path = os.path.join(self.tmp, "signing.key")
        from cryptography.hazmat.primitives import serialization
        with open(priv_path, "wb") as f:
            f.write(priv.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption(),
            ))
        pub_bytes = priv.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        L.PRIVATE_KEY_PATH = priv_path
        L.PUBLIC_KEY_HEX = pub_bytes.hex()
        self.state_dir = os.path.join(self.tmp, "state")

    def test_sign_and_verify_roundtrip(self):
        key = L.sign_license("buyer@example.com", plan="lifetime")
        payload = L.verify_license(key)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["email"], "buyer@example.com")
        self.assertEqual(payload["plan"], "lifetime")

    def test_verify_needs_only_public_key_not_private(self):
        """The whole point of asymmetric signing: verification must not
        require the private key. Delete it and verification still works."""
        key = L.sign_license("buyer@example.com")
        os.remove(L.PRIVATE_KEY_PATH)
        payload = L.verify_license(key)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["email"], "buyer@example.com")

    def test_sign_without_private_key_raises(self):
        os.remove(L.PRIVATE_KEY_PATH)
        with self.assertRaises(FileNotFoundError):
            L.sign_license("buyer@example.com")

    def test_key_signed_by_different_keypair_rejected(self):
        """A key minted with someone else's private key must not verify
        against this build's public key — proves you can't self-issue by
        generating your own keypair."""
        other_priv = Ed25519PrivateKey.generate()
        payload = {"email": "forger@example.com", "plan": "lifetime", "issued": 0}
        body = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True).encode()).decode().rstrip("=")
        sig = other_priv.sign(body.encode())
        sig_b64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
        forged = f"PM1.{body}.{sig_b64}"
        self.assertIsNone(L.verify_license(forged))

    def test_tampered_key_rejected(self):
        # Flip a character in the middle of the signature, not the last
        # char of the whole string: base64 without padding has "don't
        # care" bits in its final group, so a last-char flip can decode
        # to the same bytes and isn't a real tamper test.
        key = L.sign_license("buyer@example.com")
        mid = len(key) // 2
        flipped = "0" if key[mid] != "0" else "1"
        tampered = key[:mid] + flipped + key[mid + 1:]
        self.assertIsNone(L.verify_license(tampered))

    def test_garbage_key_rejected_not_raised(self):
        self.assertIsNone(L.verify_license("not-a-license-key"))
        self.assertIsNone(L.verify_license(""))

    def test_activate_persists_and_is_licensed(self):
        key = L.sign_license("buyer@example.com")
        self.assertFalse(L.is_licensed(self.state_dir))
        L.activate(key, self.state_dir)
        self.assertTrue(L.is_licensed(self.state_dir))

    def test_activate_bad_key_raises(self):
        with self.assertRaises(ValueError):
            L.activate("garbage", self.state_dir)

    def test_reconciled_spend_sums_priced_records_only(self):
        ledger = Ledger(os.path.join(self.tmp, "spend.jsonl"))
        table = {"testprov": {"usd_per_mtok_in": 1.0, "usd_per_mtok_out": 1.0}}
        ledger.append({"id": "1", "provider": "testprov", "tokens_in": 1_000_000,
                        "tokens_out": 0, "usd": None})
        ledger.append({"id": "2", "provider": "unknown-provider", "tokens_in": 1_000_000,
                        "tokens_out": 0, "usd": None})
        total = L.reconciled_spend_usd(ledger, table)
        self.assertEqual(total, 1.0)  # only the priced record counts; unknown excluded

    def test_check_trial_ok_under_cap_blocks_over_cap(self):
        ledger = Ledger(os.path.join(self.tmp, "spend.jsonl"))

        t = L.check_trial(ledger, self.state_dir)
        self.assertTrue(t["ok"])
        self.assertFalse(t["licensed"])

        orig = L.reconciled_spend_usd
        L.reconciled_spend_usd = lambda ledger, table=None: L.TRIAL_LIMIT_USD + 1
        try:
            t2 = L.check_trial(ledger, self.state_dir)
            self.assertFalse(t2["ok"])
            self.assertEqual(t2["remaining"], 0.0)
        finally:
            L.reconciled_spend_usd = orig

    def test_licensed_bypasses_exhausted_trial(self):
        ledger = Ledger(os.path.join(self.tmp, "spend.jsonl"))
        key = L.sign_license("buyer@example.com")
        L.activate(key, self.state_dir)
        orig = L.reconciled_spend_usd
        L.reconciled_spend_usd = lambda ledger, table=None: L.TRIAL_LIMIT_USD + 1
        try:
            t = L.check_trial(ledger, self.state_dir)
            self.assertTrue(t["ok"])
            self.assertTrue(t["licensed"])
        finally:
            L.reconciled_spend_usd = orig


class TestEnforcementIsDormantByDefault(unittest.TestCase):
    """The mechanism ships complete and switched off. These tests exist so that
    turning it on is a deliberate act someone has to commit, not a default that
    drifts back in unnoticed."""

    def setUp(self):
        self._saved = os.environ.pop(L.ENFORCE_ENV, None)

    def tearDown(self):
        os.environ.pop(L.ENFORCE_ENV, None)
        if self._saved is not None:
            os.environ[L.ENFORCE_ENV] = self._saved

    def test_disabled_when_env_unset(self):
        self.assertFalse(L.enforcement_enabled())

    def test_disabled_for_any_value_other_than_1(self):
        for value in ("0", "", "true", "yes", "2"):
            os.environ[L.ENFORCE_ENV] = value
            self.assertFalse(L.enforcement_enabled(), f"{value!r} must not enable")

    def test_enabled_only_by_explicit_1(self):
        os.environ[L.ENFORCE_ENV] = "1"
        self.assertTrue(L.enforcement_enabled())


class TestFailsOpenWithoutCrypto(unittest.TestCase):
    """Without the optional crypto dependency no key can verify. Enforcing then
    would deny service to a customer who has paid and cannot activate — worse
    than not enforcing at all (receipt-spec fiction 4)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.state_dir = os.path.join(self.tmp, "state")
        self._have = L._HAVE_CRYPTO
        L._HAVE_CRYPTO = False

    def tearDown(self):
        L._HAVE_CRYPTO = self._have

    def test_trial_check_fails_open_and_says_it_is_unenforceable(self):
        ledger = Ledger(os.path.join(self.tmp, "spend.jsonl"))
        orig = L.reconciled_spend_usd
        L.reconciled_spend_usd = lambda ledger, table=None: L.TRIAL_LIMIT_USD + 1
        try:
            t = L.check_trial(ledger, self.state_dir)
            self.assertTrue(t["ok"], "must not gate when no key could be verified")
            self.assertFalse(t["enforceable"])
        finally:
            L.reconciled_spend_usd = orig

    def test_activate_blames_the_missing_package_not_the_key(self):
        with self.assertRaises(RuntimeError) as ctx:
            L.activate("PM1.whatever.sig", self.state_dir)
        self.assertIn("cryptography", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
