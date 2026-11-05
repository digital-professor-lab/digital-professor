"""Integration tests against the pinned Week 3 checkout.

They run after scripts/setup_week3.sh and `pip install -e ".[test,postgres]"`. Without those they skip,
each with its reason. None of them needs Docker, an API key or a model download.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

from _setup import ctx, week3_root
from retrieval_tool import RetrievalOptions, build_service
from retrieval_tool.backends import BackendUnavailable, InMemoryBackend, PgvectorBackend
from retrieval_tool.local_fixture import FIXTURE_ROOT
from retrieval_tool.schemas import validate_record
from retrieval_tool.service import RetrievalService
from retrieval_tool.tool_schema import build_request

import test_service

ROOT = week3_root()
REPLAY = ROOT / "artifacts/evaluations/refinement_runs/facets_6.jsonl" if ROOT else None
HAVE_POSTGRES_CLIENT = all(importlib.util.find_spec(name) for name in ("psycopg", "pgvector"))
NO_WEEK3 = "Week 3 checkout not found: run bash scripts/setup_week3.sh"
NO_CLIENT = 'PostgreSQL client packages not installed: pip install -e ".[postgres]"'


class FixtureSafetyTests(unittest.TestCase):
    def test_memory_stand_in_needs_explicit_test_flag(self):
        with self.assertRaises(ValueError):
            build_service("memory", root=FIXTURE_ROOT)


@unittest.skipIf(ROOT is None, NO_WEEK3)
class Week3ReplayTests(unittest.TestCase):
    """The tool path must return exactly what Week 3 returned (Week 3's saved facets_6 reports)."""

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
            turn = ctx(course_id=case["course_id"], turn_id=case["id"],
                       retrieval_snapshot_id=f"snap.{case['course_id']}.dev-ai-breakdown.1")
            out[case["id"]] = (build_request(args, turn, top_k=6), None)
            out[case["id"]] = (out[case["id"]][0], service.handle(out[case["id"]][0]))
        return service, out

    def test_same_passages_same_order_as_week3(self):
        _, out = self.run_all()
        for cid, report in self.recorded.items():
            week3_ids = [r["passage_id"] for r in report["results"]]
            tool_ids = [p["legacy_locator"]["week3_passage_id"] for p in out[cid][1].get("passages", [])]
            self.assertEqual(tool_ids, week3_ids, cid)

    def test_week3_statuses_map_to_v1(self):
        _, out = self.run_all()
        for cid, report in self.recorded.items():
            record = out[cid][1]
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
        self.assertTrue(all(out[cid][1].get("passages") for cid in found))

    def test_all_50_benchmark_records_validate(self):
        """Bundles built from Week 3's own saved search results (real passages, both courses)."""
        _, out = self.run_all(RetrievalOptions())
        for cid, (request, record) in out.items():
            self.assertEqual(validate_record(request), [], cid)
            self.assertEqual(validate_record(record), [], cid)


@unittest.skipIf(ROOT is None, NO_WEEK3)
@unittest.skipUnless(HAVE_POSTGRES_CLIENT, NO_CLIENT)
class ServiceOnWeek3CodeTests(test_service.ServiceTests):
    """The same service tests, on Week 3's own Retriever over Week 3's files."""

    @classmethod
    def setUpClass(cls):
        cls.service = build_service("memory", root=ROOT, test_double=True)

    def test_vector_channel_path_with_stub_encoder(self):
        # Stub encoder: returns the stored vector of the first record mentioning the query's first word.
        probe = InMemoryBackend(ROOT, catalog=self.service.catalog, encoder=lambda k, t: None)

        def encoder(key, texts):
            out = []
            for text in texts:
                word = text.split()[0].lower()
                idx = next((i for i, r in enumerate(probe.records) if word in r["input_text"].lower()), 0)
                out.append(probe.vectors[key][idx])
            return np.stack(out)
        backend = InMemoryBackend(ROOT, catalog=self.service.catalog, encoder=encoder)
        self.assertTrue(backend.semantic_available)
        svc = RetrievalService(backend, self.service.catalog, self.service.policies)
        b = svc.handle(build_request(test_service.args("logistic growth model", ("definition", "logistic growth model")), ctx()))
        self.assertNotIn("semantic_channel_unavailable", {w["code"] for w in b["warnings"]})
        report = backend.run("logistic growth", [], course_id="calc1")
        self.assertTrue(any(set(r["signals"]) & {"bge_base_en_v1_5", "qwen3_embedding_0_6b"} for r in report["results"]))
        self.assertEqual(report["channel_candidate_counts"]["bge_base_en_v1_5"], 40)


@unittest.skipIf(ROOT is None, NO_WEEK3)
class PgvectorAdapterTests(unittest.TestCase):
    def test_week3_folder_is_used_and_encoder_fault_is_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb = Path(tmp)
            (kb / "retrieval").mkdir()
            (kb / "retrieval" / "search.py").write_text(
                "class Retriever:\n"
                "    def __init__(self, models=(), device='auto'):\n"
                "        self.models, self.device = models, device\n"
                "    def close(self):\n        pass\n")
            (kb / "retrieval" / "request_policy.py").write_text("def query_facets(q):\n    return []\n")
            (kb / "retrieval" / "report_contract.py").write_text("def validate_report_contract(r):\n    pass\n")
            for name in ("search", "request_policy", "report_contract"):
                sys.modules.pop(name, None)
            backend = PgvectorBackend(ROOT, week3_kb=kb, models=("bge_base_en_v1_5",))
            self.assertTrue(backend.semantic_available)
            if importlib.util.find_spec("sentence_transformers") is None:
                # encoder library missing -> component fault -> `failed`, not `no_support_found`
                with self.assertRaises(BackendUnavailable) as raised:
                    backend.run("chain rule", [], course_id="calc1")
                self.assertEqual(raised.exception.code, "encoder_unavailable")
            for name in ("search", "request_policy", "report_contract"):
                sys.modules.pop(name, None)
            sys.path.remove(str(kb / "retrieval"))


if __name__ == "__main__":
    unittest.main()
