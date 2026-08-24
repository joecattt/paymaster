import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from paymaster import receipt as R
from paymaster.schema import record

REC = record(ts="2026-08-23T09:38:02+00:00", rail="api-billing", provider="openrouter",
              principal="prove-nonzero", state="RECONCILED", attribution="asserted",
              model="openai/gpt-4o-mini", tokens_in=13, tokens_out=2, usd=0.00000315,
              evidence="gen=gen-TEST123;reconciled=MATCH;local_est=0.00000315", rid="t"*64)
DEC = [{"principal_id":"prove-nonzero","provider":"openrouter","decision":"DENY",
        "reason_code":"ORPHAN_NO_BUDGET","policy_hash":"85010f7c926045cb",
        "ts":"2026-08-23T09:37:00+00:00"}]

class DecisionReceipt(unittest.TestCase):
    def test_deterministic(self):
        a = R.build(REC, seq=1, decisions=DEC)
        b = R.build(REC, seq=1, decisions=DEC)
        self.assertEqual(a["receipt_id"], b["receipt_id"])

    def test_telemetry_change_changes_receipt(self):
        a = R.build(REC, seq=1, decisions=DEC)
        mutated = dict(REC, tokens_in=999)
        b = R.build(mutated, seq=1, decisions=DEC)
        self.assertNotEqual(a["receipt_id"], b["receipt_id"])

    def test_weakest_grade_rule(self):
        r = R.build(REC, seq=1, decisions=DEC)
        # decision link is temporal -> derived; overall grade must be 'derived',
        # NOT 'reconciled', even though reconciliation is present
        self.assertEqual(r["evidence_grade"], "derived")

    def test_gaps_are_explicit_not_guessed(self):
        r = R.build(REC, seq=1, decisions=())  # no decision available
        self.assertTrue(any("no gate decision" in g for g in r["gaps"]))
        self.assertTrue(any("no consideration chain" in g for g in r["gaps"]))
        self.assertEqual(r.get("authority"), {})     # absent, not fabricated

    def test_no_reconciliation_is_a_gap_and_asserted_amount(self):
        rec = record(ts="2026-08-23T10:00:00+00:00", rail="api-billing", provider="groq",
                     principal="x", state="DELIVERED", attribution="asserted",
                     usd=0.5, evidence="", rid="u"*64)
        r = R.build(rec)
        self.assertEqual(r["economics"]["amount_usd"]["grade"], "asserted")
        self.assertTrue(any("no external reconciliation" in g for g in r["gaps"]))

    def test_cannot_silently_strengthen(self):
        # grades are computed from linkage kind; passing a decision does not
        # let authority claim better than 'derived'
        r = R.build(REC, seq=1, decisions=DEC)
        self.assertEqual(r["authority"]["policy_hash"]["grade"], "derived")

    def test_render_answers_the_question(self):
        out = R.render(R.build(REC, seq=1, decisions=DEC))
        for word in ("WHO", "WHAT", "AUTHORITY", "COST", "RECONCILE", "GRADE", "GAPS"):
            self.assertIn(word, out)

if __name__ == "__main__":
    unittest.main(verbosity=1)
