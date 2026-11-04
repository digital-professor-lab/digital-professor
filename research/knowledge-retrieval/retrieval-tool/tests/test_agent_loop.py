import json
import unittest

from _setup import ctx, index_root
from retrieval_tool import build_service, decide, run_turn
from retrieval_tool.citations import CitationMap, extract_labels, verify_grounding_refs
from retrieval_tool.llm import LLMResponse, ScriptedLLM, ToolCall, answer, tool_call

ROOT = index_root()
FTC_CALL = {"query": "fundamental theorem of calculus", "purpose": "answer_grounding",
            "evidence_needs": [{"need_type": "theorem_statement", "description": "Statement of the fundamental theorem of calculus",
                                "anchor": "fundamental theorem"}]}


class CitationTests(unittest.TestCase):
    def test_extract_labels(self):
        self.assertEqual(extract_labels("see [P1] and [P2, P3]; again [P1]"), ["P1", "P2", "P3"])

    def test_verify_rules(self):
        bundle = {"turn_id": "t", "session_id": "s", "retrieval_status": "partial",
                  "passages": [{"passage_id": "a"}, {"passage_id": "b"}, {"passage_id": "c"}],
                  "need_coverage": [{"need_id": "n1", "coverage": "covered", "passage_ids": ["a"]},
                                    {"need_id": "n2", "coverage": "partially_covered", "passage_ids": ["b"]}]}
        check = verify_grounding_refs(["a", "b", "c", "zz"], [bundle], session_id="s", turn_id="t")
        self.assertEqual(check["accepted"], ["a", "b"])
        self.assertEqual({r["code"] for r in check["rejected"]}, {"citation_need_not_covered", "citation_not_from_turn_bundle"})
        other_turn = verify_grounding_refs(["a"], [bundle], session_id="s", turn_id="t2")
        self.assertFalse(other_turn["ok"])
        strict = verify_grounding_refs(["b"], [bundle], session_id="s", turn_id="t", allow_partial=False)
        self.assertFalse(strict["ok"])

    def test_labels_are_stable_within_a_turn(self):
        m = CitationMap()
        self.assertEqual([m.label_for("x"), m.label_for("y"), m.label_for("x")], ["P1", "P2", "P1"])


@unittest.skipIf(ROOT is None, "Week 3 index files not found (set DP_RETRIEVAL_ROOT)")
class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        self.service = build_service("memory", root=ROOT, test_double=True)

    def test_must_forces_tool_and_maps_citations(self):
        llm = ScriptedLLM([tool_call(FTC_CALL), answer("The course states the FTC links derivatives and integrals [P1].")])
        result = run_turn(llm, self.service, ctx(action_type="explain", student_message="why is FTC true?"))
        self.assertEqual(llm.calls[0]["tool_choice"], "required")
        self.assertEqual(llm.calls[1]["tool_choice"], "auto")
        self.assertEqual(result.records[0]["retrieval_status"], "supported")
        self.assertTrue(result.citation_check["ok"])
        self.assertEqual(result.grounding_refs, [result.records[0]["passages"][0]["passage_id"]])
        tool_msg = [m for m in llm.calls[1]["messages"] if m["role"] == "tool"][0]
        self.assertEqual(json.loads(tool_msg["content"])["passages"][0]["label"], "P1")

    def test_must_prefetches_when_model_skips_the_tool(self):
        llm = ScriptedLLM([answer("Here is the FTC from memory, page 212."), answer("Grounded answer [P1].")])
        # concept names only: the offline stand-in has no vector channel, so a long intent sentence finds nothing
        result = run_turn(llm, self.service, ctx(action_type="explain", concept_names=["fundamental theorem of calculus"]))
        self.assertEqual(result.requests[0]["producer"], "tutoring-engine:prefetch")
        self.assertEqual(result.answer, "Grounded answer [P1].")
        self.assertTrue(any(e.get("note", "").startswith("model skipped") for e in result.events))

    def test_must_prefetches_when_provider_rejects_required(self):
        llm = ScriptedLLM([answer("Grounded answer [P1].")], honors_required=False)
        result = run_turn(llm, self.service, ctx(action_type="explain", concept_names=["fundamental theorem of calculus"]))
        self.assertEqual(len(result.requests), 1)
        self.assertTrue(result.citation_check["ok"])

    def test_may_lets_the_model_decide(self):
        llm = ScriptedLLM([answer("What do you think happens to the inner function?")])
        result = run_turn(llm, self.service, ctx(action_type="probe"))
        self.assertEqual(llm.calls[0]["tool_choice"], "auto")
        self.assertEqual(result.requests, [])
        self.assertEqual(result.grounding_refs, [])

    def test_not_needed_sends_no_tool(self):
        llm = ScriptedLLM([answer("Please show your steps.")])
        run_turn(llm, self.service, ctx(action_type="inspect"))
        self.assertIsNone(llm.calls[0]["tools"])
        self.assertIsNone(llm.calls[0]["tool_choice"])

    def test_fabricated_citation_is_rewritten_then_stripped(self):
        llm = ScriptedLLM([tool_call(FTC_CALL), answer("FTC [P1], also see [P9]."), answer("Still [P9].")])
        result = run_turn(llm, self.service, ctx(action_type="explain"))
        self.assertNotIn("[P9]", result.answer)
        self.assertTrue(result.citation_check.get("stripped_invalid_citations"))
        self.assertIn("cannot be cited", llm.calls[2]["messages"][-1]["content"])
        self.assertIn("not from the student", llm.calls[2]["messages"][-1]["content"])

    def test_wrong_purpose_is_returned_to_the_model(self):
        bad = {**FTC_CALL, "purpose": "practice_generation"}
        llm = ScriptedLLM([tool_call(bad), tool_call(FTC_CALL, call_id="c2"), answer("ok [P1]")])
        result = run_turn(llm, self.service, ctx(action_type="explain"))
        first_tool_result = json.loads([m for m in llm.calls[1]["messages"] if m["role"] == "tool"][0]["content"])
        self.assertEqual(first_tool_result["error"], "invalid arguments")
        self.assertEqual(len(result.requests), 1)

    def test_tool_call_limit(self):
        llm = ScriptedLLM([tool_call(FTC_CALL, call_id="a"), tool_call(FTC_CALL, call_id="b"),
                           answer("done [P1]")])
        result = run_turn(llm, self.service, ctx(action_type="explain"))
        self.assertEqual(len(result.requests), 2)
        self.assertEqual(llm.calls[2]["tool_choice"], "none")

    def test_no_support_found_answer_has_no_refs(self):
        laplace = {"query": "Laplace transform", "purpose": "answer_grounding",
                   "evidence_needs": [{"need_type": "definition", "description": "Definition of the Laplace transform",
                                       "anchor": "Laplace transform"}]}
        llm = ScriptedLLM([tool_call(laplace), answer("The course materials do not cover the Laplace transform.")])
        result = run_turn(llm, self.service, ctx(action_type="explain"))
        self.assertEqual(result.records[0]["retrieval_status"], "no_support_found")
        view = json.loads([m for m in llm.calls[1]["messages"] if m["role"] == "tool"][0]["content"])
        self.assertIn("do not cover", view["instructions"])
        self.assertEqual(result.grounding_refs, [])


if __name__ == "__main__":
    unittest.main()
