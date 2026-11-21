"""The Tutoring Engine used by the integrated demo.

One turn, in order:

    read the message  ->  math check  ->  marking (one model call, when the message is an attempt or
    unclear)  ->  gap updates  ->  decide(): the situation  ->  course passages  ->  the writer model
    writes the reply  ->  reply checks  ->  pending turn

Division of work. Code keeps what has to be reliable: the math check, the learner state with its evidence,
the check that no reply gives the answer away or does a step for the student, and the log. The language
model does the teaching: it reads the student, decides how much help to give and in what form, and writes.

Nothing is committed while a turn runs. The Engine works on a copy of the question state; the copy
replaces the committed state only when Delivery reports that the reply was presented. A reply the student
never saw changes nothing.
"""

from __future__ import annotations

import copy
import os
import re
import time
import unicodedata
from dataclasses import replace
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Protocol
from uuid import uuid4

from digital_professor.interaction.models import (SCHEMA_VERSION, DeliveryResult, LearnerState, StudentEvidence,
                                                  TutoringAction)
from digital_professor.pipeline_view import retrieval_snapshot
from digital_professor.providers import GenerationResult
from digital_professor.retrieval.course_retrieval import describe_index, last_outcome
from digital_professor.retrieval.index import RetrievedPassage

from .decide import FIXED_SITUATIONS, Decision, TurnInputs, decide
from .judge import (PROMPT_VERSION, Judgment, elapsed_ms, judge_turn, read_by_code, read_by_heuristic,
                    safety_signal)
from .math_check import check_math, derive_answer_check
from .policy import (ATTEMPT_TURNS, HELP_NAMES, METHOD_NAMES, MOVE_HELP, MOVES, PARK_TEXT, POLICY_VERSION, SAFETY_TEXT,
                     SWITCH_TEXT, Settings)
from .passage_judge import COVERED_AT, MAX_PASSAGES, OFF_TOPIC_BELOW, default_judge
from .reply import (GUARD_PROMPT_VERSION, WRITER_PROMPT_VERSION, ReplyResult, build_brief, write_and_check)
from .state import QuestionState, apply_gap_updates, build_gaps, method_name

PRODUCER = "grounded_tutoring_engine"
_FIXED_TEXT = {"safety": SAFETY_TEXT, "park": PARK_TEXT, "switch": SWITCH_TEXT}
_FIXED_ACTION = {"safety": "escalate", "park": "escalate", "switch": "elicit"}
_STATES_COURSE_CONTENT = frozenset({"teach_rule", "refer_to_text", "review_prerequisite", "answer_concept",
                                    "similar_example", "discuss_solution"})

# Passages that are lists of words or exercises: they match many searches and teach nothing.
_LISTING = re.compile(r"key\s+terms|review\s+problems|chapter\s+\d+\s+review|^\s*index\b|table\s+of\s+contents|"
                      r"answers?\s+to\s+(?:odd|selected)|^\s*problems\b|^\s*exercises\b", re.IGNORECASE)
_STATES_A_RULE = ("theorem", "definition", "formula")
_NOT_FOR_READING = ("exercise", "solution", "proof")
_PROOF = re.compile(r"^\s*(?:\d+\s+Chapter\s+\d+[^\n]*\n)?\s*Proof\b")
_HELP_WITH_AN_IDEA = re.compile(r"\b(maybe|perhaps|try|tried|use|using|should i|could i|can i|do i|is it|what if|"
                                r"i think|i guess|by)\b|[=^]|\d", re.IGNORECASE)
_NAME_STOP = frozenset({"we", "if", "in", "let", "find", "evaluate", "suppose", "this", "it", "to", "solution",
                        "consider", "show", "use", "there", "when", "then"})
_NUMBERED_ITEM = re.compile(r"(?:^|\s)\d{1,3}\.\s+\S")        # "55. h(t) = ..." : an exercise list
_RUNNING_HEAD = re.compile(r"^\s*(?:\d+\s+Chapter\s+\d+\b.*|\d+(?:\.\d+)*\s+\D.*\s\d{1,4})\s*$")
_MATH_ONLY = re.compile(r"[\sA-Za-z0-9+\-*/^().,=$\\]*")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s")
_SHORT_PASSAGE_WORDS = 60


class TextProvider(Protocol):
    def generate(self, *, system: str, messages: list[dict[str, str]]) -> GenerationResult: ...


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def settings_from_environment() -> Settings:
    """Defaults, with two switches for experiments: ``DIGITAL_PROFESSOR_REPLY_GUARD=0`` turns the guard model
    off (the code checks still run) and ``DIGITAL_PROFESSOR_ENGINE_RETRIEVAL=0`` stops the Engine from
    searching the course material."""
    return Settings(model_guard_enabled=os.getenv("DIGITAL_PROFESSOR_REPLY_GUARD", "1") != "0",
                    retrieval_enabled=os.getenv("DIGITAL_PROFESSOR_ENGINE_RETRIEVAL", "1") != "0")


