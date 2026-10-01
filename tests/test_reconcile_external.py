import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import tempfile
from datetime import datetime, timezone, timedelta
from paymaster import principal, capability as C
from paymaster.reconcile_external import (reconcile, MATCH, MISMATCH,
    UNKNOWN_PROVIDER, UNSETTLED, NO_ACTION, UNAUTHORIZED_SPEND)


class _WithCapability(unittest.TestCase):
    """PM-003: reconcile derives authorization from a capability chain, so the
    tests that exercise provider/settlement logic supply a currently-valid one."""
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        principal.KEYDIR = os.path.join(tmp, "keys"); C.REVOKED_DB = os.path.join(tmp, "revoked.jsonl")
        for p in ("company", "agent"): principal.enroll(p)
        exp = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
        cls.root = C.issue("company", "agent", scope={"provider": "openrouter"}, expires=exp,
                           max_usd=1.0, allow_delegate=True)
        cls.chain = [cls.root]


class ReconcileExternal(_WithCapability):
    def test_full_match(self):
        r = reconcile(0.0012, 0.0012, 0.0012, capability_chain=self.chain, authorized=True, response_received=True)
        self.assertEqual(r["verdict"], MATCH); self.assertTrue(r["spent_known"])

    def test_provider_disagrees_and_wins(self):
        r = reconcile(0.0010, 0.0013, capability_chain=self.chain, authorized=True, response_received=True)
        self.assertEqual(r["verdict"], MISMATCH); self.assertEqual(r["amount"], 0.0013)

    def test_lost_response_is_unknown_not_zero(self):
        # THE crux: dispatched, response lost, provider silent.
        r = reconcile(None, None, capability_chain=self.chain, authorized=True, response_received=False)
        self.assertEqual(r["verdict"], UNKNOWN_PROVIDER)
        self.assertFalse(r["spent_known"])        # system must NOT claim no-spend
        self.assertIsNone(r["amount"])

    def test_local_only_is_unverified(self):
        r = reconcile(0.002, None, capability_chain=self.chain, authorized=True, response_received=True)
        self.assertEqual(r["verdict"], UNKNOWN_PROVIDER)
        self.assertFalse(r["spent_known"])

    def test_reported_but_unsettled(self):
        r = reconcile(0.002, 0.002, capability_chain=self.chain, authorized=True, response_received=True)
        self.assertEqual(r["verdict"], UNSETTLED); self.assertFalse(r["spent_known"])

    def test_nothing_happened(self):
        r = reconcile(None, None, authorized=False, response_received=False)
        self.assertEqual(r["verdict"], NO_ACTION)


class AuthorizationDerived(_WithCapability):
    """PM-003: authorization comes from the capability chain, never the caller's flag."""
    def _spend(self, **kw):
        return reconcile(0.002, 0.002, 0.002, authorized=True, response_received=True, **kw)

    def test_caller_flag_cannot_authorize_spend(self):
        for chain in (None, [], "not-a-chain", [{"x": 1}], [dict(self.root, max_usd=999.0)]):
            r = self._spend(capability_chain=chain)
            self.assertEqual(r["verdict"], UNAUTHORIZED_SPEND, repr(chain))

    def test_flag_false_does_not_launder_spend(self):     # the original repro
        r = reconcile(5.0, 5.0, 5.0, authorized=False, response_received=True)
        self.assertEqual(r["verdict"], UNAUTHORIZED_SPEND)
        r = reconcile(None, 5.0, authorized=False, response_received=True)   # provider-only charge
        self.assertEqual(r["verdict"], UNAUTHORIZED_SPEND)
        self.assertEqual(r["amount"], 5.0); self.assertTrue(r["spent_known"])

    def test_valid_chain_is_authorized(self):
        self.assertEqual(self._spend(capability_chain=self.chain)["verdict"], MATCH)

    def test_revoked_capability_makes_spend_unauthorized(self):
        root = C.issue("company", "agent", scope={}, expires=(datetime.now(timezone.utc)
                       + timedelta(hours=1)).isoformat(timespec="seconds"))
        self.assertEqual(self._spend(capability_chain=[root])["verdict"], MATCH)
        C.revoke(root["id"], "pm-003 test")
        self.assertEqual(self._spend(capability_chain=[root])["verdict"], UNAUTHORIZED_SPEND)

    def test_expired_capability_makes_spend_unauthorized(self):
        old = C.issue("company", "agent", scope={}, expires=(datetime.now(timezone.utc)
                      - timedelta(seconds=5)).isoformat(timespec="seconds"))
        self.assertEqual(self._spend(capability_chain=[old])["verdict"], UNAUTHORIZED_SPEND)

    def test_headless_chain_cannot_authorize(self):       # composes with PM-001
        child = C.delegate(self.root, "agent", "agent")
        self.assertEqual(self._spend(capability_chain=[child])["verdict"], UNAUTHORIZED_SPEND)

    def test_dispatch_without_authority_is_unauthorized_and_unknown(self):
        r = reconcile(None, None, authorized=True, response_received=False)
        self.assertEqual(r["verdict"], UNAUTHORIZED_SPEND); self.assertFalse(r["spent_known"])

    def test_nothing_recorded_stays_no_action(self):
        r = reconcile(None, None, authorized=False, response_received=False)
        self.assertEqual(r["verdict"], NO_ACTION)


if __name__ == "__main__":
    unittest.main(verbosity=1)


class AdversarialRealMoney(_WithCapability):
    """Proven against the real recorded charge ($0.00000315, 2026-08-23).
    A reconciler that only ever says MATCH is worthless — prove it discriminates."""
    REAL = 0.00000315
    def _tol(self, pc): return max(1e-7, 0.20 * pc)

    def test_stale_price_is_mismatch(self):
        r = reconcile(self.REAL * 2.5, self.REAL, self.REAL, capability_chain=self.chain, authorized=True,
                      response_received=True, tol=self._tol(self.REAL))
        self.assertEqual(r["verdict"], MISMATCH)
        self.assertEqual(r["amount"], self.REAL)   # provider authoritative for the charge

    def test_rounding_within_tolerance_is_match(self):
        r = reconcile(self.REAL * 1.1, self.REAL, self.REAL, capability_chain=self.chain, authorized=True,
                      response_received=True, tol=self._tol(self.REAL))
        self.assertEqual(r["verdict"], MATCH)

    def test_provider_missing_stays_unknown(self):
        r = reconcile(self.REAL, None, capability_chain=self.chain, authorized=True, response_received=True)
        self.assertEqual(r["verdict"], UNKNOWN_PROVIDER)
        self.assertFalse(r["spent_known"])

    def test_provider_zero_vs_real_charge_is_mismatch(self):
        r = reconcile(self.REAL, 0.0, 0.0, capability_chain=self.chain, authorized=True, response_received=True,
                      tol=self._tol(self.REAL))
        self.assertEqual(r["verdict"], MISMATCH)
