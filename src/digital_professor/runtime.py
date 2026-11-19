"""Stateful application service for the integrated local demo.

The service coordinates shared records without moving course parsing, retrieval,
tutoring decisions, or presentation into the web layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import time
from types import MappingProxyType
from typing import Any, Protocol
from uuid import uuid4

_log = logging.getLogger(__name__)

from digital_professor.course_context.ingestion import CourseWorkspace
from digital_professor.interaction import (
    HandwritingEvidenceService,
    HandwritingLoggingConfiguration,
    HandwritingRecognitionFailure,
    HandwritingReview,
    HandwritingSubmissionInput,
    InMemoryArtifactStore,
    MockDelivery,
    StudentEvidencePipeline,
    TutoringTurnCoordinator,
    TypedSubmissionInput,
)
from digital_professor.interaction.models import (
    SCHEMA_VERSION,
    DeliveryResult,
    LearnerState,
    StudentEvidence,
    TutoringAction,
    TutoringTurnFailure,
)
from digital_professor.interaction.ports import HandwritingRecognizerPort
from digital_professor.providers import GenerationResult
from digital_professor.retrieval.index import CourseRetrievalIndex, RetrievedPassage


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TextProvider(Protocol):
    def generate(self, *, system: str, messages: list[dict[str, str]]) -> GenerationResult: ...


class TimestampedTraceStore:
    """Persist operational and optional diagnostic events outside the UI."""

    def __init__(self, root: Path | str = "logs") -> None:
        self.root = Path(root)

    def write(self, session_id: str, event: dict[str, Any]) -> Path:
        created_at = str(event["created_at"])
        day = created_at[:10]
        clock = created_at[11:23].replace(":", "").replace(".", "-")
        event_name = str(event.get("event", "event")).replace("/", "-")
        folder = self.root / day / session_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{clock}_{event_name}_{uuid4().hex[:8]}.json"
        path.write_text(
            json.dumps(event, indent=2, ensure_ascii=False, default=_json_default) + "\n",
            encoding="utf-8",
        )
        return path

    def read_session(self, session_id: str) -> list[dict[str, Any]]:
        """Read one session's timestamped records without exposing arbitrary paths."""
        if not session_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in session_id):
            raise ValueError("Invalid session identifier.")
        records: list[dict[str, Any]] = []
        for path in sorted(self.root.glob(f"????-??-??/{session_id}/*.json")):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return records

    def write_artifact(
        self, session_id: str, *, filename: str, data: bytes
    ) -> dict[str, Any]:
        """Preserve an original binary submission beside its session records."""
        created_at = _now()
        day = created_at[:10]
        safe_name = "".join(
            character if character.isalnum() or character in ".-_" else "_"
            for character in Path(filename).name
        ) or "submission.bin"
        folder = self.root / day / session_id / "artifacts"
        folder.mkdir(parents=True, exist_ok=True)
        clock = created_at[11:23].replace(":", "").replace(".", "-")
        path = folder / f"{clock}_{uuid4().hex[:8]}_{safe_name}"
        path.write_bytes(data)
        return {
            "backend_path": str(path),
            "sha256": hashlib.sha256(data).hexdigest(),
            "byte_count": len(data),
        }


@dataclass(slots=True)
class Gap:
    """Tracks whether a single requirement from the QuestionSchema has been demonstrated."""

    gap_id: str
    gap_type: str  # method | prerequisite | mastery | misconception
    target_slot: str  # e.g. "correct_approach", "prerequisite_concepts[0]"
    requirement: str
    status: str = "open"  # open | partial | closed
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QuestionState:
    """Per-question mutable state tracked by the Engine during a tutoring session."""

    phase: str = "ATTEMPTING"
    help_level: int = 0
    stall_count: int = 0
    turn_count: int = 0
    assisted: bool = False
    main_solved: bool = False
    solved_by: str | None = None
    last_diagnosis: str | None = None
    last_assessment: dict[str, Any] | None = None
    target_gap: str | None = None
    gaps: dict[str, Gap] = field(default_factory=dict)

    def open_gaps(self) -> list[Gap]:
        return [g for g in self.gaps.values() if g.status in ("open", "partial")]

    def closed_gaps(self) -> list[Gap]:
        return [g for g in self.gaps.values() if g.status == "closed"]

    def apply_updates(
        self, updates: list[dict], evidence_id: str, student_text: str
    ) -> None:
        order = {"open": 0, "partial": 1, "closed": 2}
        for upd in updates:
            if not isinstance(upd, dict):
                continue
            slot = upd.get("target_slot")
            new_status = upd.get("status")
            quote = upd.get("evidence_quote", "")
            if not slot or new_status not in order:
                continue
            gap = next((g for g in self.gaps.values() if g.target_slot == slot), None)
            if gap is None:
                continue
            if quote and quote not in student_text:
                continue
            if order[new_status] > order.get(gap.status, 0):
                gap.status = new_status
                gap.evidence_ids.append(evidence_id)


@dataclass(slots=True)
class RuntimeQuestionSchema:
    record_id: str
    record_type: str
    schema_version: str
    created_at: str
    producer: str
    status: str
    correlation_id: str
    question_schema_version: str
    question_id: str
    course_id: str
    module_id: str
    prompt: str
    origin: str
    concept_ids: tuple[str, ...]
    concept_names: tuple[str, ...]
    question_type: str
    expected_response_modes: tuple[str, ...]
    learning_objectives: tuple[dict[str, str], ...]
    correct_approach: dict[str, str]
    reference_answer: str
    source_ids: tuple[str, ...]
    source_reference: dict[str, Any]
    provenance: str
    built_from: dict[str, str]
    validation_status: str
    requires_human_review: bool
    common_misconceptions: tuple[dict, ...] = ()
    prerequisite_concepts: tuple[dict, ...] = ()
    answer_verification: dict[str, Any] | None = None


@dataclass(slots=True)
class DemoSession:
    session_id: str
    user_id: str
    course: CourseWorkspace
    question: RuntimeQuestionSchema
    diagnostic_logging: bool
    coordinator: TutoringTurnCoordinator
    engine: "GroundedDemoEngine"
    attempt_id: str
    turn_count: int = 0
    prior_submission_id: str | None = None
    prior_evidence_id: str | None = None
    prior_action_id: str | None = None
    logs: list[dict[str, Any]] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)
    handwriting_service: HandwritingEvidenceService | None = None
    total_estimated_cost_usd: float = 0.0
    question_schema_dict: dict[str, Any] | None = None


