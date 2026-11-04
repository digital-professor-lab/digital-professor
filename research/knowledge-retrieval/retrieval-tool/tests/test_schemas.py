"""The JSON Schema files describe exactly what the code produces: every kind of request, bundle and stop
the service can emit must validate, and the files in schemas/ must match the code."""

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

from _setup import ctx, index_root
from retrieval_tool import build_service, decide, run_turn
from retrieval_tool.backends import BackendUnavailable
from retrieval_tool.llm import ScriptedLLM, answer, tool_call
from retrieval_tool.planner import RetrievalPlanner, plan_to_request
from retrieval_tool.service import RetrievalService, development_policy
from retrieval_tool.tool_schema import build_request, build_structured_request

try:
    import jsonschema  # noqa: F401
    from retrieval_tool.schemas import validate_record
    HAVE_JSONSCHEMA = True
except ImportError:
    HAVE_JSONSCHEMA = False

ROOT = index_root()
WEEK8 = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "artifacts/evaluations/refinement_runs/facets_6.jsonl" if ROOT else None
CHAIN = "calc1.03-derivatives.chain-rule"


def args(query, *needs, purpose="answer_grounding", **extra):
    return {"query": query, "purpose": purpose,
            "evidence_needs": [dict(zip(("need_type", "description", "anchor"), n)) for n in needs], **extra}


@unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema not installed (pip install jsonschema)")
class SchemaFileTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(WEEK8 / "scripts"))
        from export_schemas import schema_folder
        self.folder = schema_folder()
        if not self.folder.exists():
            self.skipTest(f"schema files not found at {self.folder} (in the repo they arrive with specs/, JDP-36)")

    def test_files_match_the_code(self):
        from export_schemas import rendered
        for name, text in rendered().items():
            self.assertEqual((self.folder / name).read_text(encoding="utf-8"), text,
                             f"{name} is out of date: run python scripts/export_schemas.py")

    def test_files_are_valid_json_schema(self):
        for path in self.folder.glob("*.schema.json"):
            jsonschema.Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


