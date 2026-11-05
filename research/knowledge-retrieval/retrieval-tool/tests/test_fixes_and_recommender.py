"""Fixes after the first real DeepSeek run (2026-10-29) and the optional Jev retrieval recommender."""

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from _setup import ctx, engine_turn
from retrieval_tool import build_service, recommend_grounding
from retrieval_tool.citations import CitationMap, model_view, strip_labels
from retrieval_tool.evidence import JevEvidenceJudge, is_formula, related, rule_check
from retrieval_tool.jev_client import JevClient
from retrieval_tool.jev_recommender import JevSearchRecommender, default_recommender
from retrieval_tool.llm import ScriptedLLM, answer, tool_call
from retrieval_tool.tool_schema import build_request

GRADIENT = {"query": "gradient vector of a function of several variables", "purpose": "answer_grounding",
            "evidence_needs": [{"need_type": "definition", "description": "Definition of the gradient", "anchor": "gradient"}]}


class EvidenceRuleTests(unittest.TestCase):
    ROW = "4.5.1 & The Chain Rule & Differentiate composite functions. & \\diffH \\\\"

    def test_term_anchor_never_covers_a_formula_need(self):
        self.assertFalse(is_formula("chain rule"))
        self.assertEqual(rule_check({"need_type": "formula_statement", "description": "chain rule formula",
                                     "anchor": "chain rule"}, self.ROW)[0], "partially_covered")

    def test_real_formula_anchor_covers(self):
        text = "Integration by parts, $\\int u\\,dv = uv - \\int v\\,du$"
        self.assertEqual(rule_check({"need_type": "formula_statement", "description": "by parts",
                                     "anchor": "∫ u dv = uv − ∫ v du"}, text)[0], "covered")

    def test_rule_word_alone_is_not_a_theorem_statement(self):
        self.assertEqual(rule_check({"need_type": "theorem_statement", "description": "Statement of the chain rule",
                                     "anchor": "chain rule"}, self.ROW)[0], "partially_covered")

    def test_concept_must_be_mentioned(self):
        need = {"need_type": "method_guidance", "description": "How to use Laplace transforms to solve differential equations"}
        text = "The definite integral, transformations of functions, differential equations"
        self.assertEqual(rule_check(need, text, ["Laplace transform"])[0], "not_covered")
        self.assertFalse(related(need, text, ["Laplace transform"]))


class CitationViewTests(unittest.TestCase):
    def test_passages_without_support_are_not_citable(self):
        bundle = {"record_type": "GroundingBundle", "retrieval_status": "partial", "warnings": [],
                  "passages": [{"passage_id": "a", "passage_text": "x"}, {"passage_id": "b", "passage_text": "y"}],
                  "need_coverage": [{"need_id": "n1", "coverage": "partially_covered", "passage_ids": ["a"]}],
                  "uncovered_needs": ["n1"]}
        view = model_view(bundle, CitationMap())
        self.assertEqual([p["citable"] for p in view["passages"]], [True, False])

    def test_scope_reason_reaches_the_model(self):
        bundle = {"record_type": "GroundingBundle", "retrieval_status": "no_support_found", "passages": [],
                  "warnings": [{"code": "excluded_scope", "message": "outside_course_scope (in the student message)"}]}
        view = model_view(bundle, CitationMap())
        self.assertIn("outside this course", view["instructions"])
        self.assertIn("do not search again", view["instructions"])

    def test_strip_labels_leaves_clean_text(self):
        self.assertEqual(strip_labels("see the lists in [P3], [P4], [P5], and [P6]. Ok [P1, P9].", ["P3", "P5", "P9"]),
                         "see the lists in [P4] and [P6]. Ok [P1].")


class TurnFixTests(unittest.TestCase):
    def setUp(self):
        self.service = build_service("fixture")

    def test_student_message_is_scope_checked_even_if_query_is_rewritten(self):
        c = ctx(student_message="What does the Calculus II material say about gradients?")
        record = self.service.handle(build_request(GRADIENT, c))
        self.assertEqual(record["retrieval_status"], "no_support_found")
        self.assertEqual(record["warnings"][0]["code"], "excluded_scope")
        self.assertIn("student message", record["warnings"][0]["message"])

    def test_off_topic_bundle_becomes_no_support_found(self):
        args = {"query": "Laplace transform definition and properties", "purpose": "answer_grounding",
                "evidence_needs": [{"need_type": "method_guidance", "description": "How to apply the Laplace transform"}]}
        record = self.service.handle(build_request(args, ctx(concept_names=["Laplace transform"])))
        self.assertEqual((record["retrieval_status"], record["passages"]), ("no_support_found", []))

    def test_prompt_carries_question_length_and_general_knowledge_rule(self):
        llm = ScriptedLLM([answer("Show me your steps for this one.")])
        engine_turn(llm, self.service, ctx(action_type="inspect", question_prompt="Differentiate f(x) = sin(x^2).",
                                        course_title="Calculus I"))
        system = llm.calls[0]["messages"][0]["content"]
        self.assertIn("tutor for the course Calculus I", system)
        self.assertIn("Do not say yet whether the answer is right", system)
        self.assertIn("Differentiate f(x) = sin(x^2).", system)
        self.assertIn("at most 110 words", system)
        self.assertIn("Not from your course materials", system)          # dev policy allows a labelled aside
        self.service.policies["calc1"] = replace(self.service.policies["calc1"], allow_general_knowledge=False)
        llm = ScriptedLLM([answer("ok"), answer("ok")])
        result = engine_turn(llm, self.service, ctx(action_type="explain"))      # must turn, no context to prefetch with
        self.assertTrue(any("prefetch impossible" in e.get("note", "") for e in result.events))
        self.assertIn("do not teach it from general knowledge", llm.calls[0]["messages"][0]["content"])
        self.assertIn("at most 170 words", llm.calls[0]["messages"][0]["content"])