class GroundedDemoEngine:
    """Stateful demo Engine using uploaded passages and an optional real model."""

    def __init__(
        self,
        question: RuntimeQuestionSchema,
        retrieval: CourseRetrievalIndex,
        provider: TextProvider | None,
    ) -> None:
        self.question = question
        self.retrieval = retrieval
        self.provider = provider
        self.pending: dict[str, TutoringAction] = {}
        self.history: list[dict[str, str]] = []
        self.last_passages: tuple[RetrievedPassage, ...] = ()
        self.last_retrieval_ms: int = 0
        self.last_generation: GenerationResult | None = None
        self.delivery_results: list[DeliveryResult] = []
        self.current_state: LearnerState | None = None
        self.pending_states: dict[str, tuple[LearnerState, str, int]] = {}
        self.qstate: QuestionState = QuestionState(gaps=_build_gaps_from_qs(question))
        self.policy_version = "demo-tutoring-policy@0.2"

    def select_action(self, evidence: StudentEvidence) -> TutoringAction:
        if evidence.validation_status != "valid" or evidence.unresolved_ambiguities:
            raise ValueError("Only confirmed StudentEvidence may reach the Tutoring Engine.")
        student_text = evidence.confirmed_content or ""

        # --- quick synchronous checks (no LLM) ---
        math_correct = _check_student_math(student_text, self.question.answer_verification)
        turn_type = _read_turn(student_text, has_history=bool(self.history))

        # --- retrieval (fast, independent of LLM) ---
        # Prepend the technique name so lexical search finds the right textbook section
        # even when the student's phrasing ("how to take integral of xcos(x)") has no
        # term overlap with the technique section heading ("integration by parts").
        _technique = (self.question.correct_approach or {}).get("technique", "")
        query = "\n".join(p for p in (_technique, self.question.prompt, student_text) if p)
        retrieval_started = time.perf_counter()
        passages = self.retrieval.search(
            query, top_k=4, concept_ids=self.question.concept_ids
        )
        self.last_retrieval_ms = round((time.perf_counter() - retrieval_started) * 1000)
        self.last_passages = passages
        context = "\n\n".join(
            f"SOURCE {index}: {item.passage.filename}, page {item.passage.page_number}, "
            f"lines {item.passage.line_start}-{item.passage.line_end}\n{item.passage.text}"
            for index, item in enumerate(passages, 1)
        )

        # --- assessment (LLM) — only needed when student is making an attempt ---
        _empty_assessment: dict[str, Any] = {
            "diagnosis": "UNCLEAR",
            "confidence": "low",
            "target_gap": None,
            "gap_updates": [],
            "explanation": "none",
            "summary": "",
        }
        if turn_type in ("ATTEMPT", "REASONING"):
            assessment = self.assess_turn(student_text, evidence.evidence_id)
        else:
            assessment = _empty_assessment
        if math_correct is True and assessment.get("diagnosis") != "CORRECT":
            assessment = {
                **assessment,
                "diagnosis": "CORRECT",
                "confidence": "high",
                "summary": "SymPy verified: antiderivative is correct.",
            }
        self.qstate.apply_updates(
            assessment.get("gap_updates") or [], evidence.evidence_id, student_text
        )
        if assessment.get("diagnosis") not in (None, "UNCLEAR"):
            self.qstate.last_diagnosis = assessment["diagnosis"]
        self.qstate.last_assessment = assessment
        self.qstate.turn_count += 1

        # --- policy decision (uses turn_type + assessment together) ---
        action_type, next_phase, next_help_level, action_instruction = self._select_policy(
            student_text, turn_type=turn_type, math_correct=math_correct, assessment=assessment
        )
        self._tick_stall(turn_type, assessment.get("diagnosis"))

        if self.provider is None:
            reply = self._local_reply(student_text, passages, action_type)
            self.last_generation = None
        else:
            q = self.question
            _eliciting = action_type in ("probe", "clarify")
            qs_context = _qs_system_context(q, hide_technique=_eliciting)
            assessment_context = _assessment_context(assessment)
            # On probe/clarify turns withhold course passages from the LLM — the
            # passages often contain worked examples of the target technique, and
            # the model will cite them even when told not to hint.
            llm_context = "" if _eliciting else context
            result = self.provider.generate(
                system=(
                    "You are a course-grounded tutor. Use only the supplied course passages "
                    "for course-specific claims. Do not reveal a full answer immediately. "
                    f"Selected tutoring action: {action_type}. {action_instruction} "
                    "State when the "
                    "sources do not support a claim. Keep the response under 180 words. "
                    "Write mathematical notation as valid LaTeX: use $...$ inline and "
                    "$$...$$ for important standalone equations. Do not use Unicode math "
                    "as a substitute when LaTeX is clearer.\n\n"
                    f"{qs_context}"
                    f"{assessment_context}"
                    f"COURSE PASSAGES:\n{llm_context or '[no supporting passage found]'}"
                ),
                messages=[
                    *self.history[-8:],
                    {"role": "user", "content": student_text},
                ],
            )
            reply = result.text
            self.last_generation = result

        action_id = f"action-{uuid4()}"
        learner_state_id = f"learner-state-{uuid4()}"
        _conf = (
            assessment.get("confidence", "low")
            if assessment.get("diagnosis") not in (None, "UNCLEAR")
            else "low"
        )
        _open = self.qstate.open_gaps()
        _closed = self.qstate.closed_gaps()
        pending_state = LearnerState(
            record_id=learner_state_id,
            record_type="LearnerState",
            schema_version=SCHEMA_VERSION,
            created_at=_now(),
            producer="grounded_demo_tutoring_engine",
            status="pending_delivery",
            correlation_id=evidence.correlation_id,
            learner_state_id=learner_state_id,
            user_id=evidence.user_id,
            course_id=evidence.course_id,
            session_id=evidence.session_id,
            question_id=evidence.question_id,
            based_on_evidence_ids=(evidence.evidence_id,),
            demonstrated=tuple(MappingProxyType(_gap_dict(g)) for g in _closed),
            unresolved=tuple(MappingProxyType(_gap_dict(g)) for g in _open)
            or (
                MappingProxyType(
                    {
                        "target_slot": "student_reasoning",
                        "requirement": "Student's method and reasoning still require evidence.",
                        "status": "open",
                    }
                ),
            ),
            diagnostic_hypotheses=(
                MappingProxyType(
                    {
                        "diagnosis": assessment.get("diagnosis", "UNCLEAR"),
                        "confidence": assessment.get("confidence", "low"),
                        "target_gap": assessment.get("target_gap"),
                        "summary": assessment.get("summary", ""),
                    }
                ),
            )
            if assessment.get("diagnosis") not in (None, "UNCLEAR")
            else (),
            assistance_history_summary=MappingProxyType(
                {
                    "help_level": next_help_level,
                    "visible_action_count": len(self.delivery_results) + 1,
                    "last_action_type": action_type,
                    "policy_version": self.policy_version,
                }
            ),
            state_confidence=MappingProxyType(
                {
                    "level": _conf,
                    "limitations": ()
                    if _conf != "low"
                    else ("Assessment confidence is low or unavailable.",),
                }
            ),
            open_gaps=tuple(MappingProxyType(_gap_dict(g)) for g in _open),
            closed_gaps=tuple(MappingProxyType(_gap_dict(g)) for g in _closed),
            off_target_context=(),
            resolved_when=(
                "All gaps closed."
                if not _open
                else f"{len(_open)} gap(s) remain open."
            ),
        )
        action = TutoringAction(
            record_id=action_id,
            record_type="TutoringAction",
            schema_version=SCHEMA_VERSION,
            created_at=_now(),
            producer="grounded_demo_tutoring_engine",
            status="selected",
            correlation_id=evidence.correlation_id,
            action_id=action_id,
            session_id=evidence.session_id,
            question_id=evidence.question_id,
            turn_id=evidence.turn_id,
            learner_state_id=learner_state_id,
            action_type=action_type,
            pedagogical_goal=(
                "Use course evidence to elicit the student's next reasoning step."
                if passages
                else "Clarify the request because no supporting course passage was found."
            ),
            content=MappingProxyType({"format": "markdown", "text": reply}),
            grounding_refs=tuple(item.passage.passage_id for item in passages),
            response_expected=MappingProxyType(
                {"expected_kind": "math_with_explanation", "input_modes": ("text",)}
            ),
            allowed_presentations=("text",),
            constraints=MappingProxyType(
                {
                    "answer_disclosure": "next_step_only",
                    "policy_version": self.policy_version,
                    "phase": next_phase,
                    "help_level": next_help_level,
                }
            ),
        )
        self.pending[action_id] = action
        self.pending_states[action_id] = (pending_state, next_phase, next_help_level)
        self.history.extend(
            [
                {"role": "user", "content": student_text},
                {"role": "assistant", "content": reply},
            ]
        )
        return action

    def record_delivery(self, result: DeliveryResult) -> None:
        if result.action_id not in self.pending:
            raise LookupError(f"No pending action for {result.action_id}")
        if result.presentation_status not in {"presented", "partially_presented"}:
            raise ValueError("The action was not presented; state cannot advance.")
        self.pending.pop(result.action_id)
        pending_state, phase, help_level = self.pending_states.pop(result.action_id)
        self.current_state = replace(pending_state, status="current")
        self.qstate.phase = phase
        self.qstate.help_level = help_level
        self.delivery_results.append(result)

    def state_snapshot(self) -> dict[str, Any] | None:
        if self.current_state is None:
            return None
        state = self.current_state
        return {
            "learner_state_id": state.learner_state_id,
            "status": state.status,
            "phase": self.qstate.phase,
            "help_level": self.qstate.help_level,
            "last_diagnosis": self.qstate.last_diagnosis,
            "based_on_evidence_ids": list(state.based_on_evidence_ids),
            "open_gaps": [_gap_dict(g) for g in self.qstate.open_gaps()],
            "closed_gaps": [_gap_dict(g) for g in self.qstate.closed_gaps()],
            "diagnostic_hypotheses": [dict(h) for h in state.diagnostic_hypotheses],
            "assistance_history_summary": dict(state.assistance_history_summary),
            "state_confidence": dict(state.state_confidence),
        }

    def _select_policy(
        self,
        student_text: str,
        *,
        turn_type: str = "ATTEMPT",
        math_correct: bool | None = None,
        assessment: dict[str, Any] | None = None,
    ) -> tuple[str, str, int, str]:
        return _decide(
            turn_type=turn_type,
            math_correct=math_correct,
            diagnosis=(assessment or {}).get("diagnosis"),
            help_level=self.qstate.help_level,
            stall_count=self.qstate.stall_count,
            has_history=bool(self.history),
            phase=self.qstate.phase,
        )

    def _tick_stall(self, turn_type: str, diagnosis: str | None) -> None:
        """Advance the stall counter after each turn so _decide can escalate help."""
        if turn_type == "HELP" or diagnosis in ("CORRECT", "D5"):
            self.qstate.stall_count = 0
        elif turn_type == "ATTEMPT" and diagnosis not in (None, "UNCLEAR"):
            self.qstate.stall_count += 1

    def assess_turn(self, student_text: str, evidence_id: str) -> dict[str, Any]:
        """Call the assessor model and return a TurnAssessment dict. Never raises."""
        _empty: dict[str, Any] = {
            "diagnosis": "UNCLEAR",
            "confidence": "low",
            "target_gap": None,
            "gap_updates": [],
            "explanation": "none",
            "summary": "",
        }
        q = self.question
        if self.provider is None or not (
            q.correct_approach or q.prerequisite_concepts or q.common_misconceptions
        ):
            return _empty
        prereqs = (
            "\n".join(
                f"- [{i}] {p.get('name', '')}: {p.get('relevance', '')}"
                for i, p in enumerate(q.prerequisite_concepts)
            )
            or "(none)"
        )
        misc_cues = (
            "\n".join(
                f"- [{i}] cue: {m.get('cue', '')} | mitigation: {m.get('mitigation', '')}"
                for i, m in enumerate(q.common_misconceptions)
            )
            or "(none)"
        )
        gaps_text = (
            "\n".join(
                f"- {g.target_slot} ({g.status}): {g.requirement}"
                for g in self.qstate.gaps.values()
            )
            or "(none)"
        )
        system = (
            "You are a math-tutoring assessor. Examine the student's response and "
            "identify gaps. Output ONLY a JSON object.\n\n"
            f"Question: {q.prompt}\n"
            f"Correct approach: {(q.correct_approach or {}).get('technique', '')}\n"
            f"Reference answer (DO NOT REVEAL TO STUDENT): {q.reference_answer}\n\n"
            f"Prerequisites:\n{prereqs}\n\n"
            f"Misconception cues:\n{misc_cues}\n\n"
            f"Current gaps:\n{gaps_text}"
        )
        user = (
            f"Student response:\n{student_text}\n\n"
            'Output JSON: {"diagnosis":"D0|D1|D2|D3|D4|D5|D6|D7|CORRECT|UNCLEAR",'
            '"confidence":"high|medium|low",'
            '"target_gap":"<target_slot or null>",'
            '"explanation":"sound|weak|contradicts|none",'
            '"gap_updates":[{"target_slot":"...","status":"open|partial|closed",'
            '"evidence_quote":"verbatim quote from student text","note":"..."}],'
            '"summary":"one sentence"}'
        )
        try:
            from digital_professor.course_context.builder import _extract_json_text

            result = self.provider.generate(
                system=system, messages=[{"role": "user", "content": user}]
            )
            assessment: dict[str, Any] = json.loads(_extract_json_text(result.text))
            return assessment
        except Exception as exc:
            _log.warning("assess_turn failed: %s", exc)
            return _empty

    @staticmethod
    def _local_reply(
        student_text: str,
        passages: tuple[RetrievedPassage, ...],
        action_type: str,
    ) -> str:
        if not passages:
            return (
                "I could not find a supporting passage in the uploaded course material. "
                "Could you name the topic or section you are working from?"
            )
        heading = passages[0].passage.heading or "the retrieved course passage"
        if action_type == "probe":
            return "Show your first step and explain the reasoning behind it."
        if action_type == "clarify":
            return "Could you be more specific about what you tried? Walk me through your current approach."
        if action_type == "hint":
            return f"The course material points to {heading}. What is the smallest next step you can take from there?"
        if action_type == "explain":
            return f"The relevant section is {heading}. Which part of that method does your work currently use?"
        if action_type in ("check_understanding", "nudge_calculation"):
            return "Your method looks right. Check the calculation in your last step — what do you get?"
        if action_type == "address_misconception":
            return f"There is a misconception in that step. Review {heading} and try again."
        if action_type == "prereq_check":
            return f"This relies on a prerequisite. Can you state what {heading} says about the technique you need?"
        if action_type in ("redirect",):
            return f"That approach won't quite work here. Look at {heading} and think about which method applies."
        if action_type == "confirm":
            return "Correct! Well done. Can you explain in your own words why that method gave the right answer?"
        if action_type == "wrap_up":
            return "You've solved this one. Would you like a follow-up challenge on the same topic?"
        return "Please show the next step and explain why you chose it."



