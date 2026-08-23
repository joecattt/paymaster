import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from paymaster.coverage import assess, COVERED, UNACCOUNTED, OVERCOUNTED, NO_AGGREGATE

class Coverage(unittest.TestCase):
    def test_clean_coverage(self):
        self.assertEqual(assess(1.2345, 1.2345)["verdict"], COVERED)

    def test_bypass_detected(self):
        # ledger knows $8.00; provider says $16.00 -> $8 of bypass spend exists
        r = assess(8.0, 16.0)
        self.assertEqual(r["verdict"], UNACCOUNTED)
        self.assertEqual(r["gap"], 8.0)
        self.assertTrue(r["coverage_known"])

    def test_overcount_flagged(self):
        r = assess(10.0, 9.0)
        self.assertEqual(r["verdict"], OVERCOUNTED)

    def test_no_aggregate_is_honest(self):
        r = assess(5.0, None)
        self.assertEqual(r["verdict"], NO_AGGREGATE)
        self.assertFalse(r["coverage_known"])   # must NOT imply coverage

if __name__ == "__main__":
    unittest.main(verbosity=1)