class FakeJev:
    def __init__(self, p=None, error=None):
        self.p, self.error, self.states = p, error, []

    def ask(self, state, questions):
        self.states.append(state)
        if self.error:
            raise RuntimeError(self.error)
        return {"needs_course_material": {"type": "noul", "noul": self.p}}


class JevRecommenderTests(unittest.TestCase):
    def setUp(self):
        self.service = build_service("fixture")
        self.service.policies["calc1"] = replace(self.service.policies["calc1"], external_processing_allowed=True)
        self.ftc = {"query": "fundamental theorem of calculus", "purpose": "definition_lookup",
                    "evidence_needs": [{"need_type": "theorem_statement", "description": "the fundamental theorem of calculus",
                                        "anchor": "fundamental theorem"}]}

    def test_thresholds(self):
        c = ctx(action_type="probe", student_message="what does the course call this?")
        self.assertEqual(JevSearchRecommender(FakeJev(0.9)).recommend(c)["choice"], "force")
        self.assertEqual(JevSearchRecommender(FakeJev(0.1)).recommend(c)["choice"], "skip")
        self.assertEqual(JevSearchRecommender(FakeJev(0.5)).recommend(c)["choice"], "auto")

    def test_force_makes_retrieval_required(self):
        llm = ScriptedLLM([tool_call(self.ftc), answer("The course lists both parts of the FTC [P1].")])
        result = engine_turn(llm, self.service, ctx(action_type="probe", student_message="What does our course say the FTC is?"),
                          recommender=JevSearchRecommender(FakeJev(0.92)))
        self.assertEqual(llm.calls[0]["tool_choice"], "required")
        self.assertEqual(result.decision["mode"], "must")

    def test_skip_offers_no_tool(self):
        llm = ScriptedLLM([answer("Which function is inside?")])
        result = engine_turn(llm, self.service, ctx(action_type="probe", student_message="hmm let me think"),
                          recommender=JevSearchRecommender(FakeJev(0.05)))
        self.assertIsNone(llm.calls[0]["tools"])
        self.assertEqual(result.requests, [])

    def test_recommender_error_or_policy_falls_back_to_the_model(self):
        llm = ScriptedLLM([answer("Which function is inside?")])
        result = engine_turn(llm, self.service, ctx(action_type="probe", student_message="x"),
                          recommender=JevSearchRecommender(FakeJev(error="timeout")))
        self.assertEqual(llm.calls[0]["tool_choice"], "auto")
        self.assertIn("recommender error", result.events[0]["note"])
        self.service.policies["calc1"] = replace(self.service.policies["calc1"], external_processing_allowed=False)
        jev = FakeJev(0.99)
        engine_turn(ScriptedLLM([answer("ok")]), self.service, ctx(action_type="probe", student_message="x"),
                 recommender=JevSearchRecommender(jev))
        self.assertEqual(jev.states, [])                                   # student text never sent

    def test_recommender_only_touches_may_turns(self):
        jev = FakeJev(0.01)
        llm = ScriptedLLM([tool_call(self.ftc | {"purpose": "answer_grounding"}), answer("ok [P1]")])
        engine_turn(llm, self.service, ctx(action_type="explain"), recommender=JevSearchRecommender(jev))
        self.assertEqual((jev.states, llm.calls[0]["tool_choice"]), ([], "required"))


if __name__ == "__main__":
    unittest.main()


class FakeJudge:
    """Says every passage states every need with probability p (or raises)."""

    def __init__(self, p=0.9, error=None):
        self.p, self.error, self.calls = p, error, 0

    def score(self, needs, texts):
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        return [{n["need_id"]: self.p for n in needs} for _ in texts]

    def coverage(self, p):
        return "covered" if p >= 0.7 else "partially_covered" if p >= 0.35 else "not_covered"