class DemoApplication:
    """In-memory application boundary used by the API and replaceable later."""

    def __init__(
        self,
        provider: TextProvider | None = None,
        *,
        trace_store: TimestampedTraceStore | None = None,
    ) -> None:
        self.provider = provider
        self.trace_store = trace_store or TimestampedTraceStore()
        self.courses: dict[str, CourseWorkspace] = {}
        self.indexes: dict[str, CourseRetrievalIndex] = {}
        self.sessions: dict[str, DemoSession] = {}

    def publish_course(self, workspace: CourseWorkspace) -> None:
        self.courses[workspace.course_id] = workspace
        self.indexes[workspace.course_id] = CourseRetrievalIndex(workspace)

    def rename_course(self, course_id: str, course_name: str) -> CourseWorkspace:
        course = self.courses.get(course_id)
        if course is None:
            raise LookupError(f"Published course not found: {course_id}")
        clean_name = course_name.strip()
        if not clean_name:
            raise ValueError("Course name cannot be empty.")
        renamed = replace(course, course_name=clean_name)
        self.courses[course_id] = renamed
        for session in self.sessions.values():
            if session.course.course_id == course_id:
                session.course = renamed
        return renamed

    def update_course_context(
        self, course_id: str, updates: list[dict]
    ) -> CourseWorkspace:
        """Apply field edits to the in-memory CourseContext and mark as reviewed."""
        from digital_professor.course_context.generator import validate_and_flag

        course = self.courses.get(course_id)
        if course is None:
            raise LookupError(f"Published course not found: {course_id}")
        if course.course_context is None:
            raise ValueError("No CourseContext to update.")
        cc = json.loads(json.dumps(course.course_context))
        for update in updates:
            entity = update["entity"]
            record_id = update["id"]
            field = update["field"]
            value = update["value"]
            if entity == "Course":
                if isinstance(cc.get("Course"), dict):
                    cc["Course"][field] = value
            else:
                for record in cc.get(entity, []):
                    if isinstance(record, dict) and record.get("id") == record_id:
                        record[field] = value
                        break
        try:
            status, review = validate_and_flag(cc)
            if status == "validation_failed":
                status = "review_required"
            elif status in ("validated", "review_required"):
                status = "reviewed"
        except Exception:
            status, review = "reviewed", course.course_context_review
        updated = replace(
            course,
            course_context=cc,
            course_context_status=status,
            course_context_review=review,
        )
        self.courses[course_id] = updated
        return updated

    def start_session(
        self,
        *,
        course_id: str,
        question: str,
        user_id: str = "local-demo-student",
        diagnostic_logging: bool = False,
    ) -> DemoSession:
        from digital_professor.course_context.builder import (
            BuildError,
            LLMAdapter,
            build_runtime_question_schema,
        )

        course = self.courses.get(course_id)
        if course is None:
            raise LookupError(f"Published course not found: {course_id}")
        # Initial search without concept_ids (not yet known); re-searched below once QS is built.
        passages = self.indexes[course_id].search(question, top_k=4)
        correlation_id = f"correlation-{uuid4()}"
        source_ids = tuple(dict.fromkeys(item.passage.document_id for item in passages))

        qs_dict: dict[str, Any] | None = None
        schema: RuntimeQuestionSchema

        if course.course_context and self.provider is not None:
            try:
                cc = course.course_context
                cc_text = json.dumps(cc, ensure_ascii=False, sort_keys=True)
                cc_sha256 = hashlib.sha256(cc_text.encode("utf-8")).hexdigest()
                adapter = LLMAdapter(self.provider)
                qs_dict = build_runtime_question_schema(cc, cc_sha256, question, adapter)
                concept_ids = tuple(qs_dict["concept_ids"])
                concept_names = tuple(qs_dict.get("concept_names") or ())
                # Re-search: include technique name so the lexical index finds the right
                # textbook section even when the question text has no term overlap with it.
                _qs_technique = (qs_dict.get("correct_approach") or {}).get("technique", "")
                _qs_query = "\n".join(p for p in (_qs_technique, question) if p)
                passages = self.indexes[course_id].search(
                    _qs_query, top_k=4, concept_ids=concept_ids
                )
                source_ids = tuple(dict.fromkeys(item.passage.document_id for item in passages))
                schema = RuntimeQuestionSchema(
                    record_id=qs_dict["question_id"],
                    record_type="QuestionSchema",
                    schema_version=SCHEMA_VERSION,
                    created_at=_now(),
                    producer="course_context_runtime_builder",
                    status="partial",
                    correlation_id=correlation_id,
                    question_schema_version=qs_dict.get("question_schema_version", "1.0"),
                    question_id=qs_dict["question_id"],
                    course_id=course_id,
                    module_id=qs_dict.get("module_id") or f"{course_id}.runtime",
                    prompt=question,
                    origin="runtime",
                    concept_ids=concept_ids,
                    concept_names=concept_names,
                    question_type=qs_dict.get("question_type", "worked_problem"),
                    expected_response_modes=tuple(
                        qs_dict.get("expected_response_modes") or ()
                    ),
                    learning_objectives=tuple(qs_dict.get("learning_objectives") or ()),
                    correct_approach=qs_dict.get("correct_approach") or {},
                    reference_answer=qs_dict.get("reference_answer", ""),
                    source_ids=source_ids,
                    source_reference={
                        **(qs_dict.get("source_reference") or {}),
                        "source_ids": list(source_ids),
                        "citation": [item.passage.filename for item in passages],
                        "grounding": [item.passage.passage_id for item in passages],
                    },
                    provenance=qs_dict.get("provenance", "ai_inferred"),
                    built_from=qs_dict.get("built_from") or {},
                    validation_status="partial",
                    requires_human_review=True,
                    common_misconceptions=tuple(
                        qs_dict.get("common_misconceptions") or ()
                    ),
                    prerequisite_concepts=tuple(
                        qs_dict.get("prerequisite_concepts") or ()
                    ),
                    answer_verification=qs_dict.get("answer_verification"),
                )
            except (BuildError, Exception) as exc:
                qs_dict = None
                _log.warning("QuestionSchema builder failed, falling back to stub: %s", exc)

        if qs_dict is None:
            if course.course_context:
                concepts, concept_ids = _concepts_from_course_context(
                    course_id, course.course_context
                )
            else:
                concepts = tuple(course.topics[:8])
                concept_ids = tuple(
                    f"{course_id}.runtime.{_slug_topic(value)}" for value in concepts
                )
            question_id = f"{course_id}.runtime-{uuid4().hex[:12]}"
            schema = RuntimeQuestionSchema(
                record_id=question_id,
                record_type="QuestionSchema",
                schema_version=SCHEMA_VERSION,
                created_at=_now(),
                producer="course_context_runtime_builder",
                status="review_required",
                correlation_id=correlation_id,
                question_schema_version="0.1",
                question_id=question_id,
                course_id=course_id,
                module_id=f"{course_id}.runtime",
                prompt=question,
                origin="runtime",
                concept_ids=concept_ids,
                concept_names=concepts,
                question_type="open_question",
                expected_response_modes=("text", "equation", "steps", "explanation"),
                learning_objectives=tuple(
                    {
                        "id": f"objective-{index}",
                        "text": f"Explain and apply {name}.",
                        "bloom_level": "apply",
                    }
                    for index, name in enumerate(concepts[:3], 1)
                ),
                correct_approach={
                    "technique": "course-grounded guided reasoning",
                    "justification": "The runtime question has no instructor-authored solution yet.",
                },
                reference_answer=f"restricted://{question_id}/pending-review",
                source_ids=source_ids,
                source_reference={
                    "concept_ids": list(concept_ids),
                    "source_ids": list(source_ids),
                    "sibling_question_ids": [],
                    "citation": [item.passage.filename for item in passages],
                    "grounding": [item.passage.passage_id for item in passages],
                },
                provenance="source_backed" if passages else "ai_inferred",
                built_from={
                    "course_context_schema_version": "demo-0.1",
                    "content_sha256": "+".join(
                        document.content_version for document in course.documents
                    ),
                },
                validation_status="partial",
                requires_human_review=True,
            )

        engine = GroundedDemoEngine(schema, self.indexes[course_id], self.provider)
        coordinator = TutoringTurnCoordinator(
            StudentEvidencePipeline(InMemoryArtifactStore()), engine, MockDelivery()
        )
        session = DemoSession(
            session_id=f"session-{uuid4()}",
            user_id=user_id,
            course=course,
            question=schema,
            diagnostic_logging=diagnostic_logging,
            coordinator=coordinator,
            engine=engine,
            attempt_id=f"attempt-{uuid4()}",
            question_schema_dict=qs_dict,
        )
        self.sessions[session.session_id] = session
        self._log(
            session,
            "session_started",
            "course_context -> interaction",
            {"record_ref": schema.record_id},
        )
        self.trace_store.write(
            session.session_id,
            {
                "created_at": _now(),
                "event": "question_schema_record",
                "handoff": "course_context -> tutoring_engine",
                "issue": None,
                "record_ref": schema.record_id,
                "record": _question_dict(schema),
            },
        )
        return session

    def run_turn(self, session_id: str, text: str) -> dict[str, Any]:
        started = time.perf_counter()
        session = self.sessions.get(session_id)
        if session is None:
            raise LookupError(f"Session not found: {session_id}")
        session.turn_count += 1
        turn_id = f"turn-{session.turn_count}"
        request = TypedSubmissionInput(
            user_id=session.user_id,
            course_id=session.course.course_id,
            session_id=session.session_id,
            turn_id=turn_id,
            question_id=session.question.question_id,
            attempt_id=session.attempt_id,
            submitted_text=text,
            evidence_kind="initial_attempt" if session.turn_count == 1 else "follow_up",
            parent_submission_id=session.prior_submission_id,
            parent_evidence_id=session.prior_evidence_id,
            response_to_action_id=session.prior_action_id,
            consent_flags={"diagnostic_logging": session.diagnostic_logging},
        )
        try:
            result = session.coordinator.run_typed_turn(request)
        except Exception as error:
            self._log(
                session,
                "turn_failed",
                "interaction",
                {"turn_id": turn_id, "issue": str(error)},
                issue=str(error),
            )
            raise
        if isinstance(result, TutoringTurnFailure):
            self._log(
                session,
                "turn_failed",
                result.failed_stage,
                {"turn_id": turn_id, "issue": result.message},
                issue=result.message,
            )
            raise RuntimeError(result.message)

        session.prior_submission_id = result.submission.submission_id
        session.prior_evidence_id = result.evidence.evidence_id
        session.prior_action_id = result.action.action_id
        sources = [_source_dict(item) for item in session.engine.last_passages]
        generation = session.engine.last_generation
        turn_duration_ms = round((time.perf_counter() - started) * 1000)
        estimated_cost = generation.estimated_cost_usd if generation else None
        if estimated_cost is not None:
            session.total_estimated_cost_usd += estimated_cost
        self._log(
            session,
            "retrieval_result",
            "retrieval -> tutoring_engine",
            {
                "turn_id": turn_id,
                "status": "supported" if sources else "no_support_found",
                "sources": sources,
                "retrieval_ms": session.engine.last_retrieval_ms,
            },
            issue=None if sources else "No supporting course passage was found.",
        )
        handoffs = (
            ("student -> interaction", result.submission.record_id),
            ("interaction -> tutoring_engine", result.evidence.record_id),
            ("retrieval -> tutoring_engine", ",".join(result.action.grounding_refs)),
            ("tutoring_engine -> delivery", result.action.record_id),
            ("delivery -> interaction", result.delivery.record_id),
        )
        for name, record_ref in handoffs:
            self._log(
                session,
                "handoff",
                name,
                {"turn_id": turn_id, "record_ref": record_ref},
            )
        if generation:
            self._log(
                session,
                "model_generation",
                "tutoring_engine -> provider -> tutoring_engine",
                {
                    "model": generation.model,
                    "latency_ms": generation.latency_ms,
                    "input_tokens": generation.input_tokens,
                    "output_tokens": generation.output_tokens,
                    "estimated_cost_usd": generation.estimated_cost_usd,
                },
            )
        self._log(
            session,
            "turn_completed",
            "coordinator",
            {
                "turn_id": turn_id,
                "duration_ms": turn_duration_ms,
                "estimated_cost_usd": estimated_cost,
                "session_estimated_cost_usd": round(session.total_estimated_cost_usd, 8),
            },
        )
        self._log(
            session,
            "learner_state_committed",
            "delivery -> tutoring_engine",
            {
                "turn_id": turn_id,
                "record_ref": result.action.learner_state_id,
                "learner_state": session.engine.state_snapshot(),
            },
        )
        self._write_turn_record(
            session,
            turn_id=turn_id,
            modality="text",
            original_input=text,
            recognized_input=text,
            confirmed_input=result.evidence.confirmed_content or text,
            output=result.action.content.get("text", ""),
            action=result.action,
            sources=sources,
        )
        internal_response = {
            "session_id": session.session_id,
            "turn_id": turn_id,
            "message": result.action.content.get("text", ""),
            "action_id": result.action.action_id,
            "action_type": result.action.action_type,
            "evidence_id": result.evidence.evidence_id,
            "parent_evidence_id": result.evidence.parent_evidence_id,
            "response_to_action_id": result.submission.response_to_action_id,
            "handoff_status": result.handoff_status,
            "sources": sources,
            "trace": [event.event_type for event in result.trace_events],
            "compute": {
                "turn_duration_ms": turn_duration_ms,
                "retrieval_ms": session.engine.last_retrieval_ms,
                "model_latency_ms": generation.latency_ms if generation else None,
            },
            "cost": {
                "estimated_request_usd": estimated_cost,
                "estimated_session_usd": round(session.total_estimated_cost_usd, 8),
                "input_tokens": generation.input_tokens if generation else None,
                "output_tokens": generation.output_tokens if generation else None,
            },
            "learner_state": session.engine.state_snapshot(),
        }
        session.transcript.extend(
            [
                {"role": "student", "content": text, "turn_id": turn_id, "modality": "text"},
                {
                    "role": "assistant",
                    "content": internal_response["message"],
                    "turn_id": turn_id,
                    "action_type": internal_response["action_type"],
                    "sources": sources,
                },
            ]
        )
        return {
            "session_id": session.session_id,
            "turn_id": turn_id,
            "message": internal_response["message"],
            "action_type": internal_response["action_type"],
            "sources": sources,
        }

    def session_snapshot(self, session_id: str) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if session is None:
            raise LookupError(f"Session not found: {session_id}")
        return {
            "session_id": session.session_id,
            "course_id": session.course.course_id,
            "course_name": session.course.course_name,
            "diagnostic_logging": session.diagnostic_logging,
            "turn_count": session.turn_count,
            "transcript": session.transcript,
        }

    def begin_handwriting(
        self,
        session_id: str,
        *,
        filename: str,
        media_type: str,
        data: bytes,
        recognizer: HandwritingRecognizerPort,
    ) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if session is None:
            raise LookupError(f"Session not found: {session_id}")
        if session.handwriting_service is None:
            session.handwriting_service = HandwritingEvidenceService(
                InMemoryArtifactStore(),
                recognizer,
                session.coordinator,
                logging=HandwritingLoggingConfiguration(
                    diagnostic_logging_enabled=session.diagnostic_logging
                ),
            )
        preserved_artifact = self.trace_store.write_artifact(
            session.session_id, filename=filename, data=data
        )
        session.turn_count += 1
        turn_id = f"turn-{session.turn_count}"
        review = session.handwriting_service.begin(
            HandwritingSubmissionInput(
                user_id=session.user_id,
                course_id=session.course.course_id,
                session_id=session.session_id,
                turn_id=turn_id,
                question_id=session.question.question_id,
                attempt_id=session.attempt_id,
                filename=filename,
                media_type=media_type,
                artifact_bytes=data,
                evidence_kind="initial_attempt" if session.turn_count == 1 else "follow_up",
                parent_submission_id=session.prior_submission_id,
                parent_evidence_id=session.prior_evidence_id,
                response_to_action_id=session.prior_action_id,
                consent_flags={"diagnostic_logging": session.diagnostic_logging},
            )
        )
        if isinstance(review, HandwritingRecognitionFailure):
            self._log(
                session,
                "recognition_failed",
                "interaction -> handwriting_recognizer",
                {
                    "turn_id": turn_id,
                    "record_ref": review.submission.submission_id,
                    "error_code": review.error_code,
                },
                issue=review.message,
            )
            raise RuntimeError(review.message)
        self._log(
            session,
            "recognition_review_required",
            "handwriting_recognizer -> interaction",
            {
                "turn_id": turn_id,
                "record_ref": review.recognition.recognition_id,
                "provider": review.recognition.provider,
                "model": review.recognition.model_version,
                "latency_ms": review.recognition.latency_ms,
                "input_tokens": review.recognition.input_tokens,
                "output_tokens": review.recognition.output_tokens,
                "estimated_cost_usd": review.recognition.estimated_cost_usd,
                "ambiguities": [dict(item) for item in review.recognition.ambiguities],
            },
        )
        self.trace_store.write(
            session.session_id,
            {
                "created_at": _now(),
                "event": "recognition_record",
                "handoff": "handwriting_recognizer -> interaction",
                "issue": None,
                "turn_id": turn_id,
                "record_ref": review.recognition.recognition_id,
                "record": {
                    "modality": "handwriting_upload",
                    "filename": filename,
                    "original_artifact_ref": review.submission.original_artifact_ref,
                    "preserved_artifact": preserved_artifact,
                    "recognized_input": review.recognition.recognized_content,
                    "recognition_status": review.recognition.recognition_status,
                    "ambiguities": [dict(item) for item in review.recognition.ambiguities],
                },
            },
        )
        if review.recognition.estimated_cost_usd is not None:
            session.total_estimated_cost_usd += review.recognition.estimated_cost_usd
        return {
            "recognition_id": review.recognition.recognition_id,
            "turn_id": turn_id,
            "recognized_content": review.recognition.recognized_content,
            "recognition_status": review.recognition.recognition_status,
            "confirmation_required": review.confirmation_required,
            "ambiguities": [dict(item) for item in review.recognition.ambiguities],
            "page_count": review.recognition.page_count,
            "processed_pages": list(review.recognition.processed_pages),
        }

    def confirm_handwriting(
        self,
        session_id: str,
        *,
        recognition_id: str,
        confirmed_content: str,
        ambiguity_resolutions: dict[str, str],
    ) -> dict[str, Any]:
        started = time.perf_counter()
        session = self.sessions.get(session_id)
        if session is None:
            raise LookupError(f"Session not found: {session_id}")
        if session.handwriting_service is None:
            raise LookupError("No handwriting review is pending for this session.")
        pending_review = session.handwriting_service.pending_review(recognition_id)
        confirmed = session.handwriting_service.confirm(
            recognition_id,
            confirmed_content=confirmed_content,
            actor_id=session.user_id,
            ambiguity_resolutions=ambiguity_resolutions,
        )
        result = confirmed.result
        if isinstance(result, TutoringTurnFailure):
            raise RuntimeError(result.message)
        session.prior_submission_id = result.submission.submission_id
        session.prior_evidence_id = result.evidence.evidence_id
        session.prior_action_id = result.action.action_id
        sources = [_source_dict(item) for item in session.engine.last_passages]
        generation = session.engine.last_generation
        estimated_cost = generation.estimated_cost_usd if generation else None
        if estimated_cost is not None:
            session.total_estimated_cost_usd += estimated_cost
        duration_ms = round((time.perf_counter() - started) * 1000)
        self._log(
            session,
            "handwriting_confirmed",
            "interaction -> tutoring_engine",
            {
                "turn_id": result.evidence.turn_id,
                "record_ref": result.evidence.evidence_id,
                "recognition_id": recognition_id,
                "correction_refs": list(result.evidence.correction_refs),
            },
        )
        self._log(
            session,
            "retrieval_result",
            "retrieval -> tutoring_engine",
            {
                "turn_id": result.evidence.turn_id,
                "status": "supported" if sources else "no_support_found",
                "sources": sources,
                "retrieval_ms": session.engine.last_retrieval_ms,
            },
            issue=None if sources else "No supporting course passage was found.",
        )
        internal_response = {
            "session_id": session.session_id,
            "turn_id": result.evidence.turn_id,
            "message": result.action.content.get("text", ""),
            "action_id": result.action.action_id,
            "action_type": result.action.action_type,
            "evidence_id": result.evidence.evidence_id,
            "parent_evidence_id": result.evidence.parent_evidence_id,
            "response_to_action_id": result.submission.response_to_action_id,
            "handoff_status": result.handoff_status,
            "sources": sources,
            "trace": [event.event_type for event in result.trace_events],
            "compute": {
                "turn_duration_ms": duration_ms,
                "retrieval_ms": session.engine.last_retrieval_ms,
                "model_latency_ms": generation.latency_ms if generation else None,
            },
            "cost": {
                "estimated_request_usd": estimated_cost,
                "estimated_session_usd": round(session.total_estimated_cost_usd, 8),
                "input_tokens": generation.input_tokens if generation else None,
                "output_tokens": generation.output_tokens if generation else None,
            },
            "learner_state": session.engine.state_snapshot(),
        }
        recognized_input = (
            pending_review.recognition.recognized_content
            if pending_review is not None
            else None
        )
        self._write_turn_record(
            session,
            turn_id=result.evidence.turn_id,
            modality="handwriting_upload",
            original_input={
                "artifact_ref": result.submission.original_artifact_ref,
                "filename": result.submission.client_metadata.get("filename"),
            },
            recognized_input=recognized_input,
            confirmed_input=confirmed_content,
            output=result.action.content.get("text", ""),
            action=result.action,
            sources=sources,
        )
        session.transcript.extend(
            [
                {
                    "role": "student",
                    "content": confirmed_content,
                    "turn_id": result.evidence.turn_id,
                    "modality": "handwriting_upload",
                },
                {
                    "role": "assistant",
                    "content": internal_response["message"],
                    "turn_id": result.evidence.turn_id,
                    "action_type": internal_response["action_type"],
                    "sources": sources,
                },
            ]
        )
        return {
            "session_id": session.session_id,
            "turn_id": result.evidence.turn_id,
            "message": internal_response["message"],
            "action_type": internal_response["action_type"],
            "sources": sources,
        }

    def activity_summary(self, session_id: str) -> dict[str, Any]:
        if session_id not in self.sessions:
            raise LookupError(f"Session not found: {session_id}")
        session = self.sessions[session_id]
        rows: list[dict[str, Any]] = []
        for event in self.trace_store.read_session(session_id):
            if event.get("event") != "turn_activity":
                continue
            record = event.get("record", {})
            rows.append(
                {
                    "created_at": event.get("created_at"),
                    "turn_id": event.get("turn_id"),
                    "modality": record.get("modality"),
                    "input": _bounded(record.get("confirmed_input")),
                    "recognized_input": _bounded(record.get("recognized_input")),
                    "output": _bounded(record.get("output")),
                    "decision_summary": record.get("decision_summary", {}),
                    "learner_state": record.get("learner_state"),
                    "sources": record.get("sources", []),
                }
            )
        return {"turns": rows, "question_schema": session.question_schema_dict}

    def _write_turn_record(
        self,
        session: DemoSession,
        *,
        turn_id: str,
        modality: str,
        original_input: Any,
        recognized_input: str | None,
        confirmed_input: str,
        output: str,
        action: TutoringAction,
        sources: list[dict[str, Any]],
    ) -> None:
        self.trace_store.write(
            session.session_id,
            {
                "created_at": _now(),
                "event": "turn_activity",
                "handoff": "interaction -> tutoring_engine -> delivery",
                "issue": None,
                "turn_id": turn_id,
                "record_ref": action.action_id,
                "record": {
                    "modality": modality,
                    "original_input": original_input,
                    "recognized_input": recognized_input,
                    "confirmed_input": confirmed_input,
                    "output": output,
                    "decision_summary": {
                        "action_type": action.action_type,
                        "phase": action.constraints.get("phase"),
                        "help_level": action.constraints.get("help_level"),
                        "grounding_status": "supported" if sources else "no_support_found",
                    },
                    "learner_state": session.engine.state_snapshot(),
                    "sources": [
                        _activity_source(source, diagnostic=session.diagnostic_logging)
                        for source in sources
                    ],
                },
            },
        )

    def _log(
        self,
        session: DemoSession,
        event: str,
        handoff: str,
        diagnostic: dict[str, Any],
        *,
        issue: str | None = None,
    ) -> None:
        row: dict[str, Any] = {
            "created_at": _now(),
            "event": event,
            "handoff": handoff,
            "issue": issue,
            "diagnostic_logging": session.diagnostic_logging,
        }
        if "turn_id" in diagnostic:
            row["turn_id"] = diagnostic["turn_id"]
        if "record_ref" in diagnostic:
            row["record_ref"] = diagnostic["record_ref"]
        if session.diagnostic_logging:
            row["details"] = diagnostic
        session.logs.append(row)
        self.trace_store.write(session.session_id, row)


