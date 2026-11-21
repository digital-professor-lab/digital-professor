"""decide(), reconciliation and the gap rules: pure code, no model."""

from __future__ import annotations

import copy
import itertools

import pytest

from digital_professor.tutoring.decide import TurnInputs, decide, may_name_method
from digital_professor.tutoring.judge import reconcile
from digital_professor.tutoring.policy import MAX_LEVEL, MODEL_DIAGNOSES, TURN_TYPES, Settings
from digital_professor.tutoring.state import (QuestionState, apply_gap_updates, build_gaps, choose_target_gap,
                                              method_name)

from .helpers import make_question

CFG = Settings()
CORRECT = {"status": "correct", "flags": []}
WRONG = {"status": "incorrect", "flags": []}
UNKNOWN = {"status": "unknown", "flags": []}
ABSENT = {"status": "absent", "flags": []}


def fresh() -> QuestionState:
    return QuestionState(gaps=build_gaps(make_question()))


def step(state: QuestionState, turn_type: str, **inputs):
    """One delivered turn: decide, then record that the student saw a real reply."""
    inputs.setdefault("saw_last", state.last_situation is not None)
    inputs.setdefault("evidence_id", f"e{state.turn_count + 1}")
    decision = decide(TurnInputs(turn_type=turn_type, **inputs), state, CFG, [])
    state.last_situation = decision.situation
    state.last_counts = decision.situation not in ("safety", "park", "switch", "redirect")
    return decision


def verdict(diagnosis: str, confidence: str = "high", **extra) -> dict:
    return {"diagnosis": diagnosis, "confidence": confidence, "explanation": "none", "target_gap": None,
            "gap_updates": [], **extra}


# --------------------------------------------------------------------------- situations and counters
def test_posing_the_problem_is_not_an_attempt_and_nothing_is_taught() -> None:
    state = fresh()
    decision = step(state, "VAGUE", opening=True)
    assert (decision.situation, decision.searches) == ("open", False)
    assert not state.has_attempt and state.stall_count == 0 and not may_name_method(state)


def test_code_counts_help_requests_but_does_not_choose_the_help() -> None:
    state = fresh()
    step(state, "VAGUE", opening=True)
    decisions = [step(state, "HELP") for _ in range(3)]
    assert [d.situation for d in decisions] == ["help"] * 3
    assert [d.searches for d in decisions] == [False, True, True]   # the textbook comes the second time
    assert state.help_requests == 3 and state.stall_count == 3
    assert state.help_level == 0                # help given is recorded from the move the writer chose


def test_the_method_is_held_back_until_the_student_is_stuck_a_second_time() -> None:
    state = fresh()
    step(state, "VAGUE", opening=True)
    step(state, "PARTIAL", math=UNKNOWN, assessment=verdict("ON_TRACK"), has_work=True)
    assert not may_name_method(state)                               # progressing, no help asked
    step(state, "HELP")
    assert not may_name_method(state)                               # stuck once: the tutor points
    asked, wrong = copy.deepcopy(state), copy.deepcopy(state)
    step(asked, "HELP")
    assert may_name_method(asked)                                   # stuck twice
    step(wrong, "PARTIAL", math=UNKNOWN, assessment=verdict("D5"), has_work=True)
    assert may_name_method(wrong)                                   # one request and one wrong attempt
    taught = fresh()
    taught.help_level = 2
    assert may_name_method(taught)                                  # once given, it stays given


def test_a_correct_step_is_progress_not_a_stall() -> None:
    state = fresh()
    step(state, "VAGUE", opening=True)
    step(state, "HELP")
    assert state.stall_count == 1
    for _ in range(4):
        decision = step(state, "PARTIAL", math=UNKNOWN, assessment=verdict("ON_TRACK"), has_work=True)
    assert (decision.situation, decision.diagnosis) == ("attempt", "ON_TRACK")
    assert (state.stall_count, state.phase) == (0, "WORKING")