class EvidenceJudgeModeTests(unittest.TestCase):
    ARGS = {"query": "fundamental theorem of calculus", "purpose": "answer_grounding",
            "evidence_needs": [{"need_type": "theorem_statement", "description": "Statement of the FTC",
                                "anchor": "fundamental theorem"}]}

    def service(self, mode, judge):
        from retrieval_tool import RetrievalOptions
        return build_service("fixture", options=RetrievalOptions(judge_mode=mode), judge=judge)

    def test_shadow_logs_but_does_not_change_the_bundle(self):
        plain = build_service("fixture").handle(build_request(self.ARGS, ctx()))
        svc = self.service("shadow", FakeJudge(p=0.1))
        shadow = svc.handle(build_request(self.ARGS, ctx()))
        self.assertEqual(shadow["need_coverage"][0]["coverage"], plain["need_coverage"][0]["coverage"])
        self.assertEqual(svc.last_report["judge"]["verdicts"][0]["coverage"], "not_covered")

    def test_on_lets_the_judge_decide(self):
        svc = self.service("on", FakeJudge(p=0.1))
        b = svc.handle(build_request(self.ARGS, ctx()))
        self.assertEqual((b["need_coverage"][0]["coverage"], b["need_coverage"][0]["method"]), ("not_covered", "judge"))

    def test_judge_failure_falls_back_to_rules(self):
        svc = self.service("on", FakeJudge(error="timeout"))
        b = svc.handle(build_request(self.ARGS, ctx()))
        self.assertTrue(b["need_coverage"][0]["method"].startswith("rule"))
        self.assertIn("judge_fallback", " ".join(w["message"] for w in b["warnings"]))

    def test_one_judge_call_per_bundle(self):
        judge = FakeJudge()
        self.service("shadow", judge).handle(build_request(self.ARGS, ctx()))
        self.assertEqual(judge.calls, 1)      # all passages scored in one batched call


class DefaultRecommenderTests(unittest.TestCase):
    def test_missing_jev_key_means_the_model_decides(self):
        names = ("JEV_PROVIDER", "TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "AI_GATEWAY_API_KEY")
        with mock.patch.dict(os.environ, {"JEV_ENV_FILE": "/nonexistent/.env"}):
            for name in names:
                os.environ.pop(name, None)
            recommender, note = default_recommender()
        self.assertIsNone(recommender)
        self.assertIn("the model decides", note)


class JevClientTests(unittest.TestCase):
    """The packaged client, through its offline mock provider: no key, no network."""

    def client(self, folder):
        return JevClient("mock", cache_path=Path(folder) / "jev.jsonl")

    def test_recommender_runs_on_the_packaged_client(self):
        with tempfile.TemporaryDirectory() as folder:
            verdict = JevSearchRecommender(self.client(folder)).recommend(ctx(action_type="probe", student_message="why?"))
        self.assertIn(verdict["choice"], ("force", "skip", "auto"))

    def test_evidence_judge_runs_on_the_packaged_client(self):
        needs = [{"need_id": "n1", "need_type": "definition", "description": "chain rule"}]
        with tempfile.TemporaryDirectory() as folder:
            scores = JevEvidenceJudge(self.client(folder)).score(needs, ["The chain rule states ..."])
        self.assertIn("n1", scores[0])

    def test_answers_are_cached(self):
        state, questions = {"a": "x"}, {"q": {"type": "noul", "instructions": "i", "criteria": {}}}
        with tempfile.TemporaryDirectory() as folder:
            first = self.client(folder)
            answer_one = first.ask(state, questions)
            second = self.client(folder)
            self.assertEqual(second.ask(state, questions), answer_one)
            self.assertEqual(second.usage.cached_calls, 1)


class ScopeBlockAndRuntimeTests(unittest.TestCase):
    def test_no_second_search_after_an_out_of_scope_result(self):
        service = build_service("fixture")
        second = {"query": "directional derivative", "purpose": "answer_grounding",
                  "evidence_needs": [{"need_type": "definition", "description": "directional derivative"}]}
        llm = ScriptedLLM([tool_call(GRADIENT, call_id="a"), tool_call(second, call_id="b"), answer("That is outside this course.")])
        result = engine_turn(llm, service, ctx(action_type="explain",
                                            student_message="What does the Calculus II material say about gradients?"))
        self.assertEqual(len(result.requests), 1)
        refused = json.loads([m for m in llm.calls[2]["messages"] if m["role"] == "tool"][-1]["content"])
        self.assertIn("do not search again", refused["error"])

    def test_runtime_without_jev_uses_rules_and_the_model(self):
        from retrieval_tool import build_tutoring_runtime
        service, recommender, notes = build_tutoring_runtime("fixture", use_jev=False)
        self.assertIsNone(recommender)
        self.assertEqual(service.options.judge_mode, "off")
        self.assertIn("Jev off", notes[0])
