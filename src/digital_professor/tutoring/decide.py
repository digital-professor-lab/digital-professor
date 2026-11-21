"""``decide()``: what situation this turn is, and the bookkeeping that has to be reliable.

Code decides the **situation** (the opening, a request for help, an attempt, a question about an idea, a
solved problem, ...) and keeps the **state**: solved or not, progress or stall, how often the student asked
for help, when to pause. It does not decide how to teach or how much to say. That is the writer's judgment,
inside one hard rule (the student does the solving) that the reply checks enforce.

``decide`` does no I/O and calls no model, so the same inputs always give the same decision. It works on a
copy of the state, which the Engine commits only after the reply is presented.

``notes`` collects, in plain words, which rules fired. It is for the run log only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .judge import reconcile
from .policy import ATTEMPT_TURNS, ERROR_DIAGNOSES, Settings
from .state import QuestionState, choose_target_gap, mark_solved

# Situations with fixed wording: nothing for a model to decide.
FIXED_SITUATIONS = frozenset({"safety", "park", "switch"})


@dataclass(slots=True)
class TurnInputs:
    turn_type: str                              # primary turn type
    opening: bool = False                       # the first message is the question itself
    safety_signal: bool = False
    demand: bool = False                        # the student asked for the answer
    evidence_id: str = ""
    math: Mapping[str, Any] = field(default_factory=lambda: {"status": "absent", "flags": []})
    assessment: Mapping[str, Any] | None = None
    fault: bool = False                         # the judge was needed and failed
    has_work: bool = False
    saw_last: bool = False                      # the student saw the previous reply
    gap_improved: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    situation: str
    level: int                                  # the most help given so far
    diagnosis: str | None = None
    verdict_source: str = "none"
    searches: bool = False                      # course passages are offered to the writer


def decide(i: TurnInputs, s: QuestionState, cfg: Settings, notes: list[str]) -> Decision:
    t = i.turn_type

    def done(situation: str, *, dx: str | None = None, searches: bool = False) -> Decision:
        return Decision(situation, s.help_level, dx, s.verdict_source, searches)

    # Safety always wins, and it holds for the rest of the question.
    if i.safety_signal or s.park_reason == "safety":
        s.phase, s.park_reason = "PARKED", "safety"
        notes.append("A safety phrase was detected, so tutoring stops and the fixed support message is sent.")
        return done("safety")

    # A solved question: the student may go over it freely.
    if s.phase == "SOLVED":
        notes.append("The question is solved, so the tutor may discuss it openly.")
        return done("switch") if t == "NEW_QUESTION" else done("after_solved", searches=True)

    if s.phase == "PARKED":
        s.phase, s.park_reason, s.stall_count, s.turn_count = "WORKING", None, 0, 0
        notes.append("The student came back after a pause, so the counters start again.")

    if not i.fault:
        s.turn_count += 1

    if i.opening:
        notes.append("This is the question itself, not an attempt, so the tutor only gets the student started. "
                     "Nothing about the method is disclosed.")
        return done("open")
    if t == "NEW_QUESTION":
        return done("switch")
    if s.turn_count > cfg.max_turns_per_question:
        s.phase, s.park_reason = "PARKED", "turn_limit"
        notes.append(f"The turn limit ({cfg.max_turns_per_question}) was reached, so the tutor suggests a pause.")
        return done("park")
    if t == "CONCEPT":
        notes.append("The student asked about an idea, so the tutor answers it and returns to the problem.")
        return done("concept", searches=True)
    if t == "OFF_TOPIC":
        return done("redirect")

    stalled = i.saw_last and s.last_counts and not i.fault
    if t in ATTEMPT_TURNS:
        first_attempt = not s.has_attempt
        s.has_attempt = True
        dx, source = reconcile(i.math, i.assessment)
        # Steps on the way count as shown work, whoever read the message.
        s.shown_work = s.shown_work or i.has_work or t == "PARTIAL" or dx == "ON_TRACK"
        notes.append(f"Math check: {i.math.get('status')}. Model verdict: "
                     f"{(i.assessment or {}).get('diagnosis', 'not available')}. Combined: {dx}"
                     f"{' (decided by the math check)' if source == 'tool' else ''}.")
        if dx == "CORRECT":
            return _solved(i, s, source, notes)
        s.last_diagnosis, s.verdict_source = dx, source
        if dx in ERROR_DIAGNOSES or dx == "D0":
            s.error_attempts += 1
        s.target_gap = choose_target_gap(s, dx, (i.assessment or {}).get("target_gap") or s.target_gap)
        if i.gap_improved or first_attempt or dx == "ON_TRACK":
            s.stall_count = 0
            notes.append("The student made progress.")
        elif stalled:
            s.stall_count += 1
            notes.append(f"No progress since the last reply ({s.stall_count} turn(s) in a row).")
        if i.math.get("status") == "incorrect" and not i.has_work:
            s.guess_count += 1
        elif i.has_work:
            s.guess_count = 0
    else:
        dx = s.last_diagnosis
        if t in ("HELP", "DEMAND") or i.demand:
            s.help_requests += 1
            notes.append(f"The student asked for {'the answer' if t == 'DEMAND' or i.demand else 'help'} "
                         f"(request {s.help_requests}).")
        if stalled and t in ("HELP", "DEMAND", "VAGUE", "ACK", "INVALID"):
            s.stall_count += 1

    if s.stall_count >= cfg.max_stall_turns:
        s.phase, s.park_reason = "PARKED", "stall"
        notes.append(f"No progress for {s.stall_count} turns, so the tutor suggests a pause.")
        return done("park", dx=dx)

    situation = "attempt" if t in ATTEMPT_TURNS else "unclear" if t in ("VAGUE", "INVALID", "ACK") else "help"
    if may_name_method(s):
        notes.append("The student has been stuck twice, so the tutor may name the method and bring in the "
                     "textbook. How to help is the tutor model's judgment.")
    else:
        notes.append("First time stuck (or not stuck at all): the tutor may point, but the method and the "
                     "textbook passage are held back until the student is stuck a second time.")
    return done(situation, dx=dx, searches=may_name_method(s))


def may_name_method(s: QuestionState) -> bool:
    """The first time a student is stuck the tutor only points; the method and the textbook passage come
    the second time: two help requests, two wrong attempts, or one of each. Once given, it stays given."""
    return s.main_solved or s.help_level >= 2 or s.help_requests + s.error_attempts >= 2


def _solved(i: TurnInputs, s: QuestionState, source: str, notes: list[str]) -> Decision:
    s.main_solved, s.solved_by, s.verdict_source = True, source, source
    s.last_diagnosis, s.phase = "CORRECT", "SOLVED"
    s.correct_level = "D9" if s.assisted else "D10" if s.shown_work else "D8"
    contradicts = (i.assessment or {}).get("explanation") == "contradicts"
    mark_solved(s, evidence_id=i.evidence_id, source=source, understood=not contradicts)
    if contradicts:
        notes.append("The answer is right but the stated reason is wrong, so the method item stays partial.")
    notes.append({"D8": "Correct, with no work shown.", "D9": "Correct, after help.",
                  "D10": "Correct, with work and without help."}[s.correct_level]
                 + " The question is solved; whether to ask a last 'why' is the tutor model's judgment.")
    return Decision("wrap_up", s.help_level, "CORRECT", source, True)
