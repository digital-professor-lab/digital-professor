import unittest
from dataclasses import replace

from _setup import ctx
from retrieval_tool import build_service
from retrieval_tool.backends import BackendUnavailable
from retrieval_tool.local_fixture import fixture_scope_checker
from retrieval_tool.records import check_bundle_invariants
from retrieval_tool.service import RetrievalService, development_policy
from retrieval_tool.tool_schema import build_request



def args(query, *needs, purpose="answer_grounding", **extra):
    return {"query": query, "purpose": purpose,
            "evidence_needs": [dict(zip(("need_type", "description", "anchor"), n)) for n in needs], **extra}


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = build_service("fixture")

    def run_tool(self, tool_args, **ctx_overrides):
        return self.service.handle(build_request(tool_args, ctx(**ctx_overrides)))

    def test_supported_bundle_with_locations_and_provenance(self):
        b = self.run_tool(args("fundamental theorem of calculus",
                               ("theorem_statement", "Statement of the fundamental theorem of calculus", "fundamental theorem")))
        self.assertEqual(b["retrieval_status"], "supported")
        self.assertEqual(check_bundle_invariants(b), [])
        p = b["passages"][0]
        self.assertTrue(p["passage_id"].startswith("psg_"))
        self.assertIsNone(p["page_number"])              # no fabricated page numbers in the dev corpus
        self.assertIsNone(p["highlight_url"])
        self.assertIn("source_line_start", p["legacy_locator"])
        codes = {w["code"] for w in b["warnings"]}
        self.assertTrue({"unverified_source", "location_unavailable"} <= codes)

    def test_partial_lists_uncovered_needs(self):
        b = self.run_tool(args("chain rule for composite functions",
                               ("theorem_statement", "Statement of the chain rule", "chain rule"),
                               ("method_guidance", "How to pick the inner and outer function")))
        self.assertEqual(b["retrieval_status"], "partial")
        self.assertIn("n2", b["uncovered_needs"])
        self.assertEqual(check_bundle_invariants(b), [])

    def test_not_in_corpus_is_no_support_found_without_passages(self):
        b = self.run_tool(args("Laplace transform", ("definition", "Definition of the Laplace transform", "Laplace transform")))
        self.assertEqual(b["retrieval_status"], "no_support_found")
        self.assertEqual(b["passages"], [])

    def test_passage_ids_are_deterministic(self):
        a = self.run_tool(args("fundamental theorem of calculus", ("theorem_statement", "fundamental theorem of calculus")))
        b = self.run_tool(args("fundamental theorem of calculus", ("theorem_statement", "fundamental theorem of calculus")))
        self.assertEqual([p["passage_id"] for p in a["passages"]], [p["passage_id"] for p in b["passages"]])

    def test_stops(self):
        unknown = self.run_tool(args("chain rule", ("definition", "chain rule")), course_id="calc2")
        self.assertEqual((unknown["record_type"], unknown["stop_reason"]), ("RetrievalStop", "invalid_request"))
        stale = self.run_tool(args("chain rule", ("definition", "chain rule")), retrieval_snapshot_id="snap.old")
        self.assertEqual(stale["stop_reason"], "version_mismatch")

    def test_student_wording_scope_check(self):
        excluded = self.run_tool(args("What does the Calculus II material say about contour plots?",
                                      ("definition", "contour plots"), contains_student_wording=True))
        self.assertEqual(excluded["retrieval_status"], "no_support_found")
        self.assertEqual(excluded["warnings"][0]["code"], "excluded_scope")
        unclear = self.run_tool(args("What does the second semester cover?", ("course_policy", "second semester topics"),
                                     contains_student_wording=True))
        self.assertEqual((unclear["record_type"], unclear["stop_reason"]), ("RetrievalStop", "needs_clarification"))
        absent = self.run_tool(args("What exact words did the instructor say in lecture?", ("course_policy", "lecture words"),
                                    contains_student_wording=True))
        self.assertEqual(absent["warnings"][0]["code"], "source_class_unavailable")

    def test_structured_queries_skip_preflight_b_but_week3_rules_still_apply(self):
        # Preflight B (free-text check) only runs for student wording ...
        b = self.run_tool(args("fundamental theorem of calculus", ("theorem_statement", "fundamental theorem")))
        self.assertNotIn("scope_check", self.service.last_report["preflight"])
        # ... but Week 3's search applies its own scope rules to every query (aligned with Week 3)
        b = self.run_tool(args("second semester", ("course_policy", "second semester topics")))
        self.assertEqual((b["record_type"], b["stop_reason"]), ("RetrievalStop", "needs_clarification"))

    def test_selection_is_week3_order_and_not_pruned(self):
        b = self.run_tool(args("chain rule for composite functions",
                               ("theorem_statement", "Statement of the chain rule", "chain rule"),
                               ("method_guidance", "How to pick the inner and outer function")))
        week3_ids = self.service.last_report["week3"]["selected"]
        self.assertEqual([p["legacy_locator"]["week3_passage_id"] for p in b["passages"]], week3_ids)
        self.assertLessEqual(len(b["passages"]), 6)
        self.assertEqual(b["query_interpretation"]["selection"], getattr(self.service.backend, "selection", "week3_production"))
        self.assertIn(b["query_interpretation"]["facet_source"], ("week3_query_facets", "none"))   # Week 3 default

    def test_evidence_needs_as_subquestions_is_a_switch(self):
        from retrieval_tool import RetrievalOptions
        svc = RetrievalService(self.service.backend, self.service.catalog, self.service.policies,
                               options=RetrievalOptions(facet_source="evidence_needs"))
        b = svc.handle(build_request(args("chain rule for composite functions",
                                          ("theorem_statement", "Statement of the chain rule", "chain rule")), ctx()))
        self.assertEqual(b["query_interpretation"]["facet_source"], "evidence_needs")
        self.assertEqual(svc.last_report["query_plan"]["facets"], ["Statement of the chain rule"])

    def test_english_only(self):
        b = self.run_tool(args("链式法则 chain rule", ("definition", "chain rule")))
        self.assertEqual(b["warnings"][0]["code"], "query_language_unsupported")

    def test_provenance_policy_none_blocks_ai_corpus(self):
        catalog = self.service.catalog
        strict = {"calc1": replace(development_policy("calc1"), allow_unverified_sources="none")}
        svc = RetrievalService(self.service.backend, catalog, strict, scope_checker=fixture_scope_checker)
        b = svc.handle(build_request(args("chain rule", ("definition", "chain rule")), ctx()))
        self.assertEqual((b["retrieval_status"], b["warnings"][0]["code"]), ("no_support_found", "no_eligible_sources"))

    def test_identifiers_are_passed_through(self):
        c = ctx()
        request = build_request(args("chain rule", ("definition", "chain rule")), c)
        b = self.service.handle(request)
        for key in ("retrieval_request_id", "course_id", "question_id", "session_id", "turn_id", "correlation_id"):
            self.assertEqual(b[key], request[key], key)
        bad = dict(request, purpose="nonsense")
        stop = self.service.handle(bad)
        self.assertEqual(stop["record_type"], "RetrievalStop")
        for key in ("retrieval_request_id", "course_id", "question_id", "session_id", "turn_id"):
            self.assertEqual(stop[key], request[key], key)

    def test_syllabus_only_course_is_reference_only(self):
        # example a: only the syllabus exists, which names topics but does not state them
        production = {"calc1": replace(development_policy("calc1"), reference_only_source_types=("syllabus",))}
        svc = RetrievalService(self.service.backend, self.service.catalog, production)
        svc._eligible_documents = lambda policy: [d for d in self.service.catalog.documents_for("calc1")
                                                  if d["source_type"] == "syllabus"]
        b = svc.handle(build_request(args("chain rule", ("definition", "chain rule")), ctx()))
        self.assertEqual(b["retrieval_status"], "no_support_found")
        self.assertEqual([w["code"] for w in b["warnings"]], ["reference_only", "no_ingested_sources"])
        self.assertEqual(check_bundle_invariants(b), [])

    def test_reference_only_passages_are_never_returned(self):
        production = {"calc1": replace(development_policy("calc1"), reference_only_source_types=("syllabus",))}
        svc = RetrievalService(self.service.backend, self.service.catalog, production)
        query = args("chain rule", ("definition", "chain rule"))
        dev = self.service.handle(build_request(query, ctx()))
        prod = svc.handle(build_request(query, ctx()))
        self.assertTrue(any(p["document_id"] == "calc1:syllabus" for p in dev["passages"]))
        self.assertFalse(any(p["document_id"] == "calc1:syllabus" for p in prod["passages"]))
        self.assertEqual([p["retrieval_rank"] for p in prod["passages"]], list(range(1, len(prod["passages"]) + 1)))

    def test_unpublished_course(self):
        svc = RetrievalService(self.service.backend, self.service.catalog,
                               {"calc1": replace(development_policy("calc1"), published=False)})
        r = svc.handle(build_request(args("chain rule", ("definition", "chain rule")), ctx()))
        self.assertEqual(r["stop_reason"], "course_not_ready")

    def test_backend_fault_is_failed_not_no_support(self):
        class Broken:
            name, semantic_available = "broken", True

            def query_facets(self, question):
                return []

            def run(self, *a, **k):
                raise BackendUnavailable("index_unavailable", "database down")

        svc = RetrievalService(Broken(), self.service.catalog, self.service.policies)
        b = svc.handle(build_request(args("chain rule", ("definition", "chain rule")), ctx()))
        self.assertEqual(b["retrieval_status"], "failed")
        self.assertTrue(b["warnings"][0]["retryable"])

    def test_cross_course_isolation(self):
        b = self.run_tool(args("quadratic reciprocity", ("theorem_statement", "quadratic reciprocity law", "reciprocity")))
        docs = {p["document_id"] for p in b["passages"]}
        self.assertTrue(all(d.startswith("calc1:") for d in docs))

    def test_registry_records_bundles_for_t4(self):
        b = self.run_tool(args("fundamental theorem of calculus", ("theorem_statement", "fundamental theorem of calculus")))
        self.assertIn(b, self.service.registry.for_turn("sess-1", "turn-1"))
        self.assertIsNotNone(self.service.registry.resolve(b["passages"][0]["passage_id"]))


if __name__ == "__main__":
    unittest.main()
