import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from paymaster.reconcile_external import (reconcile, MATCH, MISMATCH,
    UNKNOWN_PROVIDER, UNSETTLED, NO_ACTION)

class ReconcileExternal(unittest.TestCase):
    def test_full_match(self):
        r = reconcile(0.0012, 0.0012, 0.0012, authorized=True, response_received=True)
        self.assertEqual(r["verdict"], MATCH); self.assertTrue(r["spent_known"])

    def test_provider_disagrees_and_wins(self):
        r = reconcile(0.0010, 0.0013, authorized=True, response_received=True)
        self.assertEqual(r["verdict"], MISMATCH); self.assertEqual(r["amount"], 0.0013)

    def test_lost_response_is_unknown_not_zero(self):
        # THE crux: dispatched, response lost, provider silent.
        r = reconcile(None, None, authorized=True, response_received=False)
        self.assertEqual(r["verdict"], UNKNOWN_PROVIDER)
        self.assertFalse(r["spent_known"])        # system must NOT claim no-spend
        self.assertIsNone(r["amount"])

    def test_local_only_is_unverified(self):
        r = reconcile(0.002, None, authorized=True, response_received=True)
        self.assertEqual(r["verdict"], UNKNOWN_PROVIDER)
        self.assertFalse(r["spent_known"])

    def test_reported_but_unsettled(self):
        r = reconcile(0.002, 0.002, authorized=True, response_received=True)
        self.assertEqual(r["verdict"], UNSETTLED); self.assertFalse(r["spent_known"])

    def test_nothing_happened(self):
        r = reconcile(None, None, authorized=False, response_received=False)
        self.assertEqual(r["verdict"], NO_ACTION)

if __name__ == "__main__":
    unittest.main(verbosity=1)


class AdversarialRealMoney(unittest.TestCase):
    """Proven against the real recorded charge ($0.00000315, 2026-08-23).
    A reconciler that only ever says MATCH is worthless — prove it discriminates."""
    REAL = 0.00000315
    def _tol(self, pc): return max(1e-7, 0.20 * pc)

    def test_stale_price_is_mismatch(self):
        r = reconcile(self.REAL * 2.5, self.REAL, self.REAL, authorized=True,
                      response_received=True, tol=self._tol(self.REAL))
        self.assertEqual(r["verdict"], MISMATCH)
        self.assertEqual(r["amount"], self.REAL)   # provider authoritative for the charge

    def test_rounding_within_tolerance_is_match(self):
        r = reconcile(self.REAL * 1.1, self.REAL, self.REAL, authorized=True,
                      response_received=True, tol=self._tol(self.REAL))
        self.assertEqual(r["verdict"], MATCH)

    def test_provider_missing_stays_unknown(self):
        r = reconcile(self.REAL, None, authorized=True, response_received=True)
        self.assertEqual(r["verdict"], UNKNOWN_PROVIDER)
        self.assertFalse(r["spent_known"])

    def test_provider_zero_vs_real_charge_is_mismatch(self):
        r = reconcile(self.REAL, 0.0, 0.0, authorized=True, response_received=True,
                      tol=self._tol(self.REAL))
        self.assertEqual(r["verdict"], MISMATCH)