# ---------------------------------------------------------------------------
# Action instruction strings — central source of truth for the LLM prompt.
# ---------------------------------------------------------------------------

_ACTION_INSTRUCTIONS: dict[str, str] = {
    "probe":                "Ask the student what approach or method they think applies to this problem. Do NOT name, hint at, or reference any specific technique, formula, or concept name — not even indirectly. Do not ask about u, dv, substitution, or any method-specific term. Ask only: what do you think you would try? Wait for their answer before saying anything else.",
    "clarify":              "The response is unclear. Ask one specific question to understand the student's current approach. Do not name or hint at the correct method.",
    "hint":                 "Give one small source-backed hint, then ask what the next step should be. Do not advance further.",
    "explain":              "Explain one relevant concept using course material, then ask the student to apply it to this problem.",
    "check_understanding":  "The student is on the right track. Ask one focused question that deepens or confirms their reasoning.",
    "address_misconception":"Address the specific misconception the student has shown. Correct it gently using course evidence, then ask them to try again.",
    "nudge_calculation":    "The student's method is correct but there is a calculation error. Point to the specific step without correcting it outright.",
    "prereq_check":         "Point the student toward the prerequisite concept they are missing, using course material. Do not give the full solution.",
    "redirect":             "Acknowledge the student's attempt. Explain briefly why the current approach does not work, and hint at the correct direction without giving the answer.",
    "confirm":              "Confirm the correct answer. Celebrate briefly (one sentence), then ask the student to explain in their own words why the method works.",
    "wrap_up":              "The student already solved this problem. Offer a brief follow-up challenge or close the question. Do not re-explain the solution.",
    "retry":                "Ask the student to inspect the latest step and try again. Do not reveal the answer.",
}


