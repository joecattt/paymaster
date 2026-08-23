import os, sys, json, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from paymaster import counters as C, budgets as B
from paymaster.gate import Snapshot
from paymaster.ledger import Ledger
from paymaster.schema import record

BUD = [{"id": "po-a", "scope": {"principal": "alice"}, "window": "day", "limit_calls": 100},
       {"id": "po-prov", "scope": {"provider": "groq"}, "window": "month", "limit_tokens": 10_000}]

def mkledger(path, recs):
    led = Ledger(path)
    led.append_batch(recs)
    return led

def rec(ts, principal, provider, tin=0, tout=0, i=0):
    return record(ts=ts, rail="api-billing", provider=provider, principal=principal,
                  state="DELIVERED", attribution="asserted", tokens_in=tin, tokens_out=tout,
                  rid=f"{principal}-{provider}-{ts}-{i}")

class DifferentialEquivalence(unittest.TestCase):
    """THE gate: counter-store decision == full-ledger decision, always."""
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.lp = os.path.join(self.d, "l.jsonl")
        self.sp = os.path.join(self.d, "c.json")

    def _assert_equiv(self, recs, probes, tz="UTC"):
        mkledger(self.lp, recs)
        truth = C.rebuild(BUD, tz, self.lp)
        fast, prov = C.load_fast(BUD, tz, self.lp, self.sp)
        for pr in probes:
            dt = truth.decide(**pr)
            df = fast.decide(**pr)
            self.assertEqual((dt["decision"], dt["reason_code"], dt["budget"]),
                             (df["decision"], df["reason_code"], df["budget"]),
                             f"DIVERGENCE on {pr}: ledger={dt['decision']}/{dt['reason_code']} counter={df['decision']}/{df['reason_code']} (prov={prov})")
        return prov

    def test_replay_equivalence(self):
        recs = [rec(f"2026-08-14T10:00:{i%60:02d}+00:00", "alice", "groq", 50, 10, i) for i in range(120)]
        probes = [{"principal": "alice", "provider": "groq"},
                  {"principal": "stranger", "provider": "groq"},
                  {"principal": "alice", "provider": "mistral", "tokens": 5000}]
        self._assert_equiv(recs, probes)

    def test_boundary_at_limit(self):
        recs = [rec(f"2026-08-14T10:{i//60:02d}:{i%60:02d}+00:00", "alice", "x", i=i) for i in range(100)]
        # exactly at limit_calls=100; next call is the boundary
        self._assert_equiv(recs, [{"principal": "alice", "provider": "x"}])

    def test_dst_boundary(self):
        recs = [rec("2026-11-01T06:30:00+00:00", "alice", "g", i=1),
                rec("2026-11-01T07:30:00+00:00", "alice", "g", i=2)]
        self._assert_equiv(recs, [{"principal": "alice", "provider": "g"}], tz="America/Chicago")

    def test_delta_after_cache(self):
        recs = [rec(f"2026-08-14T10:00:{i:02d}+00:00", "alice", "groq", i=i) for i in range(30)]
        mkledger(self.lp, recs)
        C.load_fast(BUD, "UTC", self.lp, self.sp)          # warm the cache
        Ledger(self.lp).append_batch([rec(f"2026-08-14T11:00:{i:02d}+00:00", "alice", "groq", i=100+i) for i in range(30)])
        truth = C.rebuild(BUD, "UTC", self.lp)
        fast, prov = C.load_fast(BUD, "UTC", self.lp, self.sp)
        self.assertEqual(prov, "delta")
        self.assertEqual(truth.usage, fast.usage)          # delta applied == full rebuild

    def test_policy_change_forces_rebuild(self):
        recs = [rec(f"2026-08-14T10:00:{i:02d}+00:00", "alice", "groq", i=i) for i in range(10)]
        mkledger(self.lp, recs)
        C.load_fast(BUD, "UTC", self.lp, self.sp)
        BUD2 = BUD + [{"id": "po-new", "scope": {"principal": "bob"}, "window": "day", "limit_calls": 5}]
        _, prov = C.load_fast(BUD2, "UTC", self.lp, self.sp)
        self.assertEqual(prov, "policy-changed-rebuild")

    def test_ledger_shrink_forces_rebuild(self):
        recs = [rec(f"2026-08-14T10:00:{i:02d}+00:00", "alice", "groq", i=i) for i in range(20)]
        mkledger(self.lp, recs)
        C.load_fast(BUD, "UTC", self.lp, self.sp)
        # rewrite ledger shorter (rollback / genesis-rewrite)
        os.remove(self.lp)
        mkledger(self.lp, recs[:5])
        _, prov = C.load_fast(BUD, "UTC", self.lp, self.sp)
        self.assertIn(prov, ("ledger-shrank-rebuild", "cold-rebuild"))

    def test_reconcile_detects_corrupt_cache(self):
        recs = [rec(f"2026-08-14T10:00:{i:02d}+00:00", "alice", "groq", i=i) for i in range(40)]
        mkledger(self.lp, recs)
        C.load_fast(BUD, "UTC", self.lp, self.sp)
        # corrupt the cache: inflate alice's counter
        d = json.load(open(self.sp))
        k = [x for x in d["usage"] if "po-a" in x][0]
        d["usage"][k]["calls"] = 999999
        json.dump(d, open(self.sp, "w"))
        ok, msg = C.reconcile(BUD, "UTC", self.lp, self.sp)
        self.assertFalse(ok)
        self.assertIn("MISMATCH", msg)
        ok2, _ = C.reconcile(BUD, "UTC", self.lp, self.sp)  # cache overwritten -> now clean
        self.assertTrue(ok2)

if __name__ == "__main__":
    unittest.main(verbosity=1)


class Invariants(unittest.TestCase):
    def test_enforced_invariants_present(self):
        from paymaster import invariants as I
        ids = {i[0] for i in I.enforced()}
        self.assertTrue({"I1","I2","I3","I4","I5"} <= ids)

    def test_nonneg_holds_on_real_shape(self):
        from paymaster import invariants as I
        from paymaster.gate import Snapshot
        snap = Snapshot([{"id":"p","scope":{"principal":"a"},"window":"day","limit_calls":9}], "UTC").build([])
        snap.advance("a","g",5,3,"2026-08-14T10:00:00+00:00")
        self.assertTrue(I.check_nonneg(snap))