@unittest.skipUnless(HAVE_JSONSCHEMA and ROOT is not None, "jsonschema or Week 3 index files not available")
class RecordsMatchSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = build_service("memory", root=ROOT, test_double=True)

    def assertValid(self, record):
        self.assertEqual(validate_record(record), [], json.dumps(record, ensure_ascii=False)[:400])

    def test_requests(self):
        planner = RetrievalPlanner.from_folder(["calc1"])
        c = ctx(concept_ids=[CHAIN], student_message="I got cos(x^2). Why is that wrong?",
                intent_summary="omitted the inner derivative", evidence_summary="wrote cos(x^2)",
                bank_sibling_question_ids=["q-chain-2"], course_context_ref={"course_context_id": "calc1", "version": "1.1"})
        self.assertValid(build_request(args("chain rule", ("theorem_statement", "chain rule", "chain rule")), c))
        self.assertValid(build_request(args("chain rule example", ("worked_example", "example"), purpose="example_lookup"), c))
        self.assertValid(build_request(args("chain rule", ("definition", "chain rule")), c, top_k=4))
        self.assertValid(build_structured_request(c, decide("hint")))
        self.assertValid(plan_to_request(planner.draft(c, decide("explain")), c, purpose="answer_grounding"))

    def test_every_bundle_status_and_warning_path(self):
        run = lambda a, **o: self.service.handle(build_request(a, ctx(**o)))  # noqa: E731
        supported = run(args("fundamental theorem of calculus",
                             ("theorem_statement", "Statement of the fundamental theorem of calculus", "fundamental theorem")))
        partial = run(args("chain rule", ("theorem_statement", "statement of the chain rule"),
                           ("worked_example", "worked example of the chain rule")))
        nothing = run(args("Laplace transform", ("definition", "definition of the Laplace transform")))
        excluded = run(args("What does the Calculus II material say about contour plots?",
                            ("definition", "contour plots"), contains_student_wording=True))
        language = run(args("链式法则", ("definition", "链式法则")))
        statuses = [b["retrieval_status"] for b in (supported, partial, nothing, excluded, language)]
        self.assertEqual(statuses, ["supported", "partial", "no_support_found", "no_support_found", "no_support_found"])
        for bundle in (supported, partial, nothing, excluded, language):
            self.assertValid(bundle)

        strict = RetrievalService(self.service.backend, self.service.catalog,
                                  {"calc1": replace(development_policy("calc1"), allow_unverified_sources="none")})
        self.assertValid(strict.handle(build_request(args("chain rule", ("definition", "chain rule")), ctx())))

        syllabus_only = RetrievalService(self.service.backend, self.service.catalog,
                                         {"calc1": replace(development_policy("calc1"), reference_only_source_types=("syllabus",))})
        syllabus_only._eligible_documents = lambda p: [d for d in self.service.catalog.documents_for("calc1")
                                                       if d["source_type"] == "syllabus"]
        self.assertValid(syllabus_only.handle(build_request(args("chain rule", ("definition", "chain rule")), ctx())))

        class Broken:
            name, semantic_available = "broken", True

            def query_facets(self, question):
                return []

            def run(self, *a, **k):
                raise BackendUnavailable("index_unavailable", "database down")
        failed = RetrievalService(Broken(), self.service.catalog, self.service.policies).handle(
            build_request(args("chain rule", ("definition", "chain rule")), ctx()))
        self.assertEqual(failed["retrieval_status"], "failed")
        self.assertValid(failed)

    def test_every_stop_reason(self):
        run = lambda a, **o: self.service.handle(build_request(a, ctx(**o)))  # noqa: E731
        stops = [run(args("chain rule", ("definition", "chain rule")), course_id="calc2"),
                 run(args("chain rule", ("definition", "chain rule")), retrieval_snapshot_id="snap.old"),
                 run(args("What does the second semester cover?", ("course_policy", "second semester topics"),
                          contains_student_wording=True)),
                 RetrievalService(self.service.backend, self.service.catalog,
                                  {"calc1": replace(development_policy("calc1"), published=False)}).handle(
                     build_request(args("chain rule", ("definition", "chain rule")), ctx()))]
        self.assertEqual([s["stop_reason"] for s in stops],
                         ["invalid_request", "version_mismatch", "needs_clarification", "course_not_ready"])
        for stop in stops:
            self.assertValid(stop)

    def test_records_of_a_whole_turn(self):
        tool_args = {"query": "chain rule for composite functions", "purpose": "answer_grounding",
                     "concept_id": CHAIN,
                     "evidence_needs": [{"need_type": "theorem_statement", "description": "statement of the chain rule"}]}
        result = run_turn(ScriptedLLM([tool_call(tool_args), answer("ok")]), self.service,
                          ctx(action_type="explain", concept_ids=[CHAIN], student_message="Why is cos(x^2) wrong?"))
        for record in [*result.requests, *result.records]:
            self.assertValid(record)

    def test_schema_catches_contract_breaks(self):
        bundle = self.service.handle(build_request(args("fundamental theorem of calculus",
                                                        ("theorem_statement", "fundamental theorem", "fundamental theorem")), ctx()))
        broken = [dict(bundle, retrieval_status="supported", passages=[]),            # supported needs passages
                  {k: v for k, v in bundle.items() if k != "course_id"},              # identifiers must be kept
                  dict(bundle, warnings=[{"code": "made_up_code", "message": "x"}]),  # unknown warning code
                  dict(bundle, retrieval_status="failed")]                            # failed has no passages
        for record in broken:
            self.assertNotEqual(validate_record(record), [])


@unittest.skipUnless(HAVE_JSONSCHEMA and ROOT is not None and REPLAY is not None and REPLAY.exists(),
                     "jsonschema or Week 3 saved runs not available")
class RealWeek3OutputTests(unittest.TestCase):
    def test_all_50_benchmark_bundles_validate(self):
        """Bundles built from Week 3's own saved search results (real passages, both courses)."""
        service = build_service("replay", root=ROOT, replay_file=REPLAY)
        cases = [json.loads(l) for l in (ROOT / "data/benchmark/benchmark_50.jsonl").read_text().splitlines() if l.strip()]
        for case in cases:
            request = build_request({"query": case["question"], "purpose": "answer_grounding",
                                     "evidence_needs": [{"need_type": "method_guidance", "description": case["question"][:200]}]},
                                    ctx(course_id=case["course_id"], turn_id=case["id"],
                                        retrieval_snapshot_id=f"snap.{case['course_id']}.dev-ai-breakdown.1"), top_k=6)
            self.assertEqual(validate_record(request), [], case["id"])
            self.assertEqual(validate_record(service.handle(request)), [], case["id"])


if __name__ == "__main__":
    unittest.main()