def test_repeating_the_same_error_counts_as_no_progress() -> None:
    state = fresh()
    step(state, "PARTIAL", math=UNKNOWN, assessment=verdict("D5"), has_work=True)
    assert state.stall_count == 0                                   # a first attempt is progress
    step(state, "PARTIAL", math=UNKNOWN, assessment=verdict("D5"), has_work=True)
    assert state.stall_count == 1 and state.last_diagnosis == "D5"


def test_no_progress_for_six_turns_ends_in_a_pause() -> None:
    state = fresh()
    step(state, "VAGUE", opening=True)
    situations = [step(state, "HELP").situation for _ in range(6)]
    assert situations[-1] == "park" and state.phase == "PARKED" and state.park_reason == "stall"
    assert step(state, "HELP").situation == "help" and state.stall_count == 0       # coming back starts again


def test_wrong_answers_without_work_are_counted() -> None:
    state = fresh()
    for _ in range(3):
        assert step(state, "ANSWER", math=WRONG, assessment=verdict("D5")).situation == "attempt"
    assert state.guess_count == 3
    step(state, "ANSWER", math=WRONG, assessment=verdict("D5"), has_work=True)
    assert state.guess_count == 0


def test_turn_limit_pauses_the_question() -> None:
    state = fresh()
    state.turn_count = CFG.max_turns_per_question
    assert step(state, "PARTIAL", math=UNKNOWN, assessment=verdict("ON_TRACK")).situation == "park"
    assert state.park_reason == "turn_limit"


def test_demanding_the_answer_never_solves_the_question() -> None:
    state = fresh()
    step(state, "VAGUE", opening=True)
    for _ in range(4):
        assert step(state, "DEMAND", demand=True).situation == "help"
    assert state.help_requests == 4 and not state.main_solved


def test_safety_signal_always_wins_and_holds() -> None:
    state = fresh()
    assert step(state, "ANSWER", safety_signal=True, math=CORRECT).situation == "safety"
    assert step(state, "ANSWER", math=CORRECT).situation == "safety" and not state.main_solved


def test_turns_that_are_not_counted_against_the_student() -> None:
    state = fresh()
    step(state, "VAGUE", opening=True)
    assert step(state, "CONCEPT").situation == "concept"
    assert step(state, "OFF_TOPIC").situation == "redirect"
    assert step(state, "NEW_QUESTION").situation == "switch"
    assert state.help_requests == 0 and state.stall_count == 0
    faulty = step(state, "PARTIAL", fault=True, math=UNKNOWN)
    assert faulty.situation == "attempt" and state.turn_count == 4


# --------------------------------------------------------------------------- solving
def test_a_correct_answer_solves_the_question_at_once() -> None:
    state = fresh()
    decision = step(state, "ANSWER", math=CORRECT, has_work=True)
    assert decision.situation == "wrap_up" and decision.verdict_source == "tool"
    assert state.main_solved and state.phase == "SOLVED"
    assert state.correct_level == "D10" and state.gaps["method"].status == "closed"


def test_correct_answer_alone_is_recorded_as_shown_without_work() -> None:
    state = fresh()
    step(state, "ANSWER", math=CORRECT, has_work=False)
    assert state.correct_level == "D8" and state.phase == "SOLVED"


def test_correct_after_help_only_partly_closes_the_method_gap() -> None:
    state = fresh()
    state.assisted = True
    step(state, "ANSWER", math=CORRECT, has_work=True)
    assert state.correct_level == "D9" and state.gaps["method"].status == "partial"


def test_missing_constant_is_nearly_done_not_solved() -> None:
    state = fresh()
    decision = step(state, "ANSWER", math={"status": "correct", "flags": ["missing_constant"]}, has_work=True)
    assert decision.diagnosis == "D7" and not state.main_solved


def test_a_solved_question_can_be_discussed_openly() -> None:
    state = fresh()
    step(state, "ANSWER", math=CORRECT, has_work=True)
    assert step(state, "CONCEPT").situation == "after_solved"
    assert step(state, "HELP").situation == "after_solved" and state.main_solved
    assert step(state, "NEW_QUESTION").situation == "switch"