# ---------------------------------------------------------------------------
# decide() — pure function: maps (turn state) → (action, phase, help_level)
# ---------------------------------------------------------------------------

def _decide(
    *,
    turn_type: str,
    math_correct: bool | None,
    diagnosis: str | None,
    help_level: int,
    stall_count: int,
    has_history: bool,
    phase: str,
) -> tuple[str, str, int, str]:
    """Pure, deterministic action selection.

    Returns (action_type, next_phase, next_help_level, instruction).
    All state is passed in; nothing is read from self.
    """
    hl = help_level
    stall_escalate = stall_count >= 2

    # Already solved — just wrap up regardless of what the student sends.
    if phase == "SOLVED":
        return ("wrap_up", "SOLVED", hl, _ACTION_INSTRUCTIONS["wrap_up"])

    # SymPy or model confirmed correct answer.
    if math_correct is True or diagnosis == "CORRECT":
        return ("confirm", "SOLVED", hl, _ACTION_INSTRUCTIONS["confirm"])

    # Explicit help request.
    if turn_type == "HELP":
        if hl == 0:
            return ("hint", "ATTEMPTING", 1, _ACTION_INSTRUCTIONS["hint"])
        return ("explain", "ATTEMPTING", min(hl + 1, 3), _ACTION_INSTRUCTIONS["explain"])

    # Ambiguous / too short.
    if turn_type == "VAGUE":
        if not has_history:
            return ("probe", "ATTEMPTING", hl, _ACTION_INSTRUCTIONS["probe"])
        return ("clarify", "ATTEMPTING", hl, _ACTION_INSTRUCTIONS["clarify"])

    # Student is explaining reasoning.
    if turn_type == "REASONING":
        return ("check_understanding", "ATTEMPTING", hl, _ACTION_INSTRUCTIONS["check_understanding"])

    # Off-topic new question.
    if turn_type == "NEW_QUESTION":
        return ("redirect", "ATTEMPTING", hl, _ACTION_INSTRUCTIONS["redirect"])

    # --- ATTEMPT branch: ladder indexed by diagnosis ---

    if diagnosis == "D0":  # no work shown
        return ("probe", "ATTEMPTING", hl, _ACTION_INSTRUCTIONS["probe"])

    if diagnosis == "D1":  # known misconception
        return ("address_misconception", "ATTEMPTING", max(hl, 1), _ACTION_INSTRUCTIONS["address_misconception"])

    if diagnosis == "D4":  # calculation error — method is right
        return ("nudge_calculation", "ATTEMPTING", hl, _ACTION_INSTRUCTIONS["nudge_calculation"])

    if diagnosis == "D5":  # partial — on the right track
        return ("check_understanding", "ATTEMPTING", hl, _ACTION_INSTRUCTIONS["check_understanding"])

    if diagnosis == "D2":  # wrong method
        if stall_escalate:
            return ("explain", "ATTEMPTING", min(hl + 1, 3), _ACTION_INSTRUCTIONS["explain"])
        return ("redirect", "ATTEMPTING", min(hl + 1, 3), _ACTION_INSTRUCTIONS["redirect"])

    if diagnosis in ("D3", "D6", "D7"):  # concept/prerequisite gap or other specific gap
        return ("prereq_check", "ATTEMPTING", min(hl + 1, 3), _ACTION_INSTRUCTIONS["prereq_check"])

    # Unclear / no specific diagnosis — escalate if stalled, otherwise retry.
    if stall_escalate:
        if hl == 0:
            return ("hint", "ATTEMPTING", 1, _ACTION_INSTRUCTIONS["hint"])
        return ("explain", "ATTEMPTING", min(hl + 1, 3), _ACTION_INSTRUCTIONS["explain"])

    if not has_history:
        return ("probe", "ATTEMPTING", hl, _ACTION_INSTRUCTIONS["probe"])
    return ("retry", "ATTEMPTING", hl, _ACTION_INSTRUCTIONS["retry"])


