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

class ChainAnchoring(unittest.TestCase):
    """PM-001: a chain must start at a root, else revoked ancestors are invisible."""
    @classmethod
    def setUpClass(cls):
        for p in ("company", "agent-a", "agent-b", "agent-c"):
            principal.enroll(p)

    def _chain(self):
        root = C.issue("company", "agent-a", scope={"provider": "x"}, expires=iso(hours=2),
                       max_usd=20.0, max_calls=10, allow_delegate=True)
        child = C.delegate(root, "agent-a", "agent-b", expires=iso(hours=1), allow_delegate=True)
        leaf = C.delegate(child, "agent-b", "agent-c", expires=iso(minutes=30))
        return root, child, leaf

    def test_leaf_alone_is_not_valid(self):
        root, child, leaf = self._chain()
        v = C.verify_chain([leaf])
        self.assertFalse(v["valid"]); self.assertEqual(v["reason"], "NOT_ROOT_ANCHORED")
        self.assertNotIn("effective", v)

    def test_headless_chain_is_not_valid(self):
        root, child, leaf = self._chain()
        v = C.verify_chain([child, leaf])
        self.assertFalse(v["valid"]); self.assertEqual(v["reason"], "NOT_ROOT_ANCHORED")

    def test_revoked_root_invalidates_truncated_chains(self):
        root, child, leaf = self._chain()
        C.revoke(root["id"], "cascade")
        for chain in ([root, child, leaf], [child, leaf], [leaf]):
            self.assertFalse(C.verify_chain(chain)["valid"])

    def test_full_chain_still_valid(self):
        root, child, leaf = self._chain()
        self.assertTrue(C.verify_chain([root, child, leaf])["valid"])
        self.assertTrue(C.verify_chain([root])["valid"])

    def test_skipped_link_is_rejected(self):
        root, child, leaf = self._chain()
        v = C.verify_chain([root, leaf])
        self.assertFalse(v["valid"]); self.assertIn("BROKEN_LINK", v["reason"])
class ExpiryParsing(unittest.TestCase):
    """PM-002: expiry is parsed to aware datetimes and compared as instants; fail closed."""
    NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    @classmethod
    def setUpClass(cls):
        principal.enroll("company")
        cls.base = C.issue("company", "company", scope={}, expires=iso(hours=1))

    def _signed(self, expires):
        """A cap signed by a legitimate key holder carrying an arbitrary expiry value."""
        body = {k: v for k, v in self.base.items() if k not in ("sig", "id")}
        body["expires"] = expires
        body["id"] = "x" + str(abs(hash(repr(expires))))
        body["sig"] = C._sign("company", {k: v for k, v in body.items() if k != "sig"})
        return body

    def _v(self, expires):
        return C.verify_chain([self._signed(expires)], now=self.NOW)

    def test_garbage_strings_are_invalid_not_immortal(self):
        for bad in ("zzzz", "9999", "zzzz-never", "", "2025/01/01", "12/31/2025"):
            v = self._v(bad)
            self.assertFalse(v["valid"], bad); self.assertIn("INVALID_EXPIRY", v["reason"], bad)

    def test_non_string_types_fail_closed_without_crash(self):
        for bad in (None, 1, 1.5, True, ["x"]):
            v = self._v(bad)
            self.assertFalse(v["valid"], repr(bad)); self.assertIn("INVALID_EXPIRY", v["reason"])

    def test_bytes_expiry_fails_closed_without_crash(self):
        cap = dict(self._signed("2026-10-01T13:00:00+00:00"), expires=b"2026-10-01T13:00:00+00:00")
        v = C.verify_chain([cap], now=self.NOW)
        self.assertFalse(v["valid"]); self.assertEqual(v["reason"], "MALFORMED[0]")

    def test_naive_and_date_only_are_invalid(self):
        for bad in ("2026-10-01T13:00:00", "2026-10-01", "2099-01-01"):
            self.assertIn("INVALID_EXPIRY", self._v(bad)["reason"], bad)

    def test_offsets_compare_as_instants(self):
        self.assertFalse(self._v("2026-10-01T16:30:00+05:00")["valid"])   # = 11:30Z, past
        self.assertIn("EXPIRED", self._v("2026-10-01T16:30:00+05:00")["reason"])
        self.assertTrue(self._v("2026-10-01T05:00:00-08:00")["valid"])    # = 13:00Z, future
        self.assertTrue(self._v("2026-10-01T13:00:00Z")["valid"])
        self.assertFalse(self._v("2026-10-01T11:00:00Z")["valid"])
        self.assertTrue(self._v("2026-10-01 13:00:00+00:00")["valid"])

    def test_boundary_is_expired(self):                   # existing semantic: exp <= now is expired
        self.assertFalse(self._v("2026-10-01T12:00:00+00:00")["valid"])
        self.assertFalse(self._v("2026-10-01T17:00:00+05:00")["valid"])
        self.assertTrue(self._v("2026-10-01T12:00:01+00:00")["valid"])

    def test_issue_refuses_to_sign_malformed_expiry(self):
        for bad in ("zzzz", "9999", None, 5, "2026-10-01T13:00:00"):
            with self.assertRaises(ValueError):
                C.issue("company", "company", scope={}, expires=bad)

    def test_delegate_compares_instants_not_strings(self):
        root = C.issue("company", "company", scope={}, expires="2026-10-01T13:00:00+00:00",
                       allow_delegate=True)
        # 05:00-08:00 is the same instant as the parent; lexical compare mis-ordered it
        same = C.issue("company", "company", scope={}, expires="2026-10-01T05:00:00-08:00",
                       parent=root)
        self.assertEqual(same["expires"], "2026-10-01T05:00:00-08:00")
        with self.assertRaises(PermissionError):   # 13:30Z is later than parent
            C.issue("company", "company", scope={}, expires="2026-10-01T13:30:00Z", parent=root)
        with self.assertRaises(ValueError):
            C.delegate(root, "company", "company", expires="zzzz")
        d = C.delegate(root, "company", "company", expires="2026-10-01T16:00:00+05:00")
        self.assertEqual(d["expires"], "2026-10-01T16:00:00+05:00")       # 11:00Z is earlier
        d2 = C.delegate(root, "company", "company", expires="2026-10-01T23:00:00+05:00")
        self.assertEqual(d2["expires"], root["expires"])                  # 18:00Z later -> capped

if __name__ == "__main__":
    unittest.main(verbosity=1)
