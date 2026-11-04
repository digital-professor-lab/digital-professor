"""Retrieval planner: concept linking, draft, validation/repair, schema, and its use inside a turn."""

import json
import unittest

from _setup import ctx, index_root
from retrieval_tool import build_service, decide, run_turn
from retrieval_tool.llm import ScriptedLLM, answer, tool_call
from retrieval_tool.planner import (PLAN_VERSION, RetrievalPlanner, plan_is_usable, plan_to_request, validate_plan)
from retrieval_tool.tool_schema import tool_for_decision

ROOT = index_root()
CHAIN = "calc1.03-derivatives.chain-rule"
FTC = "calc1.05-integration.ftc"


class LinkingAndDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.planner = RetrievalPlanner.from_folder(["calc1", "number_theory_1"])
        cls.catalog = cls.planner.catalog("calc1")

    def test_course_context_list_is_loaded(self):
        self.assertEqual(len(self.catalog.concepts), 33)
        self.assertIsNone(self.planner.catalog("number_theory_1"))      # no Course Context for it yet

    def test_clear_mentions_link_and_vague_text_does_not(self):
        pick = lambda text: self.catalog.auto_select(self.catalog.link(text))  # noqa: E731
        self.assertEqual(pick("What does the fundamental theorem of calculus say?"), [FTC])
        self.assertEqual(pick("Explain integration by parts."), ["calc1.06-integral-applications.by-parts"])
        self.assertEqual(pick("So is it cos(x^2) times something?"), [])        # paraphrase: left to the model
        self.assertEqual(pick("Can you explain Laplace transforms?"), [])       # 'transforms' ≠ 'transformations'
        self.assertEqual(pick("What does the Calculus II material say about gradients?"), [])
        self.assertEqual(pick("What is the derivative?"), [])                   # one common word is not a mention

    def test_question_schema_concept_wins_over_linking(self):
        c = ctx(concept_ids=[CHAIN], student_message="what does the fundamental theorem of calculus say?")
        draft = self.planner.draft(c, decide("explain"))
        self.assertEqual([(x["concept_id"], x["source"]) for x in draft["concepts"]], [(CHAIN, "question_schema")])

    def test_draft_is_a_valid_plan(self):
        draft = self.planner.draft(ctx(student_message="What does the FTC part about accumulation say? fundamental theorem of calculus"),
                                   decide("explain"))
        self.assertEqual(validate_plan(draft), [])
        self.assertEqual(draft["plan_version"], PLAN_VERSION)
        self.assertEqual([n["need_type"] for n in draft["needs"]], ["definition", "theorem_statement"])
        self.assertIn("Fundamental Theorem of Calculus", draft["needs"][1]["query"])
        self.assertEqual(draft["scope"]["module_ids"], ["calc1.05-integration"])
        self.assertEqual(draft["scope"]["narrowing"], "not_enforced")

    def test_draft_without_any_concept_has_no_needs(self):
        draft = self.planner.draft(ctx(student_message="Can you explain Laplace transforms?"), decide("explain"))
        self.assertEqual((draft["concepts"], draft["needs"]), ([], []))
        self.assertFalse(plan_is_usable(draft))


class FinalizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.planner = RetrievalPlanner.from_folder(["calc1"])

    def draft(self, **kw):
        return self.planner.draft(ctx(**kw), decide("explain"))

    def test_unknown_concepts_are_dropped_and_recorded(self):
        c = ctx(student_message="How do I differentiate sin(x^2)?")
        plan = self.planner.finalize({"query": "chain rule", "concept_id": "calc1.99-made-up", "related_concept_ids": [CHAIN],
                                      "evidence_needs": [{"need_type": "theorem_statement", "description": "statement of the chain rule"}]},
                                     self.draft(student_message="How do I differentiate sin(x^2)?"), c)
        self.assertEqual([(x["concept_id"], x["source"], x["role"]) for x in plan["concepts"]], [(CHAIN, "model", "primary")])
        codes = [r["code"] for r in plan["repairs"]]
        self.assertIn("unknown_concept_dropped", codes)
        self.assertIn("first_related_promoted_to_primary", codes)
        self.assertEqual(validate_plan(plan), [])

    def test_question_schema_concept_cannot_be_removed(self):
        c = ctx(concept_ids=[CHAIN])
        plan = self.planner.finalize({"query": "product rule", "concept_id": "calc1.03-derivatives.product-quotient",
                                      "evidence_needs": [{"need_type": "definition", "description": "product rule"}]},
                                     self.planner.draft(c, decide("explain")), c)
        self.assertEqual([x["concept_id"] for x in plan["concepts"]], [CHAIN, "calc1.03-derivatives.product-quotient"])

    def test_missing_parts_come_from_the_draft(self):
        c = ctx(student_message="What does the fundamental theorem of calculus say?")
        draft = self.planner.draft(c, decide("explain"))
        plan = self.planner.finalize({"query": "", "evidence_needs": []}, draft, c)
        codes = [r["code"] for r in plan["repairs"]]
        self.assertIn("main_query_from_draft", codes)
        self.assertIn("needs_from_draft", codes)
        self.assertEqual(plan["needs"], draft["needs"])
        self.assertEqual([x["concept_id"] for x in plan["concepts"]], [FTC])

    def test_needs_are_cleaned(self):
        c = ctx(concept_ids=[CHAIN])
        needs = [{"need_type": "definition", "description": "chain rule definition"},
                 {"need_type": "definition", "description": "Chain rule definition"},          # duplicate
                 {"need_type": "vibes", "description": "x"},                                  # invalid type
                 {"need_type": "worked_example", "description": "example", "concept_id": FTC},  # concept not in plan
                 {"need_type": "exercise", "description": "practice on chain rule"},
                 {"need_type": "method_guidance", "description": "how to spot the inner function"},
                 {"need_type": "notation_convention", "description": "Leibniz notation"}]
        plan = self.planner.finalize({"query": "chain rule", "evidence_needs": needs},
                                     self.planner.draft(c, decide("explain")), c)
        codes = [r["code"] for r in plan["repairs"]]
        for code in ("duplicate_dropped", "invalid_need_dropped", "not_a_plan_concept_dropped", "truncated"):
            self.assertIn(code, codes)
        self.assertEqual([n["need_id"] for n in plan["needs"]], ["n1", "n2", "n3", "n4"])
        self.assertTrue(all(n.get("concept_id") == CHAIN for n in plan["needs"]))
        self.assertEqual(validate_plan(plan), [])

    def test_schema_check_catches_problems(self):
        bad = {"plan_version": "x", "course_id": "calc1", "concepts": [], "concept_status": "found", "main_query": "", "needs": [],
               "scope": {"module_ids": [], "narrowing": "everywhere"}, "origin": "guess", "repairs": [], "extra": 1}
        problems = validate_plan(bad)
        for p in ("plan_version", "main_query length", "needs count", "origin", "scope.narrowing", "unknown field extra",
                  "concept_status does not match the primary concepts"):
            self.assertIn(p, problems)

    def test_plan_becomes_a_request(self):
        c = ctx(concept_ids=[CHAIN])
        plan = self.planner.draft(c, decide("explain"))
        request = plan_to_request(plan, c, purpose="answer_grounding")
        self.assertEqual(request["retrieval_plan"], plan)
        self.assertEqual(request["concept_ids"], [CHAIN])
        self.assertEqual(request["concept_names"], ["The chain rule"])
        self.assertEqual([n["description"] for n in request["evidence_needs"]], [n["query"] for n in plan["needs"]])

    def test_tool_concept_fields_are_enums_of_the_course_list(self):
        menu = self.planner.concept_menu("calc1")
        props = tool_for_decision(decide("explain"), concept_menu=menu)["function"]["parameters"]["properties"]
        self.assertEqual(len(props["concept_id"]["enum"]), 34)                  # 33 concepts + not_in_course
        self.assertIn("not_in_course", props["concept_id"]["enum"])
        self.assertEqual(len(props["related_concept_ids"]["items"]["enum"]), 33)
        bare = tool_for_decision(decide("explain"))["function"]["parameters"]["properties"]
        self.assertNotIn("concept_id", bare)
        self.assertNotIn("related_concept_ids", bare)

    def test_one_primary_concept_and_related_ones_stay_out_of_the_request(self):
        c = ctx(student_message="How do I find dy/dx for x^2 + y^2 = 25?")
        plan = self.planner.finalize({"query": "implicit differentiation", "concept_id": "calc1.03-derivatives.implicit",
                                      "related_concept_ids": [CHAIN],
                                      "evidence_needs": [{"need_type": "method_guidance", "description": "steps of implicit differentiation"}]},
                                     self.draft(student_message="How do I find dy/dx for x^2 + y^2 = 25?"), c)
        self.assertEqual([(x["concept_id"], x["role"]) for x in plan["concepts"]],
                         [("calc1.03-derivatives.implicit", "primary"), (CHAIN, "related")])
        self.assertEqual(plan["concept_status"], "found")
        self.assertEqual(plan["needs"][0]["concept_id"], "calc1.03-derivatives.implicit")
        self.assertEqual(validate_plan(plan), [])
        request = plan_to_request(plan, c, purpose="answer_grounding")
        self.assertEqual(request["concept_ids"], ["calc1.03-derivatives.implicit"])   # related not used for support

    def test_not_in_course_is_recorded_and_removes_linked_concepts(self):
        c = ctx(student_message="Can you explain Laplace transforms?")
        plan = self.planner.finalize({"query": "Laplace transform", "concept_id": "not_in_course",
                                      "evidence_needs": [{"need_type": "definition", "description": "definition of the Laplace transform"}]},
                                     self.draft(student_message="Can you explain Laplace transforms?"), c)
        self.assertEqual((plan["concepts"], plan["concept_status"]), ([], "not_in_course"))
        self.assertEqual(validate_plan(plan), [])
        self.assertEqual(plan_to_request(plan, c, purpose="answer_grounding")["concept_ids"], [])

    def test_not_in_course_cannot_override_a_bank_question(self):
        c = ctx(concept_ids=[CHAIN])
        plan = self.planner.finalize({"query": "x", "concept_id": "not_in_course",
                                      "evidence_needs": [{"need_type": "definition", "description": "chain rule"}]},
                                     self.planner.draft(c, decide("explain")), c)
        self.assertEqual(plan["concept_status"], "found")
        self.assertIn("not_in_course_ignored", [r["code"] for r in plan["repairs"]])

    def test_model_primary_becomes_related_on_a_bank_question(self):
        c = ctx(concept_ids=[CHAIN])
        plan = self.planner.finalize({"query": "trig derivative", "concept_id": "calc1.03-derivatives.trig",
                                      "evidence_needs": [{"need_type": "definition", "description": "derivative of sine"}]},
                                     self.planner.draft(c, decide("explain")), c)
        self.assertEqual([(x["concept_id"], x["role"]) for x in plan["concepts"]],
                         [(CHAIN, "primary"), ("calc1.03-derivatives.trig", "related")])

    def test_old_concept_ids_list_still_accepted(self):
        c = ctx(student_message="Why do I multiply by the inside derivative?")
        plan = self.planner.finalize({"query": "chain rule", "concept_ids": [CHAIN, "calc1.03-derivatives.trig"],
                                      "evidence_needs": [{"need_type": "theorem_statement", "description": "chain rule"}]},
                                     self.draft(student_message="Why do I multiply by the inside derivative?"), c)
        self.assertEqual([(x["concept_id"], x["role"]) for x in plan["concepts"]],
                         [(CHAIN, "primary"), ("calc1.03-derivatives.trig", "related")])