_HELP_MARKERS = frozenset({
    "help", "stuck", "explain", "don't know", "do not know", "unsure",
    "hint", "show me", "what do i", "how do i", "i don't", "i do not",
    "not sure", "confused", "lost",
})
_REASON_MARKERS = frozenset({
    "because", "therefore", "since", "so that", "which means", "thus",
    "hence", "that's why", "this means",
})
_MATH_CHARS = frozenset("=+-*/^∫∂∑∏")
_MATH_WORDS = frozenset({
    "integral", "derivative", "integrate", "differentiat", "substitut",
    "factor", "simplif", "expand", "solve", "calculat", "dx", "dy",
    "step", "approach", "method", "technique", "formula",
})
_NEW_Q_PATTERNS = (
    "what is ", "what are ", "how do ", "how does ", "can you ", "could you ",
    "define ", "what's the difference",
)


def _read_turn(text: str, *, has_history: bool) -> str:
    """Classify a student message into one of five turn types.

    HELP      — student is explicitly asking for guidance
    ATTEMPT   — student is making a mathematical attempt
    REASONING — student is explaining their reasoning
    VAGUE     — message is too short or ambiguous to classify
    NEW_QUESTION — student is asking about something unrelated
    """
    import re as _re

    stripped = text.strip()
    lowered = stripped.lower()
    words = lowered.split()
    has_math = any(c in _MATH_CHARS for c in text) or _re.search(r"\d", text)

    # Explicit help request — check before length gate so "help" alone works.
    if any(m in lowered for m in _HELP_MARKERS):
        return "HELP"

    # Very short messages with no math signal are VAGUE.
    if len(words) < 4 and not has_math:
        return "VAGUE"

    # Reasoning (student justifies a step).
    if any(m in lowered for m in _REASON_MARKERS):
        return "REASONING"

    # Math content signals an attempt.
    if has_math or any(w in lowered for w in _MATH_WORDS):
        return "ATTEMPT"

    # Looks like a new conceptual question (no math, starts with question phrase).
    if any(lowered.startswith(p) for p in _NEW_Q_PATTERNS):
        return "NEW_QUESTION"

    # Default: treat as an attempt if we have history, otherwise vague.
    return "ATTEMPT" if has_history else "VAGUE"


