import unittest
from digital_professor.retrieval.request_policy import assess_request, query_facets
from digital_professor.retrieval.report_contract import validate_report_contract
import test_search_policy as support

SOURCES = support.SOURCES


class RequestPolicyTests(unittest.TestCase):
    def assess(self, question, **overrides):
        options = dict(include_unconfirmed=False, include_outside_course=False, source_types=SOURCES)
        options.update(overrides)
        return assess_request(question, **options)

    def test_scope_mentions_are_not_always_requests(self):
        for question in (
            "Explain derivatives in Calculus I, not Calculus II.",
            "Use Calculus I, not from Calculus II.",
            "I studied Calculus II, but explain the Chain Rule in Calculus I.",
            "Without Calculus II, explain the Fundamental Theorem of Calculus.",
        ):
            with self.subTest(question=question):
                self.assertEqual(self.assess(question).decision, "retrieve")

    def test_mixed_and_ambiguous_scopes_require_clarification(self):
        self.assertEqual(self.assess("Compare Calculus I and Calculus II.").decision, "needs_clarification")
        self.assertEqual(self.assess("What does the second semester cover?").category, "ambiguous_scope")
        self.assertEqual(self.assess("Explain Calculus I limits.", course_id="number_theory_1").reason_code, "course_filter_conflict")
        self.assertEqual(self.assess("Explain Calculus II.", include_outside_course=True,
                                     course_id="number_theory_1").decision, "needs_clarification")

    def test_excluded_scope_and_source_missing_are_distinct(self):
        scope = self.assess("What does Calculus II say about gradients?")
        lecture = self.assess("What did the professor say yesterday?")
        self.assertEqual(scope.category, "out_of_scope")
        self.assertEqual(lecture.category, "source_unavailable")
        self.assertEqual(lecture.required_source_types, ["lecture_record"])
        self.assertTrue(scope.matched_rules)
        self.assertEqual(self.assess("What grade did Bob receive?").category, "source_unavailable")
        self.assertEqual(self.assess("What score did student alice receive?").category, "source_unavailable")

    def test_general_questions_and_source_opt_in(self):
        self.assertEqual(self.assess("What score is needed to pass the course?").decision, "retrieve")
        self.assertEqual(self.assess("Quote the exact words defining a Dedekind domain.").decision, "retrieve")
        self.assertEqual(self.assess("What did the professor say?", source_types=SOURCES|{"lecture_record"}).decision, "retrieve")
        self.assertEqual(self.assess("Compare Calculus I and Calculus II.", include_outside_course=True).decision, "retrieve")
        self.assertEqual(self.assess("Explain second-semester number theory.", include_unconfirmed=True).decision, "retrieve")

    def test_facets_are_general_and_do_not_invent_concepts(self):
        self.assertEqual(query_facets("Compare A with B."), ["A.", "B."])
        facets = query_facets("Which theorem is used in oscillating models, and where does the course apply it?")
        self.assertEqual(len(facets), 2)
        self.assertNotIn("Sandwich", " ".join(facets))
        self.assertEqual(query_facets("Explain the Chain Rule."), [])

    def test_contract_rejects_evidence_on_not_found(self):
        helper = support.SearchPolicyTests()
        report = helper.search(helper.fake_retriever(0))
        validate_report_contract(report)
        report["results"] = [{"raw_latex": "unsupported evidence"}]
        with self.assertRaises(ValueError):
            validate_report_contract(report)


if __name__ == "__main__":
    unittest.main()