@unittest.skipIf(ROOT is None, "Week 3 index files not found (set DP_RETRIEVAL_ROOT)")
class PlannerInTurnTests(unittest.TestCase):
    def setUp(self):
        self.service = build_service("memory", root=ROOT, test_double=True)

    def test_model_sees_the_draft_and_the_list_and_its_proposal_is_repaired(self):
        args = {"query": "chain rule for composite functions", "purpose": "answer_grounding",
                "concept_id": "calc1.99-made-up",
                "evidence_needs": [{"need_type": "theorem_statement", "description": "statement of the chain rule"}]}
        llm = ScriptedLLM([tool_call(args), answer("ok")])
        result = run_turn(llm, self.service, ctx(action_type="explain", concept_ids=[CHAIN],
                                                 student_message="I got cos(x^2). Why is that wrong?"))
        system = llm.calls[0]["messages"][0]["content"]
        self.assertIn("Retrieval plan drafted by the system", system)
        self.assertIn(f"{CHAIN} — The chain rule", system)
        plan_event = next(e for e in result.events if e["event_type"] == "retrieval_plan")
        self.assertEqual(plan_event["concepts"], [(CHAIN, "question_schema")])
        self.assertIn("unknown_concept_dropped", [r["code"] for r in plan_event["repairs"]])
        self.assertEqual(result.requests[0]["retrieval_plan"]["origin"], "model")
        self.assertEqual(self.service.last_report["retrieval_plan"]["schema_problems"], [])

    def test_prefetch_uses_the_code_draft(self):
        llm = ScriptedLLM([answer("from memory"), answer("ok")])
        result = run_turn(llm, self.service, ctx(action_type="explain", concept_ids=[FTC],
                                                 student_message="What does it say?"))
        request = result.requests[0]
        self.assertEqual(request["producer"], "tutoring-engine:prefetch")
        self.assertEqual(request["retrieval_plan"]["origin"], "draft")
        self.assertEqual(request["concept_ids"], [FTC])

    def test_plan_without_needs_is_sent_back_to_the_model(self):
        empty = {"query": "Laplace transform", "purpose": "answer_grounding", "evidence_needs": []}
        fixed = {"query": "Laplace transform", "purpose": "answer_grounding",
                 "evidence_needs": [{"need_type": "definition", "description": "definition of the Laplace transform"}]}
        llm = ScriptedLLM([tool_call(empty, call_id="a"), tool_call(fixed, call_id="b"), answer("not in this course")])
        result = run_turn(llm, self.service, ctx(action_type="explain", student_message="Can you explain Laplace transforms?"))
        first = json.loads([m for m in llm.calls[1]["messages"] if m["role"] == "tool"][0]["content"])
        self.assertEqual(first["error"], "invalid arguments")
        self.assertEqual(len(result.requests), 1)


if __name__ == "__main__":
    unittest.main()