def _check_student_math(student_text: str, answer_verification: dict | None) -> bool | None:
    """Return True if the student's text contains a provably correct antiderivative.

    Returns None when verification isn't possible (SymPy missing, no payload,
    no parseable expression found).  Never raises.
    """
    if not answer_verification:
        return None
    variable = answer_verification.get("variable")
    integrand = answer_verification.get("integrand")
    if not (variable and integrand):
        return None
    try:
        import sympy
    except ImportError:
        return None
    try:
        var = sympy.Symbol(str(variable))
        loc: dict[str, Any] = {str(variable): var}
        integ = sympy.sympify(str(integrand), locals=loc)
    except Exception:
        return None
    for candidate in _extract_math_candidates(student_text):
        try:
            anti = sympy.sympify(candidate, locals=loc)
            if sympy.simplify(sympy.diff(anti, var) - integ) == 0:
                return True
        except Exception:
            continue
    return None


def _extract_math_candidates(text: str) -> list[str]:
    """Pull potential antiderivative expressions from free-form student text."""
    import re as _re

    candidates: list[str] = []

    # Method 1: whatever comes after any "=" sign (up to newline or sentence end).
    for part in _re.split(r"=", text)[1:]:
        raw = _re.split(r"[\n.;]", part)[0].strip()
        if raw:
            candidates.append(_latex_to_sympy(raw))

    # Method 2: LaTeX inline math $...$ or $$...$$
    for m in _re.findall(r"\$\$?([^$]+)\$\$?", text):
        candidates.append(_latex_to_sympy(m.strip()))

    # Method 3: expressions anchored to a function call (handles answers written
    # without "=", e.g. "the answer is xsin(x)+cos(x)").
    # Lazy prefix so "xsin(" is split as prefix="x", fn="sin" rather than
    # consuming "sin" into the prefix.
    _fns = r"(?:sin|cos|tan|log|exp|sqrt|ln)"
    _prefix = r"[-a-zA-Z0-9\*]*?"          # lazy: minimal chars before func name
    _arg = r"\([^()]*\)"                   # single-level argument
    _post_term = rf"[-a-zA-Z0-9\*]*?(?:{_fns}\s*{_arg}|[a-zA-Z0-9]+)"
    for m in _re.finditer(
        rf"({_prefix}{_fns}\s*{_arg}(?:\s*[\+\-]\s*{_post_term})*)",
        text,
        _re.IGNORECASE,
    ):
        raw = m.group(1).strip()
        if raw:
            candidates.append(_latex_to_sympy(raw))

    # Method 4: power expressions without function calls, e.g. "x^2/2 + x".
    for m in _re.finditer(
        r"[a-zA-Z]\s*(?:\*\*|\^)\s*[0-9]+"
        r"(?:\s*[\+\-\*\/]\s*[a-zA-Z0-9]+(?:\s*(?:\*\*|\^)\s*[0-9]+)?)*",
        text,
    ):
        candidates.append(_latex_to_sympy(m.group(0).strip()))

    # Deduplicate while preserving order.
    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _latex_to_sympy(raw: str) -> str:
    """Best-effort conversion of common LaTeX/student notation to SymPy syntax."""
    import re as _re

    s = raw.strip()
    # Strip trailing constant of integration (+C / + c)
    s = _re.sub(r"\s*\+\s*[Cc]\b\s*$", "", s)
    # LaTeX trig / log commands
    for latex, sympy_fn in (
        (r"\sin", "sin"),
        (r"\cos", "cos"),
        (r"\tan", "tan"),
        (r"\ln", "log"),
        (r"\log", "log"),
        (r"\exp", "exp"),
    ):
        s = s.replace(latex, sympy_fn)
    # Multiplication operators
    s = s.replace(r"\cdot", "*").replace(r"\times", "*")
    # LaTeX braces used as grouping: \frac{a}{b} → (a)/(b)  [simple single-level]
    s = _re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"(\1)/(\2)", s)
    # Remove remaining LaTeX commands and braces
    s = _re.sub(r"\\[a-zA-Z]+", "", s)
    s = s.replace("{", "(").replace("}", ")")
    # Exponents
    s = s.replace("^", "**")
    # Implicit multiplication before known trig/math function names
    for _fn in ("sin", "cos", "tan", "log", "exp", "sqrt"):
        s = _re.sub(rf"([a-zA-Z\d])({_fn}\()", r"\1*\2", s)
    # Implicit multiplication: digit immediately before letter or "("
    s = _re.sub(r"(\d)([a-zA-Z(])", r"\1*\2", s)
    # letter immediately before digit
    s = _re.sub(r"([a-zA-Z])(\d)", r"\1*\2", s)
    return s.strip()