class GroundedDemoEngine:
    """Stateful Engine for one question: uploaded course passages and an optional language model."""

    def __init__(self, question: Any, retrieval: Any, provider: TextProvider | None,
                 settings: Settings | None = None, course_blocks: Any = None) -> None:
        self.question = question
        self.retrieval = retrieval
        self.provider = provider
        self.settings = settings or settings_from_environment()
        self.policy_version = POLICY_VERSION
        self.qstate = QuestionState(gaps=build_gaps(question))
        # The computed answer check: the builder's, or one read from the wording of the question.
        self.verification = derive_answer_check(question.prompt, getattr(question, "answer_verification", None))
        # The course's blocks in reading order, used to finish a passage that stops at a heading.
        self._following: dict[str, Any] = {}
        blocks = list(course_blocks or ())
        for block, after in zip(blocks, blocks[1:]):
            if block.document_id == after.document_id:
                self._following[block.passage_id] = after
        self.history: list[dict[str, str]] = []
        self.student_texts: list[str] = []
        self.pending: dict[str, TutoringAction] = {}
        self.pending_turns: dict[str, dict[str, Any]] = {}
        self.current_state: LearnerState | None = None
        self.delivery_results: list[DeliveryResult] = []
        self.last_passages: tuple[RetrievedPassage, ...] = ()
        self.last_retrieval: dict[str, Any] = {}
        self.last_retrieval_ms: int = 0
        self.last_generation: GenerationResult | None = None
        self._passage_cache: dict[str, tuple[tuple[RetrievedPassage, ...], dict[str, Any], dict[str, Any]]] = {}
        # Jev scores candidate passages ("does this state the rule?") when it is configured; None: rules only.
        self.passage_judge = default_judge()
        self._jev_record: dict[str, Any] | None = None
        # Run log (see digital_professor.pipeline_view): what each step produced, per turn.
        self.session_trace: dict[str, Any] | None = None
        self.pipeline_turns: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ one turn
    def select_action(self, evidence: StudentEvidence) -> TutoringAction:
        if evidence.validation_status != "valid" or evidence.unresolved_ambiguities:
            raise ValueError("Only confirmed StudentEvidence may reach the Tutoring Engine.")
        cfg = self.settings
        text = evidence.confirmed_content or ""
        state = copy.deepcopy(self.qstate)          # proposed state; committed on delivery
        calls: list[GenerationResult] = []
        trace: dict[str, Any] = {
            "turn_id": evidence.turn_id, "created_at": _now(), "engine_version": 2,
            "evidence": {"evidence_id": evidence.evidence_id, "evidence_kind": evidence.evidence_kind,
                         "confirmed_content": text, "parent_evidence_id": evidence.parent_evidence_id,
                         "modality": "handwriting" if evidence.recognition_ref else "text"},
            "state_before": {"phase": state.phase, "help_level": state.help_level,
                             "stall_count": state.stall_count, "last_move": state.last_move},
            "gaps_before": {g.gap_id: g.status for g in state.gaps.values()},
        }

        # Did the student see the last reply, and was it help?
        saw_last = bool(state.last_action_id and state.last_action_id in evidence.prior_assistance)
        if saw_last and state.help_level >= 1:        # the student has seen more than questions
            state.assisted = True

        # The opening message is the problem itself. It is not an attempt and nothing is marked.
        mine, problem = _squash(text), _squash(self.question.prompt)
        opening = not self.history and bool(mine) and (
            mine in problem or (problem in mine and len(mine) <= 1.3 * len(problem)))

        # Reading (fixed rules first), the math check, and the marking call when it is needed.
        read = read_by_code(text)
        if (read is not None and read.primary == "HELP" and not opening and self.provider is not None
                and len(text.split()) > 3 and _HELP_WITH_AN_IDEA.search(text)):
            read = None                 # "I don't know, maybe by parts?" carries an idea: let the model read it
        if opening:
            read = read or read_by_heuristic(text, has_history=False)
            read.intents, read.final_answer, read.has_work, read.source = ["VAGUE"], None, False, "code"
        math = ({"status": "absent", "reason": None, "method": None, "flags": []} if opening else
                check_math(text, self.verification, final_answer=read.final_answer if read else None))
        need_assessment = read is not None and read.primary in ATTEMPT_TURNS
        # A bare answer that the math check proved needs no marking call: there is nothing else to read.
        proved_bare = read is not None and math["status"] == "correct" and not math["flags"] and not read.has_work
        after_solved = state.phase == "SOLVED"            # nothing is marked once the question is solved
        if after_solved and read is None:
            read = read_by_heuristic(text, has_history=True)
            read.source = "code"
        need_judge = not opening and not proved_bare and not after_solved and (read is None or need_assessment)
        judgment = Judgment()
        if need_judge and self.provider is not None:
            started = time.perf_counter()
            judgment = judge_turn(
                self.provider, question=self.question, student_text=text,
                open_gaps=[g.to_dict() for g in state.open_gaps()], math=math, phase=state.phase,
                last_card=state.last_move, need_read=read is None, need_assessment=need_assessment,
                max_retries=cfg.max_model_retries)
            calls.extend(judgment.calls)
            trace["judge"] = {"model": judgment.calls[-1].model if judgment.calls else None,
                              "ms": elapsed_ms(started), "attempts": judgment.attempts,
                              "failed": judgment.failed, "error": judgment.error, "prompt_version": PROMPT_VERSION,
                              "tokens": {"in": sum(c.input_tokens or 0 for c in judgment.calls),
                                         "out": sum(c.output_tokens or 0 for c in judgment.calls)}}
        else:
            trace["judge"] = {"model": None, "skipped": "opening" if opening else
                              "no_model" if need_judge else "proved_by_math_check" if proved_bare and
                              need_assessment else "already_solved" if after_solved else "fixed_rules"}
        if read is None:
            read = judgment.read or read_by_heuristic(text, has_history=bool(self.history))
            if judgment.read is None and self.provider is not None:
                read.source = "failed"
        read.safety_signal = read.safety_signal or safety_signal(text)
        if read.final_answer and math["status"] != "correct" and not opening:   # the model read out an answer
            math = check_math(text, self.verification, final_answer=read.final_answer)
        is_attempt = read.primary in ATTEMPT_TURNS
        assessment = judgment.assessment if (is_attempt or state.phase == "SOLVED_CHECK") else None
        fault = self.provider is not None and (
            read.source == "failed" or (is_attempt and assessment is None and math["status"] != "correct"))
        trace.update(read=read.to_dict(), turn_type=read.primary, opening=opening, math_check=math,
                     assessment=assessment, answer_check=self.verification)
        if assessment is None:
            trace["assessment_skipped"] = ("opening" if opening else "no_model" if self.provider is None and
                                           is_attempt else "failed" if is_attempt else "turn_type")

        # Gap updates: accepted only with the student's own words as evidence.
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        if assessment:
            accepted, rejected = apply_gap_updates(
                state, assessment["gap_updates"], question=self.question, student_text=text,
                evidence_id=evidence.evidence_id, diagnosis=assessment["diagnosis"])
        gap_improved = any(not a.get("reopened") for a in accepted)
        trace["gap_updates"] = {"accepted": accepted, "rejected": rejected}

        if "DISTRESS" in read.intents:
            state.frustrated = True

        # decide(): the situation and the help level
        notes: list[str] = []
        level_before = state.help_level
        decision: Decision = decide(TurnInputs(
            turn_type=read.primary, opening=opening, safety_signal=read.safety_signal,
            demand="DEMAND" in read.intents, evidence_id=evidence.evidence_id, math=math, assessment=assessment,
            fault=fault, has_work=read.has_work, saw_last=saw_last, gap_improved=gap_improved), state, cfg, notes)
        situation = decision.situation
        fixed = situation in FIXED_SITUATIONS
        brief = None if fixed else build_brief(
            situation=situation, state=state, question=self.question, diagnosis=decision.diagnosis,
            verdict_source=decision.verdict_source, assessment=assessment,
            demand="DEMAND" in read.intents, distress="DISTRESS" in read.intents, guess_limit=cfg.guess_limit,
            student_text=self._language_sample(text))
        trace["gaps_after_assessment"] = {g.gap_id: g.status for g in state.gaps.values()}
        trace["decision"] = {
            "situation": situation, "fixed_text": fixed, "diagnosis": decision.diagnosis,
            "verdict_source": decision.verdict_source, "notes": notes, "target_gap": state.target_gap,
            "help_level": state.help_level, "help_level_before": level_before,
            "help_given": HELP_NAMES[state.help_level], "help_requests": state.help_requests,
            "may_name_method": brief.may_name_method if brief else None,
            "brief": brief.to_dict() if brief else None,
            "next_phase": state.phase, "stall_count": state.stall_count, "park_reason": state.park_reason,
            "policy_version": self.policy_version,
        }

        # Course passages, when the reply will teach or answer a question about an idea.
        passages: tuple[RetrievedPassage, ...] = ()
        passages_text = ""
        if fixed:
            self._no_retrieval(trace, "this reply is a fixed sentence")
        elif not decision.searches:
            self._no_retrieval(trace, "the student has only posed the problem, so nothing is taught yet"
                               if situation == "open" else "the textbook is brought in the second time the "
                               "student is stuck" if situation in ("help", "attempt", "unclear") else
                               "this reply states no course content")
        elif not cfg.retrieval_enabled:
            self._no_retrieval(trace, "retrieval is switched off")
        else:
            passages, passages_text = self._retrieve(situation, state, evidence, text, trace)

        # The reply
        if fixed:
            reply = ReplyResult(_FIXED_TEXT[situation], move=situation)
            trace["writer"] = {"model": None, "fixed_text": True}
        else:
            started = time.perf_counter()
            reply = write_and_check(
                self.provider, brief=brief, question=self.question, student_text=text, history=self.history,
                student_texts=[*self.student_texts, text], passages=passages, passages_text=passages_text,
                cfg=cfg, verification=self.verification)
            calls.extend(reply.calls)
            writer_calls = [c for c in reply.calls if c.model == reply.writer_model] or reply.calls
            trace["writer"] = {
                "model": reply.writer_model, "move": reply.move, "passages_given": len(passages),
                "passage_attached": reply.read, "ms": elapsed_ms(started),
                "latency_ms": sum(c.latency_ms or 0 for c in writer_calls),
                "input_tokens": sum(c.input_tokens or 0 for c in writer_calls),
                "output_tokens": sum(c.output_tokens or 0 for c in writer_calls),
                "prompt_version": WRITER_PROMPT_VERSION,
            }
            trace["reply_checks"] = {
                "failed_first_draft": reply.failed_checks, "rewrites_used": reply.rewrites_used,
                "guard": reply.guard, "guard_ran": reply.guard is not None, "fallback": reply.fallback,
                "guard_prompt_version": GUARD_PROMPT_VERSION,
                "guard_enabled": cfg.model_guard_enabled and self.provider is not None,
            }
        text_out = reply.text
        shown: tuple[RetrievedPassage, ...] = ()
        if passages and not reply.read and not reply.fallback and not fixed:
            reply.read = _page_mentioned(reply.text, passages)
            if "writer" in trace:
                trace["writer"]["passage_attached"] = reply.read
        attached_block = ""
        if reply.read and not reply.fallback:
            chosen = passages[reply.read - 1]
            shown = (chosen, *(p for p in passages if p is not chosen))
            if situation == "wrap_up":      # solved: the page is named and linked, nothing more to read now
                if "writer" in trace:
                    trace["writer"]["passage_attached"] = None
            elif all(p["passage_id"] != chosen.passage.passage_id for p in state.shown_passages):
                attached_block = _reference_block(chosen)        # a passage is attached once, not every turn
                text_out = f"{text_out}\n\n{attached_block}"
                state.shown_passages.append({
                    "passage_id": chosen.passage.passage_id, "pages": _pages(chosen.passage),
                    "name": _short_name(chosen.passage)})
            elif "writer" in trace:
                trace["writer"]["passage_already_shown"] = True
                trace["writer"]["passage_attached"] = None
        elif passages and not reply.fallback and reply.move in _STATES_COURSE_CONTENT:
            shown = passages                      # the reply taught from the passages without naming one
        self.last_passages = shown

        # Pending turn: nothing below takes effect until the reply is presented.
        action_id = f"action-{uuid4()}"
        action_type = _FIXED_ACTION[situation] if fixed else MOVES.get(reply.move, "elicit")
        if not fixed and not reply.fallback:
            given = max(MOVE_HELP.get(reply.move, 0), 2 if attached_block else 0)
            if brief.bound and _names_a_method(reply.text, self.question, [*self.student_texts, text]):
                given = max(given, 2)           # whatever the label says, naming the method is teaching
            state.help_level = max(state.help_level, given)
            trace["decision"]["help_level"] = state.help_level
            trace["decision"]["help_given"] = HELP_NAMES[state.help_level]
        state.last_move = None if reply.fallback else reply.move
        state.last_situation = situation
        state.last_counts = not fixed and not reply.fallback and situation != "redirect"
        state.last_action_id = action_id
        state.state_version += 1
        learner_state = self._learner_state(state, evidence, assessment, reply.move, action_type, decision)
        goal = (f"{situation}: {reply.move}" if fixed else
                f"{situation}; move chosen by the tutor model: {reply.move}")
        action = TutoringAction(
            record_id=action_id, record_type="TutoringAction", schema_version=SCHEMA_VERSION, created_at=_now(),
            producer=PRODUCER, status="selected", correlation_id=evidence.correlation_id, action_id=action_id,
            session_id=evidence.session_id, question_id=evidence.question_id, turn_id=evidence.turn_id,
            learner_state_id=learner_state.learner_state_id, action_type=action_type, pedagogical_goal=goal,
            content=MappingProxyType({"format": "markdown", "text": text_out}),
            grounding_refs=tuple(item.passage.passage_id for item in shown),
            response_expected=MappingProxyType({"expected_kind": "math_with_explanation", "input_modes": ("text",)}),
            allowed_presentations=("text",),
            constraints=MappingProxyType({
                "situation": situation, "move": reply.move, "card": reply.move, "fallback": reply.fallback,
                "answer_disclosure": "allowed" if state.main_solved else "forbidden",
                "verdict": brief.verdict if brief else "none", "states_course_content": bool(shown),
                "policy_version": self.policy_version, "phase": state.phase, "help_level": state.help_level,
            }),
        )
        self.last_generation = _combine(calls, text_out)
        trace.update(action_id=action_id, reply=text_out, action_type=action_type,
                     model_calls=len(calls), model_ms=sum(c.latency_ms or 0 for c in calls))
        self.pending[action_id] = action
        # The conversation the writer sees next turn holds its own words only; it is told separately which
        # passages the student has been shown, so it does not copy them out.
        self.pending_turns[action_id] = {"state": state, "learner_state": learner_state, "trace": trace,
                                         "student_text": text, "reply": text_out, "reply_plain": reply.text}
        return action

    def _language_sample(self, text: str) -> str:
        """The latest message that has words in it: "x^2 + C" alone says nothing about the language."""
        for candidate in (text, *reversed(self.student_texts)):
            if sum(ch.isalpha() for ch in candidate) >= 4 and not _MATH_ONLY.fullmatch(candidate):
                return candidate
        return text

    # ------------------------------------------------------------------ course passages
    def _no_retrieval(self, trace: dict[str, Any], why: str) -> None:
        info = describe_index(self.retrieval)
        self.last_retrieval_ms = 0
        self.last_retrieval = {"mode": info.mode, "backend": info.backend, "status": "not_run", "skipped": why,
                               "warnings": [], "uncovered_needs": []}
        trace["retrieval"] = {"status": "not_run", "skipped": why, "mode": info.mode}

    def _retrieve(self, situation: str, state: QuestionState, evidence: StudentEvidence, text: str,
                  trace: dict[str, Any]) -> tuple[tuple[RetrievedPassage, ...], str]:
        technique = method_name((getattr(self.question, "correct_approach", None) or {}).get("technique") or "")
        specific = getattr(self.question, "status", None) == "partial"   # the schema was built for this question
        context: dict[str, Any] = {
            "question_prompt": self.question.prompt, "student_message": text or None,
            "session_id": evidence.session_id, "turn_id": evidence.turn_id,
            "question_id": evidence.question_id, "correlation_id": evidence.correlation_id,
        }
        if situation in ("concept", "after_solved"):
            # The student asked about an idea: search their own question, with the topic added for context.
            asked = f"{text} ({technique})" if specific and technique else text
            context.update(question_prompt=asked, action_type="explain")
            query, key = f"{asked}\n{self.question.prompt}", None
        else:
            gap = state.gap_by_slot(state.target_gap)
            if gap is not None and gap.gap_type == "prerequisite" and situation != "wrap_up":
                index = int(gap.target_slot.split("[")[1].rstrip("]"))
                topic = self.question.prerequisite_concepts[index].get("name") or gap.requirement
            else:
                topic = technique if specific and technique else None
            query = topic or self.question.prompt
            key = query
            context["action_type"] = "hint"
            if topic:
                context["topic"] = topic
                context["concept_names"] = ()
        if key is not None and key in self._passage_cache:
            passages, self.last_retrieval, snapshot = self._passage_cache[key]
            self.last_retrieval_ms = 0
            trace["retrieval"] = {**snapshot, "ms": 0, "reused": True}
        else:
            started = time.perf_counter()
            found = self.retrieval.search(query, top_k=8, concept_ids=self.question.concept_ids, **context)
            topic_words = context.get("topic") or ""
            self._jev_record = None
            passages, dropped = self._select_passages(found, topic_words)
            jev_found_none = bool(self._jev_record and self._jev_record.get("status") == "ok"
                                  and not any(s["score"] >= COVERED_AT for s in self._jev_record["scores"]))
            if topic_words and (jev_found_none or not any(_names(item.passage, topic_words) for item in passages)):
                # Nothing found states the idea itself (only proofs, examples, neighbours): ask for it directly.
                more = self.retrieval.search(f"{topic_words}: statement of the rule", top_k=8,
                                             concept_ids=self.question.concept_ids,
                                             **{**context, "action_type": "explain"})
                found = (*found, *(m for m in more if all(m.passage.passage_id != f.passage.passage_id for f in found)))
                passages, dropped = self._select_passages(found, topic_words)
            self.last_retrieval_ms = elapsed_ms(started)
            self.last_retrieval = last_outcome(self.retrieval, passages)
            snapshot = retrieval_snapshot(self.retrieval, passages, self.last_retrieval_ms)
            snapshot["found"], snapshot["dropped"] = len(found), dropped
            if self._jev_record is not None:
                snapshot["jev"] = self._jev_record
            trace["retrieval"] = snapshot
            if key is not None:
                self._passage_cache[key] = (passages, self.last_retrieval, snapshot)
        passages_text = "\n\n".join(
            f"PASSAGE {n} — page {item.passage.page_number}"
            f"{'-' + str(item.passage.page_end) if item.passage.page_end not in (None, item.passage.page_number) else ''}"
            f"{', ' + _short_name(item.passage) if _short_name(item.passage) else ''}"
            f" [{item.passage.block_type}]\n{item.passage.text[:1500]}"
            for n, item in enumerate(passages, 1))
        return passages, passages_text

    def _select_passages(self, found: tuple[RetrievedPassage, ...],
                         topic: str = "") -> tuple[tuple[RetrievedPassage, ...], list[dict[str, Any]]]:
        """Keep the passages worth showing a student: never a list of terms or exercises, never a passage
        that works this very problem. A passage that stops at a heading or an introduction is continued
        with the text that follows it in the book, so the student gets the statement itself."""
        problem = _squash((self.verification or {}).get("derivative_of") or (self.verification or {}).get("integrand") or "")
        keep: list[RetrievedPassage] = []
        dropped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in found:
            passage = item.passage
            if passage.passage_id in seen:
                continue
            why = _not_for_reading(passage)
            works_it = lambda text: (len(problem) >= 5 and problem in _squash(text)       # noqa: E731
                                     and not self.qstate.main_solved)
            used: list[str] = []
            if why is None and len(passage.text.split()) < _SHORT_PASSAGE_WORDS and not works_it(passage.text):
                item, used = self._continued(item, stop=works_it)
                passage = item.passage
            if why is None and len(problem) >= 5 and problem in _squash(passage.text) and not self.qstate.main_solved:
                why = "works this very problem"
            elif why is None and len(passage.text.split()) < 12:
                why = "too short to be useful"
            if why:
                dropped.append({"page": passage.page_number, "why": why})
            else:
                seen.update([passage.passage_id, *used])
                keep.append(item)
        # Stable: a passage that states the idea (its opening names the topic, and it is not a worked example)
        # comes first, worked examples last; the search order is kept inside each group.
        def rank(item: RetrievedPassage) -> int:
            passage = item.passage
            if passage.block_type == "example" or re.match(r"\s*EXAMPLE\b", passage.text):
                return 2
            return 0 if passage.block_type in _STATES_A_RULE or _names(passage, topic) else 1
        keep.sort(key=rank)
        if self.passage_judge is not None and topic and keep:
            # Jev scores the best candidates: "does this passage state <topic>?". Passages that state it
            # (>= COVERED_AT) come first, in the rule order above; then partial ones by score. A passage Jev
            # scores below OFF_TOPIC_BELOW is not offered at all: citing no page beats citing the wrong one.
            scored = keep[:MAX_PASSAGES]
            values, record = self.passage_judge.scores(topic, [item.passage.text for item in scored])
            if values is not None:
                by_id = {item.passage.passage_id: value for item, value in zip(scored, values)}
                record["scores"] = [{"page": item.passage.page_number, "score": value}
                                    for item, value in zip(scored, values)]
                for item in scored:
                    if by_id[item.passage.passage_id] < OFF_TOPIC_BELOW:
                        dropped.append({"page": item.passage.page_number,
                                        "why": f"Jev: does not state {topic} ({by_id[item.passage.passage_id]:.2f})"})
                keep = sorted((item for item in scored if by_id[item.passage.passage_id] >= OFF_TOPIC_BELOW),
                              key=lambda item: (by_id[item.passage.passage_id] < COVERED_AT,
                                                rank(item) if by_id[item.passage.passage_id] >= COVERED_AT else 0,
                                                -by_id[item.passage.passage_id]))
            self._jev_record = record
        return tuple(keep[:self.settings.passages_per_reply]), dropped

    def _continued(self, item: RetrievedPassage, *, stop: Any) -> tuple[RetrievedPassage, list[str]]:
        """A short passage plus the blocks that follow it, up to a readable length."""
        passage, text, used = item.passage, item.passage.text, []
        last = passage
        for _ in range(3):
            after = self._following.get(last.passage_id)
            if (after is None or _not_for_reading(after) or stop(after.text)
                    or after.page_number not in (last.page_number, last.page_number + 1)
                    or len(text.split()) >= _SHORT_PASSAGE_WORDS):
                break
            text, last = f"{text}\n{_without_running_head(after.text)}", after
            used.append(after.passage_id)
        if last is passage:
            return item, used
        merged = replace(passage, text=text, page_end=last.page_number,
                         line_end=last.line_end if last.page_number == passage.page_number else passage.line_end)
        return RetrievedPassage(merged, item.score, item.highlight_url), used

    def _learner_state(self, state: QuestionState, evidence: StudentEvidence, assessment: dict[str, Any] | None,
                       move: str, action_type: str, decision: Decision) -> LearnerState:
        open_gaps = tuple(MappingProxyType(g.to_dict()) for g in state.open_gaps())
        closed_gaps = tuple(MappingProxyType(g.to_dict()) for g in state.closed_gaps())
        confidence = (assessment or {}).get("confidence", "low") if decision.diagnosis not in (None, "UNCLEAR") else "low"
        if decision.verdict_source == "tool":
            confidence = "high"
        learner_state_id = f"learner-state-{uuid4()}"
        return LearnerState(
            record_id=learner_state_id, record_type="LearnerState", schema_version=SCHEMA_VERSION, created_at=_now(),
            producer=PRODUCER, status="pending_delivery", correlation_id=evidence.correlation_id,
            learner_state_id=learner_state_id, user_id=evidence.user_id, course_id=evidence.course_id,
            session_id=evidence.session_id, question_id=evidence.question_id,
            based_on_evidence_ids=(evidence.evidence_id,),
            demonstrated=closed_gaps,
            unresolved=open_gaps or (() if state.main_solved else (MappingProxyType({
                "target_slot": "student_reasoning", "status": "open",
                "requirement": "Student's method and reasoning still require evidence."}),)),
            diagnostic_hypotheses=(MappingProxyType({
                "diagnosis": decision.diagnosis, "verdict_source": decision.verdict_source,
                "confidence": confidence, "target_gap": state.target_gap,
                "correct_level": state.correct_level}),) if decision.diagnosis not in (None, "UNCLEAR") else (),
            assistance_history_summary=MappingProxyType({
                "help_level": state.help_level, "stall_count": state.stall_count, "assisted": state.assisted,
                "visible_action_count": len(self.delivery_results) + 1, "last_move": move, "last_card": move,
                "last_action_type": action_type, "policy_version": self.policy_version}),
            state_confidence=MappingProxyType({
                "level": confidence,
                "limitations": () if confidence != "low" else ("No confident verdict on this turn.",)}),
            open_gaps=open_gaps, closed_gaps=closed_gaps, off_target_context=(),
            resolved_when=("All gaps closed." if not open_gaps else f"{len(open_gaps)} gap(s) remain open."),
        )

    # ------------------------------------------------------------------ delivery
    def record_delivery(self, result: DeliveryResult) -> None:
        if result.action_id not in self.pending:
            raise LookupError(f"No pending action for {result.action_id}")
        if result.presentation_status not in {"presented", "partially_presented"}:
            raise ValueError("The action was not presented; state cannot advance.")
        self.pending.pop(result.action_id)
        turn = self.pending_turns.pop(result.action_id)
        self.qstate = turn["state"]
        self.current_state = replace(turn["learner_state"], status="current")
        self.history.extend([{"role": "user", "content": turn["student_text"]},
                             {"role": "assistant", "content": turn.get("reply_plain") or turn["reply"]}])
        self.student_texts.append(turn["student_text"])
        self.delivery_results.append(result)
        trace = turn["trace"]
        trace["delivery"] = {"status": result.presentation_status}
        trace["state_after"] = self.state_snapshot()
        self.pipeline_turns.append(trace)

    def state_snapshot(self) -> dict[str, Any] | None:
        if self.current_state is None:
            return None
        state, q = self.current_state, self.qstate
        return {
            "learner_state_id": state.learner_state_id, "status": state.status,
            "phase": q.phase, "outcome": q.outcome(), "help_level": q.help_level, "stall_count": q.stall_count,
            "turn_count": q.turn_count, "last_diagnosis": q.last_diagnosis, "correct_level": q.correct_level,
            "verdict_source": q.verdict_source, "target_gap": q.target_gap, "last_move": q.last_move,
            "last_card": q.last_move, "assisted": q.assisted, "main_solved": q.main_solved, "solved_by": q.solved_by,
            "park_reason": q.park_reason, "state_version": q.state_version,
            "based_on_evidence_ids": list(state.based_on_evidence_ids),
            "open_gaps": [g.to_dict() for g in q.open_gaps()],
            "closed_gaps": [g.to_dict() for g in q.closed_gaps()],
            "diagnostic_hypotheses": [dict(h) for h in state.diagnostic_hypotheses],
            "assistance_history_summary": dict(state.assistance_history_summary),
            "state_confidence": dict(state.state_confidence),
        }


