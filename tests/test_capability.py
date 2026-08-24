"""Property tests for the capability invariants — the operator's own guardrails:
authority can shrink automatically; it can never grow implicitly."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
_TMP = tempfile.mkdtemp(); os.environ["HOME"] = _TMP
import importlib
from paymaster import principal, capability as C
importlib.reload(principal); importlib.reload(C)
principal.KEYDIR = os.path.join(_TMP, "keys"); principal.NONCE_DB = os.path.join(_TMP, "n.jsonl")
C.REVOKED_DB = os.path.join(_TMP, "revoked.jsonl")

from datetime import datetime, timezone, timedelta
def iso(**kw): return (datetime.now(timezone.utc) + timedelta(**kw)).isoformat(timespec="seconds")

class Capability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for p in ("company", "agent-a", "agent-b", "agent-c"):
            principal.enroll(p)
        cls.root = C.issue("company", "agent-a", scope={"provider": "openrouter"},
                           expires=iso(hours=2), max_usd=20.0, max_calls=100,
                           allow_delegate=True)

    def test_valid_chain_verifies_at_authenticated_never_higher(self):
        child = C.delegate(self.root, "agent-a", "agent-b", max_usd=7.0, expires=iso(hours=1))
        v = C.verify_chain([self.root, child])
        self.assertTrue(v["valid"])
        self.assertEqual(v["grade"], "authenticated")     # I-CAP5: never hardware-verified
        self.assertEqual(v["effective"]["max_usd"], 7.0)

    def test_child_cannot_exceed_parent_amount(self):     # I-CAP1
        child = C.delegate(self.root, "agent-a", "agent-b", max_usd=500.0)
        self.assertEqual(child["max_usd"], 20.0)          # min()'d down, never up

    def test_child_cannot_outlive_parent(self):           # I-CAP1
        child = C.delegate(self.root, "agent-a", "agent-b", expires=iso(days=30))
        self.assertLessEqual(child["expires"], self.root["expires"])

    def test_subject_cannot_self_amplify(self):           # I-CAP2
        child = C.delegate(self.root, "agent-a", "agent-b", max_usd=5.0, allow_delegate=True)
        with self.assertRaises(PermissionError):
            # b tries to mint itself a wider grant under its own capability
            forged = dict(child, max_usd=50.0)
            C._check_monotonic(child, forged) or C.delegate(child, "agent-b", "agent-b", max_usd=50.0)
        wider = C.delegate(child, "agent-b", "agent-b", max_usd=50.0)
        self.assertEqual(wider["max_usd"], 5.0)           # even self-delegation only narrows

    def test_non_holder_cannot_delegate(self):            # I-CAP2
        with self.assertRaises(PermissionError):
            C.delegate(self.root, "agent-c", "agent-b")   # c doesn't hold root

    def test_no_delegate_flag_blocks(self):               # I-CAP4
        sealed = C.issue("company", "agent-a", scope={}, expires=iso(hours=1),
                         allow_delegate=False)
        with self.assertRaises(PermissionError):
            C.delegate(sealed, "agent-a", "agent-b")

    def test_scope_only_narrows(self):                    # I-CAP1
        child = C.delegate(self.root, "agent-a", "agent-b",
                           scope={"action": "inference"})  # ADDS a key = narrower
        self.assertEqual(child["scope"]["provider"], "openrouter")
        forged = dict(child); forged["scope"] = {"provider": "anyone"}
        with self.assertRaises(PermissionError):
            C._check_monotonic(self.root, forged)

    def test_revocation_cascades(self):                   # I-CAP3
        mid = C.delegate(self.root, "agent-a", "agent-b", allow_delegate=True)
        leaf = C.delegate(mid, "agent-b", "agent-c")
        self.assertTrue(C.verify_chain([self.root, mid, leaf])["valid"])
        C.revoke(mid["id"], "compromised")
        v = C.verify_chain([self.root, mid, leaf])
        self.assertFalse(v["valid"]); self.assertIn("REVOKED", v["reason"])

    def test_forged_signature_fails(self):
        bad = dict(self.root, max_usd=9999.0)             # tamper after signing
        v = C.verify_chain([bad])
        self.assertFalse(v["valid"]); self.assertIn("BAD_SIGNATURE", v["reason"])

    def test_expired_fails(self):
        old = C.issue("company", "agent-a", scope={}, expires=iso(seconds=-10))
        v = C.verify_chain([old])
        self.assertFalse(v["valid"]); self.assertIn("EXPIRED", v["reason"])

    def test_broken_link_fails(self):
        other = C.issue("company", "agent-b", scope={}, expires=iso(hours=1))
        v = C.verify_chain([self.root, other])            # not actually a child
        self.assertFalse(v["valid"]); self.assertIn("BROKEN_LINK", v["reason"])

    def test_depth_limit(self):                           # I-CAP4
        cur = self.root
        holders = ["agent-a", "agent-b", "agent-c", "agent-a", "agent-b"]
        with self.assertRaises(PermissionError):
            for i in range(5):
                principal.enroll(holders[i])
                cur = C.delegate(cur, cur["subject"], holders[(i+1) % 5], allow_delegate=True)

if __name__ == "__main__":
    unittest.main(verbosity=1)
