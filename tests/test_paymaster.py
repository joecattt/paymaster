import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from paymaster import budgets as B, pricing as P, report as R
from paymaster.adapters import airoute, x402
from paymaster.ledger import Ledger, verify_anchors
from paymaster.schema import record, can_transition, STATES, TRANSITIONS

# Verbatim example from vendor/x402-specification-v2.md §5.2.1 / §5.3.1
SPEC_PP = {
    "x402Version": 2,
    "resource": {"url": "https://api.example.com/premium-data",
                 "description": "Access to premium market data",
                 "mimeType": "application/json"},
    "accepted": {"scheme": "exact", "network": "eip155:84532", "amount": "10000",
                 "asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
                 "payTo": "0x209693Bc6afc0C5328bA36FaF03C514EF312287C",
                 "maxTimeoutSeconds": 60, "extra": {"name": "USDC", "version": "2"}},
    "payload": {"signature": "0xdead",
                "authorization": {"from": "0x857b06519E91e3A54538791bDbb0E22373e36b66",
                                  "to": "0x209693Bc6afc0C5328bA36FaF03C514EF312287C",
                                  "value": "10000", "validAfter": "1740672089",
                                  "validBefore": "1740672154", "nonce": "0xf374"}},
    "extensions": {},
}
SPEC_SR = {"success": True,
           "transaction": "0x1234567890abcdef", "network": "eip155:84532",
           "payer": "0x857b06519E91e3A54538791bDbb0E22373e36b66"}


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.led = Ledger(os.path.join(self.dir, "l.jsonl"))

    def _rec(self, n=0):
        return record(ts=f"2026-08-22T0{n}:00:00+00:00", rail="api-billing",
                      provider="groq", principal="test", tokens_in=100, tokens_out=10,
                      state="DELIVERED", attribution="asserted")

    def test_append_verify(self):
        for n in range(3):
            self.led.append(self._rec(n))
        ok, msg = self.led.verify()
        self.assertTrue(ok, msg)
        self.assertIn("3 records", msg)

    def test_tamper_detected(self):
        for n in range(3):
            self.led.append(self._rec(n))
        lines = open(self.led.path).read().splitlines()
        row = json.loads(lines[1])
        row["rec"]["tokens_in"] = 999999   # cook the books
        lines[1] = json.dumps(row, sort_keys=True, separators=(",", ":"))
        open(self.led.path, "w").write("\n".join(lines) + "\n")
        ok, msg = self.led.verify()
        self.assertFalse(ok)
        self.assertIn("tampered", msg)

    def test_deletion_detected(self):
        for n in range(3):
            self.led.append(self._rec(n))
        lines = open(self.led.path).read().splitlines()
        open(self.led.path, "w").write("\n".join([lines[0], lines[2]]) + "\n")
        ok, msg = self.led.verify()
        self.assertFalse(ok)


class TestX402(unittest.TestCase):
    def test_spec_example_parses(self):
        rec = x402.parse(SPEC_PP, SPEC_SR, principal="research-agent")
        self.assertEqual(rec["rail"], "x402")
        self.assertEqual(rec["state"], "PAID")             # paid != delivered
        self.assertEqual(rec["attribution"], "signed")
        self.assertEqual(rec["principal_id"],
                         SPEC_PP["payload"]["authorization"]["from"])
        self.assertEqual(rec["usd"], 0.01)          # 10000 atomic USDC = $0.01
        self.assertEqual(rec["currency"], "USDC")
        self.assertTrue(rec["ok"])
        self.assertIn("0x1234567890abcdef", rec["evidence"])

    def test_failed_settlement_not_ok(self):
        sr = dict(SPEC_SR, success=False, transaction="",
                  errorReason="insufficient_funds")
        rec = x402.parse(SPEC_PP, sr)
        self.assertEqual(rec["state"], "FAILED")
        srp = dict(SPEC_SR, success=False, transaction="0xabc",
                   errorReason="settlement_pending")
        self.assertEqual(x402.parse(SPEC_PP, srp)["state"], "PAYMENT_PENDING")

    def test_wrong_version_rejected(self):
        with self.assertRaises(ValueError):
            x402.parse(dict(SPEC_PP, x402Version=1), SPEC_SR)

    def test_signed_value_wins_over_settle_amount(self):
        # SettleResponse.amount is server-asserted; spend binds to the signed
        # authorization.value and the discrepancy is recorded (Ox review #3).
        rec = x402.parse(SPEC_PP, dict(SPEC_SR, amount="5000"))
        self.assertEqual(rec["usd"], 0.01)
        self.assertIn("settle_amount=5000", rec["evidence"])

    def test_sponsored_payer_rejected_by_default(self):
        sr = dict(SPEC_SR, payer="0x000000000000000000000000000000000000dEaD")
        with self.assertRaises(ValueError):
            x402.parse(SPEC_PP, sr)
        rec = x402.parse(SPEC_PP, sr, allow_sponsored=True)
        self.assertIn("sponsored_payer", rec["evidence"])