def test_decide_is_deterministic_and_total() -> None:
    """Every turn type, math status and diagnosis gives a decision, and the same inputs give the same one."""
    for turn_type, math, diagnosis, phase in itertools.product(
            TURN_TYPES, (CORRECT, WRONG, UNKNOWN, ABSENT), (*MODEL_DIAGNOSES, None), ("WORKING", "SOLVED", "PARKED")):
        state = fresh()
        state.phase, state.last_situation, state.last_counts = phase, "help", True
        state.main_solved = phase == "SOLVED"
        inputs = TurnInputs(turn_type=turn_type, math=math, saw_last=True, evidence_id="e1",
                            assessment=None if diagnosis is None else verdict(diagnosis))
        first, second = copy.deepcopy(state), copy.deepcopy(state)
        a, b = decide(inputs, first, CFG, []), decide(inputs, second, CFG, [])
        assert a == b and first == second and 0 <= a.level <= MAX_LEVEL


# --------------------------------------------------------------------------- reconciliation
@pytest.mark.parametrize("math, model, confidence, expected", [
    ({"status": "correct", "flags": ["missing_constant"]}, "CORRECT", "high", ("D7", "tool")),
    (CORRECT, None, None, ("CORRECT", "tool")),
    (CORRECT, "D5", "high", ("CORRECT", "tool")),               # a computed result is never overruled
    (UNKNOWN, None, None, ("UNCLEAR", "none")),
    (WRONG, None, None, ("D5", "tool")),
    (WRONG, "CORRECT", "high", ("D5", "tool")),
    (WRONG, "D4", "medium", ("D4", "tool")),
    (ABSENT, "CORRECT", "high", ("UNCLEAR", "none")),
    (UNKNOWN, "CORRECT", "high", ("CORRECT", "model")),
    (UNKNOWN, "CORRECT", "medium", ("UNCLEAR", "none")),
    (UNKNOWN, "D6", "low", ("UNCLEAR", "none")),
    (UNKNOWN, "D6", "high", ("D6", "model")),
    (UNKNOWN, "ON_TRACK", "medium", ("ON_TRACK", "model")),
    (ABSENT, "ON_TRACK", "high", ("ON_TRACK", "model")),
])
def test_reconciliation_table(math, model, confidence, expected) -> None:
    assessment = None if model is None else verdict(model, confidence)
    assert reconcile(math, assessment) == expected


# --------------------------------------------------------------------------- gaps (§5.6)
def update(slot: str, status: str, quote: str, note: str = "shown") -> dict:
    return {"target_slot": slot, "status": status, "evidence_quote": quote, "note": note}


def test_question_starts_with_method_prerequisite_and_mastery_gaps() -> None:
    gaps = build_gaps(make_question())
    assert [g.gap_type for g in gaps.values()] == ["method", "prerequisite", "prerequisite", "mastery"]
    assert all(g.status == "open" for g in gaps.values())


def test_gap_update_needs_the_students_own_words() -> None:
    state, question = fresh(), make_question()
    text = "I set u = x and dv = cos(x) dx"
    accepted, rejected = apply_gap_updates(
        state, [update("correct_approach", "partial", "I set u = x"),
                update("prerequisite_concepts[0]", "closed", "I used the product rule")],      # never said
        question=question, student_text=text, evidence_id="e1", diagnosis="D5")
    assert [a["target_slot"] for a in accepted] == ["correct_approach"]
    assert rejected[0]["why"] == "quote is not in the student's text"
    gap = state.gaps["method"]
    assert gap.status == "partial" and gap.evidence_ids == ["e1"] and gap.history[0]["from"] == "open"


def test_assisted_student_cannot_close_a_gap_through_the_model() -> None:
    state = fresh()
    state.assisted = True
    accepted, _ = apply_gap_updates(state, [update("correct_approach", "closed", "u = x")], question=make_question(),
                                    student_text="u = x", evidence_id="e1", diagnosis="CORRECT")
    assert state.gaps["method"].status == "partial" and accepted[0]["capped"] == "assisted"


