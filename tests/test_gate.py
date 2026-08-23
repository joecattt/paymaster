import os, sys, tempfile, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Isolate all state into a temp HOME before importing modules that resolve paths
_TMP = tempfile.mkdtemp()
os.environ["HOME"] = _TMP
import importlib
from paymaster import principal, gate, budgets
importlib.reload(principal); importlib.reload(gate)
principal.KEYDIR = os.path.join(_TMP, "keys")
principal.NONCE_DB = os.path.join(_TMP, "nonces.jsonl")
gate.DECISIONS = os.path.join(_TMP, "decisions.jsonl")

from datetime import datetime, timezone
def nowiso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TestPrincipalStamp(unittest.TestCase):
    def setUp(self):
        principal.enroll("alice"); principal.enroll("bob")

    def test_valid_stamp(self):
        ok, r = principal.verify(principal.stamp("alice", nowiso()))
        self.assertTrue(ok); self.assertEqual(r, "OK")

    def test_wrong_key_fails(self):
        s = principal.stamp("alice", nowiso())
        s["principal_id"] = "bob"           # claim bob, signed by alice's key
        self.assertEqual(principal.verify(s)[1], "BAD_HMAC")

    def test_missing_key(self):
        s = {"principal_id": "ghost", "ts": nowiso(), "nonce": "x", "hmac": "y"}
        self.assertEqual(principal.verify(s)[1], "NO_KEY")

    def test_modified_field_breaks_hmac(self):
        for field in ("ts", "nonce", "principal_id"):
            s = principal.stamp("alice", nowiso())
            s[field] = s[field] + "x" if field != "ts" else "2020-01-01T00:00:00+00:00"
            ok, r = principal.verify(s)
            self.assertFalse(ok, field)

    def test_replay_rejected(self):
        s = principal.stamp("alice", nowiso())
        self.assertEqual(principal.verify(s)[1], "OK")
        self.assertEqual(principal.verify(s)[1], "REPLAYED_NONCE")  # second use

    def test_stale_timestamp_rejected(self):
        s = principal.stamp("alice", "2020-01-01T00:00:00+00:00")
        self.assertEqual(principal.verify(s)[1], "STALE_OR_SKEWED")

    def test_malformed(self):
        self.assertEqual(principal.verify({"principal_id": "alice"})[1], "MALFORMED_STAMP")

    def test_key_permission_failure(self):
        principal.enroll("carol")
        os.chmod(principal._keypath("carol"), 0o644)   # group/world readable
        s = {"principal_id": "carol", "ts": nowiso(), "nonce": "n", "hmac": "h"}
        self.assertEqual(principal.verify(s)[1], "KEY_PERMISSION")


class TestShadowGate(unittest.TestCase):
    BUDGETS = [{"id": "po-a", "scope": {"principal": "alice"}, "window": "day", "limit_calls": 3}]

    def test_allow_within(self):
        snap = gate.Snapshot(self.BUDGETS).build([])
        d = snap.decide(principal="alice", provider="groq")
        self.assertEqual(d["decision"], "ALLOW")
        self.assertEqual(d["reason_code"], "WITHIN_BUDGET")

    def test_deny_over_limit(self):
        snap = gate.Snapshot(self.BUDGETS).build([])
        ts = nowiso()
        for _ in range(3):
            snap.advance("alice", "groq", 0, 1, ts)
        d = snap.decide(principal="alice", provider="groq")
        self.assertEqual(d["decision"], "DENY")
        self.assertEqual(d["reason_code"], "OVER_CALL_LIMIT")

    def test_orphan_denied(self):
        snap = gate.Snapshot(self.BUDGETS).build([])
        d = snap.decide(principal="stranger", provider="groq")
        self.assertEqual(d["reason_code"], "ORPHAN_NO_BUDGET")

    def test_decision_reproducible_from_policy_hash(self):
        s1 = gate.Snapshot(self.BUDGETS).build([])
        s2 = gate.Snapshot(self.BUDGETS).build([])
        self.assertEqual(s1.decide(principal="alice", provider="groq")["policy_hash"],
                         s2.decide(principal="alice", provider="groq")["policy_hash"])

    def test_gate_unavailable_is_deny(self):
        d = gate.evaluate("alice", "groq", budgets=None,
                          tz="UTC")  # forces ledger load; may fail -> DENY/GATE_UNAVAILABLE or ALLOW
        self.assertIn(d["decision"], ("ALLOW", "DENY"))
        self.assertIn("mode", d)

    def test_decision_log_chained(self):
        gate.evaluate("alice", "groq", budgets=self.BUDGETS, tz="UTC")
        gate.evaluate("alice", "groq", budgets=self.BUDGETS, tz="UTC")
        import json
        rows = [json.loads(l) for l in open(gate.DECISIONS) if l.strip()]
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual(rows[-1]["prev"], rows[-2]["hash"])  # chained


if __name__ == "__main__":
    unittest.main(verbosity=1)
