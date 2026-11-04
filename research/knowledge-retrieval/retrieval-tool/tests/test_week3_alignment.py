"""The tool path must return exactly what Week 3 returns (replay of Week 3's own saved facets_6 reports)."""

import json
import unittest

from _setup import ctx, index_root
from retrieval_tool import RetrievalOptions, build_service
from retrieval_tool.tool_schema import build_request

ROOT = index_root()
REPLAY = ROOT / "artifacts/evaluations/refinement_runs/facets_6.jsonl" if ROOT else None


@unittest.skipIf(ROOT is None or not REPLAY.exists(), "Week 3 package / saved runs not found")
class Week3AlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = [json.loads(l) for l in (ROOT / "data/benchmark/benchmark_50.jsonl").read_text().splitlines() if l.strip()]
        cls.recorded = {json.loads(l)["id"]: json.loads(l)["report"] for l in REPLAY.read_text().splitlines() if l.strip()}

    def run_all(self, options=RetrievalOptions.week3_parity()):
        service = build_service("replay", root=ROOT, options=options, replay_file=REPLAY)
        out = {}
        for case in self.cases:
            args = {"query": case["question"], "purpose": "answer_grounding",
                    "evidence_needs": [{"need_type": "method_guidance", "description": case["question"][:200]}]}
            record = service.handle(build_request(args, ctx(course_id=case["course_id"], turn_id=case["id"],
                                                            retrieval_snapshot_id=f"snap.{case['course_id']}.dev-ai-breakdown.1"), top_k=6))
            out[case["id"]] = record
        return service, out

    def test_same_passages_same_order_as_week3(self):
        _, out = self.run_all()
        for cid, report in self.recorded.items():
            week3_ids = [r["passage_id"] for r in report["results"]]
            tool_ids = [p["legacy_locator"]["week3_passage_id"] for p in out[cid].get("passages", [])]
            self.assertEqual(tool_ids, week3_ids, cid)

    def test_week3_statuses_map_to_v1(self):
        _, out = self.run_all()
        for cid, report in self.recorded.items():
            record = out[cid]
            if report["status"] == "found":
                self.assertIn(record["retrieval_status"], ("supported", "partial"), cid)
            elif report["status"] == "needs_clarification":
                self.assertEqual(record["stop_reason"], "needs_clarification", cid)
            else:
                self.assertEqual(record["retrieval_status"], "no_support_found", cid)

    def test_defaults_are_the_week3_baseline(self):
        service, _ = self.run_all()
        self.assertTrue(service.options.describe()["week3_parity"])
        self.assertTrue(RetrievalOptions().describe()["week3_retrieval"])    # production default: same retrieval
        call = service.backend.calls[0]
        policy = service.policies["calc1"]
        self.assertEqual((call["top_k"], call["context_chars"], call["max_per_document"], call["document_limit_mode"],
                          call["candidate_limit"]), (6, 12000, 4, "soft", 40))
        self.assertEqual((policy.default_top_k, policy.max_passage_chars), (6, 12000))

    def test_default_facets_are_week3_query_facets(self):
        service, _ = self.run_all()
        q18 = next(c for c in service.backend.calls if c["question"].startswith("Compare the discrete logistic"))
        self.assertEqual(q18["facets"], service.backend.query_facets(q18["question"]))

    def test_evidence_gate_switch_keeps_46(self):
        _, out = self.run_all(RetrievalOptions())
        found = [cid for cid, r in self.recorded.items() if r["status"] == "found"]
        self.assertTrue(all(out[cid].get("passages") for cid in found))

    def test_memory_stand_in_needs_explicit_test_flag(self):
        with self.assertRaises(ValueError):
            build_service("memory", root=ROOT)


if __name__ == "__main__":
    unittest.main()
