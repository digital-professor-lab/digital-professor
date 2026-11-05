import unittest

from _setup import ctx
from retrieval_tool.policy import GROUNDING_POLICY, recommend_grounding, policy_table
from retrieval_tool.records import TUTORING_ACTIONS
from retrieval_tool.tool_schema import (ToolArgumentError, build_request, build_structured_request, openai_tool,
                                        tool_for_decision, validate_tool_arguments)

ARGS = {"query": "chain rule for composite functions", "purpose": "answer_grounding",
        "evidence_needs": [{"need_type": "theorem_statement", "description": "Statement of the chain rule"}]}


class PolicyTests(unittest.TestCase):
    def test_every_tutoring_action_has_a_row(self):
        self.assertEqual(set(GROUNDING_POLICY), set(TUTORING_ACTIONS))
        self.assertEqual(len(policy_table()), 12)

    def test_modes_follow_spec_section_2_2(self):
        expected = {"elicit": "not_needed", "inspect": "must_not", "probe": "may", "diagnose": "may",
                    "hint": "must", "contrast": "must", "demonstrate": "must", "explain": "must",
                    "retry": "not_needed", "verify": "must_not", "check_understanding": "may", "transfer": "may"}
        self.assertEqual({a: recommend_grounding(a).mode for a in TUTORING_ACTIONS}, expected)

    def test_tool_choice_mapping(self):
        self.assertEqual(recommend_grounding("explain").tool_choice, "required")
        self.assertEqual(recommend_grounding("probe").tool_choice, "auto")
        self.assertIsNone(recommend_grounding("elicit").tool_choice)
        self.assertFalse(recommend_grounding("verify").offer_tool)

    def test_flags(self):
        self.assertEqual(recommend_grounding("hint", states_course_content=False).mode, "may")
        self.assertEqual(recommend_grounding("verify", checks_course_convention=True).mode, "may")
        self.assertEqual(recommend_grounding("explain", course_ready=False).mode, "not_needed")
        with self.assertRaises(ValueError):
            recommend_grounding("lecture")

    def test_tool_is_narrowed_to_the_turn(self):
        tool = tool_for_decision(recommend_grounding("demonstrate"))
        self.assertEqual(tool["function"]["parameters"]["properties"]["purpose"]["enum"], ["example_lookup"])
        self.assertNotIn("course_id", openai_tool()["function"]["parameters"]["properties"])


class ToolArgumentTests(unittest.TestCase):
    def test_model_cannot_choose_course_or_version(self):
        errors = validate_tool_arguments({**ARGS, "course_id": "calc2", "retrieval_snapshot_id": "x"})
        self.assertEqual({e["field"] for e in errors}, {"course_id", "retrieval_snapshot_id"})

    def test_bad_needs_rejected(self):
        with self.assertRaises(ToolArgumentError):
            build_request({**ARGS, "evidence_needs": []}, ctx())
        with self.assertRaises(ToolArgumentError):
            build_request({**ARGS, "evidence_needs": [{"need_type": "vibes", "description": "x"}]}, ctx())

    def test_system_fields_are_injected(self):
        c = ctx(concept_ids=["calc1.03.chain-rule"], evidence_summary="dropped inner derivative")
        r = build_request(ARGS, c)
        self.assertEqual((r["course_id"], r["question_id"], r["turn_id"], r["session_id"]),
                         (c.course_id, c.question_id, c.turn_id, c.session_id))
        self.assertEqual(r["retrieval_snapshot_id"], c.retrieval_snapshot_id)
        self.assertEqual(r["concept_ids"], ["calc1.03.chain-rule"])
        self.assertEqual(r["evidence_needs"][0]["need_id"], "n1")
        self.assertEqual(r["query_origin"], "structured")
        self.assertEqual(r["record_type"], "RetrievalRequest")

    def test_answer_leak_guard_for_examples(self):
        c = ctx(bank_sibling_question_ids=["q-sib"])
        r = build_request({**ARGS, "purpose": "example_lookup"}, c)
        self.assertEqual(r["exclude"]["question_ids"], [c.question_id, "q-sib"])

    def test_copied_student_wording_triggers_scope_check(self):
        c = ctx(student_message="can you use the calculus two notes from the second semester for this")
        r = build_request({**ARGS, "query": "use the calculus two notes from the second semester"}, c)
        self.assertEqual(r["query_origin"], "student_text")
        self.assertEqual(build_request({**ARGS, "contains_student_wording": True}, ctx())["query_origin"], "student_text")

    def test_structured_prefetch_request(self):
        c = ctx(intent_summary="student dropped the inner derivative", concept_names=["chain rule"])
        r = build_structured_request(c, recommend_grounding("explain"))
        self.assertEqual(r["producer"], "tutoring-engine:prefetch")
        self.assertEqual(r["query_origin"], "structured")
        self.assertEqual([n["need_type"] for n in r["evidence_needs"]],
                         ["definition", "theorem_statement", "prerequisite_explanation"])


if __name__ == "__main__":
    unittest.main()