def _names_a_method(reply: str, question: Any, student_texts: list[str]) -> bool:
    known = re.sub(r"[^a-z]", "", " ".join([question.prompt, *student_texts]).lower())
    names = [*METHOD_NAMES, method_name((getattr(question, "correct_approach", None) or {}).get("technique") or "").lower()]
    lowered = reply.lower()
    return any(len(name) >= 6 and name in lowered and re.sub(r"[^a-z]", "", name).rstrip("s") not in known
               for name in names)


def _page_mentioned(reply: str, passages: tuple[RetrievedPassage, ...]) -> int | None:
    """The passage whose page the reply names ("page 179"), when the writer did not say which to attach."""
    pages = {int(n) for n in re.findall(r"(?:\bpages?\s*|第\s*)(\d{1,4})", reply, flags=re.IGNORECASE)}
    for number, item in enumerate(passages, 1):
        if pages & set(range(item.passage.page_number, (item.passage.page_end or item.passage.page_number) + 1)):
            return number
    for number, item in enumerate(passages, 1):          # "section 4.4.1" / "4.4.1 节"
        section = re.match(r"\s*(\d+\.\d+(?:\.\d+)?)\s", item.passage.heading or item.passage.text[:20])
        if section and re.search(rf"(?<![\d.]){re.escape(section.group(1))}(?![\d.])", reply):
            return number
    return None


