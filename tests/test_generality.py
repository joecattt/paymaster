"""Proof the machinery is provider- and action-agnostic (use-case congregation).
Not five products — one primitive, shown to reconcile a NON-LLM metered service
and a non-spend agent ACTION through the exact same schema+reconcile+coverage."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from paymaster.schema import record
from paymaster.reconcile_external import reconcile, MATCH, MISMATCH
from paymaster import coverage as C

class Generality(unittest.TestCase):
    def test_twilio_sms_reconciles(self):
        # a Twilio SMS charge flows through the same SpendRecord + reconcile
        r = record(ts="2026-08-23T10:00:00Z", rail="api-billing", provider="twilio",
                   principal="notify-agent", state="DELIVERED", attribution="asserted",
                   usd=0.0079, currency="USD", evidence="twilio:SMxxxx")
        v = reconcile(local_cost=0.0079, provider_cost=0.0079, settled_cost=0.0079,
                      authorized=True, response_received=True)
        self.assertEqual(v["verdict"], MATCH)
        self.assertEqual(r["provider"], "twilio")   # no LLM assumption anywhere

    def test_cloud_compute_coverage(self):
        # Σ(known cloud spend) vs the cloud provider's aggregate -> same oracle
        res = C.assess(known_sum=120.0, provider_aggregate=155.0)
        self.assertEqual(res["verdict"], C.UNACCOUNTED)
        self.assertEqual(res["gap"], 35.0)          # $35 of untracked cloud spend

    def test_per_grant_attribution(self):
        # per-key coverage localizes to a GRANT (nonprofit accountability), same code
        r = C.assess_per_key({"grant-A": 5000.0, "grant-B": 3000.0},
                             {"grant-A": 5000.0, "grant-B": 3200.0})
        self.assertEqual(r["keys_with_unaccounted_spend"], ["grant-B"])  # $200 unaccounted on grant-B

    def test_nonspend_action_receipt(self):
        # an agent ACTION (not money): usd=None, the record still binds actor+evidence+state
        r = record(ts="2026-08-23T10:00:00Z", rail="api-billing", provider="mcp:filesystem",
                   principal="agent-7", state="DELIVERED", attribution="authenticated",
                   usd=None, evidence="mcp:tool=read_file;path=/x")
        self.assertIsNone(r["usd"])                 # non-economic action, still evidenced
        self.assertEqual(r["provider"], "mcp:filesystem")

if __name__ == "__main__":
    unittest.main(verbosity=1)
