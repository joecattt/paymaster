import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from paymaster.adapters import litellm
from paymaster import coverage as C

# A realistic LiteLLM_SpendLogs row (fields verbatim from schema.prisma)
ROW = {
    "request_id": "req-abc123", "call_type": "acompletion",
    "api_key": "sk-hash-9f", "spend": 0.0021,
    "total_tokens": 63, "prompt_tokens": 41, "completion_tokens": 22,
    "startTime": "2026-08-23T06:12:44Z", "endTime": "2026-08-23T06:12:45Z",
    "model": "gpt-4o-mini", "custom_llm_provider": "openai",
    "user": "u-1", "team_id": "t-1", "agent_id": "agent-7",
    "cache_hit": "False", "status": "success",
}

class LiteLLMAdapter(unittest.TestCase):
    def test_maps_core_fields(self):
        r = litellm.from_spendlog(ROW)
        self.assertEqual(r["principal"], "agent-7")     # agent_id wins -> per-agent attribution
        self.assertEqual(r["provider"], "openai")
        self.assertEqual(r["usd"], 0.0021)
        self.assertEqual(r["tokens_in"], 41)
        self.assertEqual(r["state"], "DELIVERED")
        self.assertEqual(r["attribution"], "asserted")  # hashed key != signature
        self.assertIn("req-abc123", r["evidence"])

    def test_failure_state(self):
        r = litellm.from_spendlog(dict(ROW, status="failure"))
        self.assertEqual(r["state"], "FAILED")

    def test_cache_hit_flagged(self):
        r = litellm.from_spendlog(dict(ROW, cache_hit="True"))
        self.assertIn("cache_hit", r["evidence"])

    def test_idempotent_fetch(self):
        recs = list(litellm.fetch([ROW]))
        self.assertEqual(len(recs), 1)
        self.assertEqual(list(litellm.fetch([ROW], seen_ids={recs[0]["id"]})), [])

    def test_falls_back_to_api_key(self):
        r = litellm.from_spendlog(dict(ROW, agent_id=None))
        self.assertEqual(r["principal"], "sk-hash-9f")


class PerKeyCoverage(unittest.TestCase):
    def test_localizes_unaccounted_to_a_key(self):
        # agent-7 fully accounted; agent-9 has $3 the ledger never saw
        known = {"agent-7": 5.0, "agent-9": 2.0}
        agg   = {"agent-7": 5.0, "agent-9": 5.0}
        r = C.assess_per_key(known, agg)
        self.assertFalse(r["clean"])
        self.assertEqual(r["keys_with_unaccounted_spend"], ["agent-9"])
        self.assertEqual(r["per_key"]["agent-7"]["verdict"], C.COVERED)
        self.assertEqual(r["per_key"]["agent-9"]["verdict"], C.UNACCOUNTED)

    def test_clean_when_all_match(self):
        r = C.assess_per_key({"a": 1.0}, {"a": 1.0})
        self.assertTrue(r["clean"])

if __name__ == "__main__":
    unittest.main(verbosity=1)