def _not_for_reading(passage: Any) -> str | None:
    """Why a passage should not be shown to a student as reading, or None when it is fine."""
    head = " ".join(filter(None, [passage.heading, passage.label, passage.text[:120]]))
    if _LISTING.search(head):
        return "a list of terms or exercises"
    if passage.block_type in _NOT_FOR_READING:
        return f"a block of type {passage.block_type}"
    if _PROOF.match(passage.text):
        return "a proof, not the statement"
    if len(_NUMBERED_ITEM.findall(passage.text)) >= 5:
        return "a list of terms or exercises"
    return None


def _names(passage: Any, topic: str) -> bool:
    """True when the opening of the passage names the topic ("Chain Rule If g is differentiable ...")."""
    words = re.sub(r"[^a-z ]", " ", topic.lower()).split()
    opening = " ".join(filter(None, [passage.heading, passage.label, _without_running_head(passage.text)[:160]])).lower()
    return bool(words) and all(word in opening for word in words)


def _short_name(passage: Any) -> str:
    """A printed name for a passage. Ingestion sometimes stores a whole line as the label; keep its title part."""
    raw = " ".join((passage.label or passage.heading or "").split())
    if _RUNNING_HEAD.match(raw):                # the page header, not a name for this passage
        return ""
    words = raw.split(" ")
    kept: list[str] = []
    for word in words:
        if len(kept) >= 2 and word.lower().strip(".,:") in _NAME_STOP:
            break
        kept.append(word)
        if len(kept) == 8:
            break
    return " ".join(kept).strip(" .,:;")


