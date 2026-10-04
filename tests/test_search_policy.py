"""Behavioral checks for file concentration and conservative Not found rules."""
import unittest

from digital_professor.retrieval.search import Retriever, format_llm_prompt, unsupported_request_reason


SOURCES = {"syllabus", "context", "textbook_reference"}


class SearchPolicyTests(unittest.TestCase):
    def reason(self, question, **overrides):
        options = dict(include_unconfirmed=False, include_outside_course=False, source_types=SOURCES)
        options.update(overrides)
        return unsupported_request_reason(question, **options)

    def test_explicit_requests_and_opt_in(self):
        for question, expected in (
            ("What does Calculus II say about gradients?", "outside_course_scope"),
            ("What does the unconfirmed second-semester unit cover?", "unconfirmed_semester_scope"),
            ("What exact words did the professor say on Monday?", "lecture_record_unavailable"),
            ("What grade did student Bob receive?", "student_record_unavailable"),
        ):
            with self.subTest(question=question):
                self.assertEqual(self.reason(question), expected)
        self.assertIsNone(self.reason("What does Calculus II cover?", include_outside_course=True))
        self.assertIsNone(self.reason("What does the second-semester unit cover?", include_unconfirmed=True))
        self.assertIsNone(self.reason("What exact words did the professor say?", source_types=SOURCES | {"lecture_record"}))
        self.assertIsNone(self.reason("What grade did student Bob receive?", source_types=SOURCES | {"student_record"}))

    def test_general_course_questions_are_not_rejected(self):
        for question in (
            "Explain the Chain Rule.", "Which grading methods does the syllabus describe?",
            "What grade must a student receive to pass this course?",
            "What should students focus on in this lecture topic?",
            "Quote the exact words in the definition of a Dedekind domain.",
            "Explain the Fundamental Theorem of Calculus.",
        ):
            with self.subTest(question=question):
                self.assertIsNone(self.reason(question))

    def fake_retriever(self, count=6):
        retriever = Retriever.__new__(Retriever)
        retriever.models = ("bge_base_en_v1_5",)
        retriever.source_types = SOURCES
        rows = {}
        for index in range(count):
            rows[str(index)] = {
                "passage_id": f"p{index}", "raw_latex": "Useful evidence " * 10,
                "filename": "same.tex", "course_id": "calc1", "course_name": "Calculus I",
                "source_type": "textbook_reference", "snapshot_path": "same.tex",
                "section_path": "Methods", "start_line": index * 10 + 1,
                "end_line": index * 10 + 9, "scope_status": "pilot_course_or_general",
                "review_status": "unverified", "known_issues": [],
            }
        retriever._vector_channel = lambda *args: list(rows)
        retriever._hydrate = lambda ids: {key: rows[key] for key in ids}
        return retriever

    def search(self, retriever, **overrides):
        options = dict(course_id=None, include_unconfirmed=False, include_outside_course=False,
                       include_flagged=False, top_k=6, candidate_limit=40,
                       context_chars=12000, use_lexical=False, max_per_document=2)
        options.update(overrides)
        return retriever._search_with_vectors("Explain the Chain Rule", {"bge_base_en_v1_5": None}, **options)

    def test_soft_limit_allows_strong_same_file_evidence(self):
        retriever = self.fake_retriever()
        hard = self.search(retriever, document_limit_mode="hard")
        soft = self.search(retriever, document_limit_mode="soft")
        self.assertEqual(len(hard["results"]), 2)
        self.assertEqual(len(soft["results"]), 6)
        self.assertEqual(len({r["passage_id"] for r in soft["results"]}), 6)
        self.assertTrue(all(r["raw_latex"] in soft["context"] for r in soft["results"]))

    def test_soft_limit_still_respects_context_budget(self):
        report = self.search(self.fake_retriever(), document_limit_mode="soft", context_chars=350)
        self.assertEqual(len(report["results"]), 2)
        self.assertLessEqual(report["raw_excerpt_characters"], 350)

    def test_empty_results_are_explicit_and_prompt_does_not_invent(self):
        report = self.search(self.fake_retriever(0))
        self.assertEqual(report["status"], "not_found")
        self.assertEqual(report["message"], "Not found")
        self.assertEqual(report["results"], [])
        self.assertIn("do not invent an answer", format_llm_prompt(report).lower())

    def test_budget_failure_is_not_claimed_to_be_missing_material(self):
        report = self.search(self.fake_retriever(), context_chars=10)
        self.assertEqual(report["not_found_reason"], "context_budget_exhausted")
        self.assertEqual(report["evidence_assessment"]["next_action"], "adjust_context_budget")

    def test_rejected_questions_skip_embedding(self):
        retriever = self.fake_retriever()
        retriever._encode_questions = lambda _: self.fail("Rejected question should not load embedding models")
        report = retriever.search_many(["What exact words did the instructor say yesterday?"])[0]
        self.assertEqual(report["not_found_reason"], "lecture_record_unavailable")
        self.assertEqual(report["channel_candidate_counts"], {})


if __name__ == "__main__":
    unittest.main()