def _source_dict(item: RetrievedPassage) -> dict[str, Any]:
    passage = item.passage
    return {
        "passage_id": passage.passage_id,
        "document_id": passage.document_id,
        "filename": passage.filename,
        "page_number": passage.page_number,
        "line_start": passage.line_start,
        "line_end": passage.line_end,
        "excerpt": passage.text[:600],
        "score": item.score,
        "highlight_url": item.highlight_url,
    }


def _activity_source(source: dict[str, Any], *, diagnostic: bool) -> dict[str, Any]:
    operational_fields = {
        "passage_id",
        "document_id",
        "filename",
        "page_number",
        "line_start",
        "line_end",
        "highlight_url",
    }
    if diagnostic:
        operational_fields.update({"excerpt", "score"})
    return {key: value for key, value in source.items() if key in operational_fields}


def _question_dict(question: RuntimeQuestionSchema) -> dict[str, Any]:
    return {
        name: list(value) if isinstance(value, tuple) else value
        for name in RuntimeQuestionSchema.__dataclass_fields__
        for value in (getattr(question, name),)
    }


def _build_gaps_from_qs(q: RuntimeQuestionSchema) -> dict[str, Gap]:
    """Create initial Gap objects from a QuestionSchema at session start."""
    gaps: dict[str, Gap] = {}
    technique = (q.correct_approach or {}).get("technique", "")
    if technique:
        gaps["method"] = Gap(
            gap_id="method",
            gap_type="method",
            target_slot="correct_approach",
            requirement=f"Demonstrate: {technique}",
        )
    for i, prereq in enumerate(q.prerequisite_concepts or ()):
        name = prereq.get("name") or prereq.get("concept_id", f"prerequisite {i}")
        relevance = prereq.get("relevance", "")
        gaps[f"prereq_{i}"] = Gap(
            gap_id=f"prereq_{i}",
            gap_type="prerequisite",
            target_slot=f"prerequisite_concepts[{i}]",
            requirement=f"Apply {name}" + (f": {relevance}" if relevance else ""),
        )
    for i, lo in enumerate((q.learning_objectives or ())[:2]):
        text = lo.get("text", "")
        if text:
            gaps[f"mastery_{i}"] = Gap(
                gap_id=f"mastery_{i}",
                gap_type="mastery",
                target_slot=f"learning_objectives[{i}]",
                requirement=text,
            )
    return gaps


def _gap_dict(g: Gap) -> dict[str, Any]:
    return {
        "gap_id": g.gap_id,
        "gap_type": g.gap_type,
        "target_slot": g.target_slot,
        "requirement": g.requirement,
        "status": g.status,
        "evidence_ids": list(g.evidence_ids),
    }


def _assessment_context(assessment: dict[str, Any]) -> str:
    """Build the TURN ASSESSMENT section injected into the writer's system prompt."""
    if not assessment or assessment.get("diagnosis") in (None, "UNCLEAR"):
        return ""
    lines = ["TURN ASSESSMENT:\n"]
    lines.append(f"Diagnosis: {assessment['diagnosis']}\n")
    target = assessment.get("target_gap")
    if target:
        lines.append(f"Target gap: {target}\n")
    summary = assessment.get("summary", "")
    if summary:
        lines.append(f"Summary: {summary}\n")
    lines.append("\n")
    return "".join(lines)


def _concepts_from_course_context(
    course_id: str, cc: dict
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return (concept_names, concept_ids) from a CourseContext dict, capped at 8."""
    concepts = [c for c in (cc.get("Concept") or []) if c.get("name")][:8]
    names = tuple(c["name"] for c in concepts)
    ids = tuple(
        c.get("id") or f"{course_id}.{_slug_topic(c['name'])}" for c in concepts
    )
    return names, ids


def _slug_topic(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "topic"


def _json_default(value: Any) -> Any:
    if hasattr(value, "items"):
        return dict(value)
    if isinstance(value, (tuple, set, frozenset)):
        return list(value)
    return str(value)


def _qs_system_context(q: "RuntimeQuestionSchema", *, hide_technique: bool = False) -> str:
    """Build the QUESTION SCHEMA section injected into the tutoring engine system prompt."""
    lines: list[str] = ["QUESTION SCHEMA:\n"]
    if not hide_technique and q.correct_approach.get("technique"):
        lines.append(
            f"Correct approach: {q.correct_approach['technique']} — "
            f"{q.correct_approach.get('justification', '')}\n"
        )
    if q.learning_objectives:
        lo_text = "; ".join(lo.get("text", "") for lo in q.learning_objectives if lo.get("text"))
        if lo_text:
            lines.append(f"Learning objectives: {lo_text}\n")
    if q.prerequisite_concepts:
        prereqs = "; ".join(
            f"{p.get('name', p.get('concept_id', ''))} ({p.get('relevance', '')})"
            for p in q.prerequisite_concepts
        )
        if prereqs:
            lines.append(f"Prerequisites: {prereqs}\n")
    if q.common_misconceptions:
        misc = "; ".join(
            f"{m.get('description', '')} [cue: {m.get('cue', '')}]"
            for m in q.common_misconceptions
            if m.get("description")
        )
        if misc:
            lines.append(f"Watch for these misconceptions: {misc}\n")
    lines.append("\n")
    return "".join(lines) if len(lines) > 2 else ""


def _bounded(value: Any, limit: int = 360) -> Any:
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return value[: limit - 1] + "…"