def _without_running_head(text: str) -> str:
    """Drop the page header a PDF leaves at the top of a page ("160 Chapter 4 Differentiation")."""
    lines = text.splitlines()
    return "\n".join(lines[1:] if len(lines) > 1 and _RUNNING_HEAD.match(lines[0]) else lines)


def _reference_block(item: RetrievedPassage) -> str:
    """The textbook passage the tutor asked the student to read, attached under the reply."""
    passage = item.passage
    text = _tidy_pdf_text(" ".join(unicodedata.normalize("NFKC", _without_running_head(passage.text)).split()))
    name = _short_name(passage)
    if name and text.lower().startswith(name.lower()):      # the title is already in the header line
        text = text[len(name):].lstrip(" .:—-")
    if len(text) > 650:
        cut = text[:650]
        ends = [m.start() for m in _SENTENCE_END.finditer(cut)]
        text = (cut[:ends[-1]] if ends and ends[-1] > 300 else cut.rstrip()) + " …"
    title = f"📖 From your textbook, {_pages(passage)}" + (f" — {name}" if name else "")
    return f"{title}:\n“{text}”"


# PDF text extraction splits some words at kerned capitals ("T o find", "W e have") and pads brackets and
# primes with spaces ("( f ◦ g)", "f ′"). Only these display artifacts are repaired; wording is unchanged.
_KERNED_WORD = re.compile(r"\b([TWY]) (o|he|his|hat|hen|here|herefore|hus|e|ith|ou|our|ake|ry)\b")


def _tidy_pdf_text(text: str) -> str:
    text = _KERNED_WORD.sub(r"\1\2", text)
    text = re.sub(r"([(\[]) +", r"\1", text)
    text = re.sub(r" +([)\]])", r"\1", text)
    return re.sub(r"(\w) +(′+)", r"\1\2", text)


def _pages(passage: Any) -> str:
    return (f"page {passage.page_number}" if passage.page_end in (None, passage.page_number)
            else f"pages {passage.page_number}–{passage.page_end}")


def _combine(calls: list[GenerationResult], text: str) -> GenerationResult | None:
    """One record for the turn's model use: every call's time, tokens and cost added up."""
    if not calls:
        return None
    costs = [c.estimated_cost_usd for c in calls if c.estimated_cost_usd is not None]
    return GenerationResult(
        text=text, model=calls[-1].model, latency_ms=sum(c.latency_ms or 0 for c in calls),
        input_tokens=sum(c.input_tokens or 0 for c in calls), output_tokens=sum(c.output_tokens or 0 for c in calls),
        estimated_cost_usd=sum(costs) if costs else None)