def test_closed_gap_reopens_only_on_an_error_with_a_reason() -> None:
    state, question = fresh(), make_question()
    state.gaps["prereq_1"].status = "closed"
    slot = "prerequisite_concepts[1]"
    text = "the antiderivative of cos x is -sin x"
    _, rejected = apply_gap_updates(state, [update(slot, "open", text)], question=question, student_text=text,
                                    evidence_id="e2", diagnosis="CORRECT")
    assert state.gaps["prereq_1"].status == "closed" and rejected
    accepted, _ = apply_gap_updates(state, [update(slot, "open", text, "wrong sign on the antiderivative")],
                                    question=question, student_text=text, evidence_id="e2", diagnosis="D5")
    assert state.gaps["prereq_1"].status == "open" and accepted[0]["reopened"]
    assert state.gaps["prereq_1"].history[-1]["reason"].startswith("reopened: wrong sign")


def test_misconception_becomes_a_gap_only_when_an_error_shows_it() -> None:
    state, text = fresh(), "let u = x cos x"
    proposal = [update("common_misconceptions[0]", "partial", text)]
    _, rejected = apply_gap_updates(state, proposal, question=make_question(), student_text=text,
                                    evidence_id="e1", diagnosis="CORRECT")
    assert "misconception_0" not in state.gaps and "only when an error" in rejected[0]["why"]
    _, rejected = apply_gap_updates(state, [update("common_misconceptions[0]", "open", "never said this")],
                                    question=make_question(), student_text=text, evidence_id="e1", diagnosis="D3")
    assert "misconception_0" not in state.gaps and rejected
    accepted, _ = apply_gap_updates(state, proposal, question=make_question(), student_text=text,
                                    evidence_id="e1", diagnosis="D3")
    gap = state.gaps["misconception_0"]
    assert (gap.gap_type, gap.status, gap.evidence_ids) == ("misconception", "open", ["e1"])
    assert accepted[0]["created"] and choose_target_gap(state, "D3", None) == "common_misconceptions[0]"


def test_target_gap_follows_the_diagnosis_when_the_model_names_none() -> None:
    state = fresh()
    assert choose_target_gap(state, "D2", None) == "prerequisite_concepts[0]"
    assert choose_target_gap(state, "D5", None) == "correct_approach"
    assert choose_target_gap(state, "D5", "prerequisite_concepts[1]") == "prerequisite_concepts[1]"
    state.gaps["prereq_1"].status = "closed"
    assert choose_target_gap(state, "D5", "prerequisite_concepts[1]") == "correct_approach"


def test_model_cannot_change_the_mastery_gap() -> None:
    state = fresh()
    _, rejected = apply_gap_updates(state, [update("mastery", "closed", "x sin(x)")], question=make_question(),
                                    student_text="x sin(x) + cos(x) + C", evidence_id="e1", diagnosis="CORRECT")
    assert state.gaps["mastery"].status == "open" and "only by rule" in rejected[0]["why"]


@pytest.mark.parametrize("technique, name", [
    ("Integration by parts using u = x and dv = cos(x) dx", "Integration by parts"),
    ("Chain rule with inner function x^2", "Chain rule"),
    ("u-substitution: let u = x^2", "u-substitution"),
    ("Integration by parts", "Integration by parts"),
    ("Closed interval method (evaluate at critical points and endpoints)", "Closed interval method"),
])
def test_method_name_drops_the_steps_of_this_problem(technique: str, name: str) -> None:
    assert method_name(technique) == name


def test_method_gap_never_carries_a_key_step_of_the_problem() -> None:
    question = make_question(correct_approach={"technique": "Integration by parts using u = x and dv = cos(x) dx"})
    assert build_gaps(question)["method"].requirement == "Demonstrate: Integration by parts"