class TestBudgets(unittest.TestCase):
    TABLE = {"groq": {"usd_per_mtok_in": 0, "usd_per_mtok_out": 0}}

    def test_breach_and_orphan(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%dT10:00:00+00:00")
        recs = [record(ts=today, rail="api-billing", provider="groq",
                       principal="looper", tokens_in=600000, tokens_out=0, rid=f"r{i}",
                       state="DELIVERED", attribution="asserted")
                for i in range(3)]
        recs.append(record(ts=today, rail="api-billing", provider="groq",
                           principal="mystery", tokens_in=5, tokens_out=5, rid="orphan1",
                           state="DELIVERED", attribution="asserted"))
        budgets = [{"id": "po-loop", "scope": {"principal": "looper"},
                    "window": "day", "limit_tokens": 1000000}]
        findings, _ = B.evaluate(recs, budgets, self.TABLE, now=now)
        kinds = {f["kind"] for f in findings}
        self.assertIn("BREACH", kinds)
        self.assertIn("ORPHAN", kinds)

    def test_past_window_breach_still_fires(self):
        # Late-arriving spend must not slip a day budget (Ox review #1).
        recs = [record(ts="2020-01-01T10:00:00+00:00", rail="api-billing",
                       provider="groq", principal="looper", tokens_in=9999999,
                       state="DELIVERED", attribution="asserted")]
        budgets = [{"id": "po-loop", "scope": {"principal": "looper"},
                    "window": "day", "limit_tokens": 10}]
        findings, _ = B.evaluate(recs, budgets, self.TABLE)
        breaches = [f for f in findings if f["kind"] == "BREACH"]
        self.assertTrue(breaches)
        self.assertIn("2020-01-01", breaches[0]["detail"])

    def test_unpriceable_fails_closed(self):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        recs = [record(ts=now.isoformat(), rail="api-billing",
                       provider="unlisted-provider", principal="looper", tokens_in=10,
                       state="DELIVERED", attribution="asserted")]
        budgets = [{"id": "po-usd", "scope": {"principal": "looper"},
                    "window": "day", "limit_usd": 1.0}]
        findings, _ = B.evaluate(recs, budgets, self.TABLE, now=now)
        self.assertIn("UNPRICEABLE", {f["kind"] for f in findings})


class TestAiroute(unittest.TestCase):
    def test_anchor_detects_genesis_rewrite(self):
        # A full-file rewrite from genesis passes verify(); the anchor,
        # witnessed in a different trust domain, catches it.
        d = tempfile.mkdtemp()
        led = Ledger(os.path.join(d, "l.jsonl"))
        for n in range(3):
            led.append(self._rec_static(n))
        seq, h = led._tail()
        anchors = os.path.join(d, "anchors.jsonl")
        open(anchors, "w").write(json.dumps({"seq": seq, "hash": h}) + "\n")
        ok, _ = verify_anchors(led, anchors)
        self.assertTrue(ok)
        # adversary rewrites the whole chain from genesis, dropping a record
        os.remove(led.path)
        led2 = Ledger(led.path)
        for n in range(2):
            led2.append(self._rec_static(n))
        ok, msg = led2.verify()
        self.assertTrue(ok)  # chain is self-consistent — the blind spot
        ok, msg = verify_anchors(led2, anchors)
        self.assertFalse(ok)  # the witness is not fooled
        self.assertIn("rewritten", msg)

    def _rec_static(self, n):
        return record(ts=f"2026-08-21T0{n}:00:00+00:00", rail="api-billing",
                      provider="groq", principal="t", tokens_in=n, state="DELIVERED",
                      attribution="asserted", rid=f"static{n}")


class TestStateMachine(unittest.TestCase):
    def test_states_closed_under_transitions(self):
        for a, outs in TRANSITIONS.items():
            self.assertIn(a, STATES)
            for b in outs:
                self.assertIn(b, STATES)

    def test_economic_facts_are_separate(self):
        # payment is not delivery; delivery is not verification
        self.assertTrue(can_transition("PAID", "DELIVERED"))
        self.assertTrue(can_transition("DELIVERED", "VERIFIED"))
        self.assertFalse(can_transition("PAID", "VERIFIED"))
        self.assertFalse(can_transition("RECONCILED", "PAID"))
        self.assertTrue(can_transition("RECONCILED", "DISPUTED"))

    def test_bad_state_rejected(self):
        with self.assertRaises(ValueError):
            record(ts="2026-08-22T00:00:00+00:00", rail="api-billing",
                   provider="groq", principal="t", state="MAYBE",
                   attribution="asserted")


class TestTimezone(unittest.TestCase):
    def test_cdt_evening_stays_in_operator_day(self):
        # 2026-08-22 19:00 CDT = 2026-08-23 00:00 UTC. In UTC windows this
        # lands "tomorrow"; in the operator's timezone it is still today.
        from paymaster.budgets import _win_key
        ts = "2026-08-23T00:00:00+00:00"
        self.assertEqual(_win_key(ts, "day", "UTC"), "2026-08-23")
        self.assertEqual(_win_key(ts, "day", "America/Chicago"), "2026-08-22")


class TestAiroute(unittest.TestCase):
    def test_fetch_idempotent_shape(self):
        d = tempfile.mkdtemp()
        db = os.path.join(d, "r.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE events (ts TEXT, caller TEXT, task_class TEXT,"
                    " provider TEXT, model TEXT, ok INTEGER, latency_ms INTEGER,"
                    " tokens_in INTEGER, tokens_out INTEGER, fallback_rank INTEGER,"
                    " grounding TEXT, error TEXT)")
        con.execute("INSERT INTO events VALUES ('2026-08-22T11:00:00+00:00','doc-context',"
                    "'','groq','gpt-oss',1,100,1000,50,0,'','')")
        con.commit(); con.close()
        rows = list(airoute.fetch(0, db_path=db))
        self.assertEqual(len(rows), 1)
        rowid, rec = rows[0]
        self.assertEqual(rec["principal"], "doc-context")
        self.assertEqual(rec["attribution"], "asserted")   # honest weak tier
        self.assertEqual(rec["state"], "DELIVERED")        # asserted, not verified
        self.assertIsNone(rec["usd"])          # adapter never prices
        self.assertEqual(list(airoute.fetch(rowid, db_path=db)), [])  # cursor works


if __name__ == "__main__":
    unittest.main(verbosity=1)
