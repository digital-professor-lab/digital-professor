"""Stateful application service for the integrated local demo.

The service coordinates shared records without moving course parsing, retrieval,
tutoring decisions, or presentation into the web layer.
"""

from __future__ import annotations

import os

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any
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
    TutoringAction,
    TutoringTurnFailure,
)
from digital_professor.interaction.ports import HandwritingRecognizerPort
from digital_professor import course_cache
from digital_professor.pipeline_view import build_pipeline_view, retrieval_snapshot
from digital_professor.retrieval.course_retrieval import (
    build_course_retrieval,
    describe_index,
)
from digital_professor.retrieval.index import CourseRetrievalIndex, RetrievedPassage
from digital_professor.tutoring.grounded_engine import GroundedDemoEngine, TextProvider


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class TimestampedTraceStore:
    """Persist operational and optional diagnostic events outside the UI."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root or os.environ.get("DIGITAL_PROFESSOR_LOG_DIR") or "logs")

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
        # Retrieval V1 over the ingested blocks when it is available, else the keyword index.
        self.indexes[workspace.course_id] = build_course_retrieval(workspace)
        course_cache.remember(workspace)        # only with DP_KEEP_COURSES=1 (local development)

    def restore_courses(self) -> int:
        """Publish again the courses saved by an earlier run (local development; see ``course_cache``)."""
        restored = 0
        for workspace in course_cache.saved_courses():
            if workspace.course_id not in self.courses:
                self.courses[workspace.course_id] = workspace
                self.indexes[workspace.course_id] = build_course_retrieval(workspace)
                restored += 1
        return restored

    def retrieval_status(self) -> dict[str, Any]:
        """Which index each published course is served by (no course text, no secrets)."""
        return {
            course_id: describe_index(index).to_dict()
            for course_id, index in self.indexes.items()
        }

    def pipeline_sessions(self) -> list[dict[str, Any]]:
        """Sessions for the run-log page, newest first."""
        rows = []
        for session in self.sessions.values():
            start = session.engine.session_trace or {}
            rows.append({
                "session_id": session.session_id,
                "course_name": session.course.course_name,
                "question": session.question.prompt,
                "started_at": start.get("created_at"),
                "turns": len(session.engine.pipeline_turns),
            })
        return rows[::-1]

    def pipeline_view(self, session_id: str) -> dict[str, Any]:
        """Every step of the session, each with its output and a plain-language note."""
        session = self.sessions.get(session_id)
        if session is None:
            raise LookupError(f"Session not found: {session_id}")
        return build_pipeline_view(session)

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
        correlation_id = f"correlation-{uuid4()}"
        search_started = time.perf_counter()
        passages = self.indexes[course_id].search(
            question,
            top_k=4,
            question_prompt=question,
            student_message=question,
            correlation_id=correlation_id,
        )
        source_ids = tuple(dict.fromkeys(item.passage.document_id for item in passages))
        start_trace: dict[str, Any] = {
            "created_at": _now(),
            "question": question,
            "course_name": course.course_name,
            "initial_retrieval": retrieval_snapshot(
                self.indexes[course_id], passages,
                round((time.perf_counter() - search_started) * 1000),
            ),
        }

        qs_dict: dict[str, Any] | None = None
        schema: RuntimeQuestionSchema

        if not course.course_context:
            start_trace["schema_builder"] = {"status": "no_course_context"}
        elif self.provider is None:
            start_trace["schema_builder"] = {"status": "no_model"}
        if course.course_context and self.provider is not None:
            builder_started = time.perf_counter()
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
                start_trace["schema_builder"] = {
                    "status": "built",
                    "ms": round((time.perf_counter() - builder_started) * 1000),
                }
                search_started = time.perf_counter()
                passages = self.indexes[course_id].search(
                    _qs_query,
                    top_k=4,
                    concept_ids=concept_ids,
                    concept_names=concept_names,
                    topic=_qs_technique or None,
                    question_prompt=question,
                    student_message=question,
                    question_id=qs_dict["question_id"],
                    correlation_id=correlation_id,
                )
                source_ids = tuple(dict.fromkeys(item.passage.document_id for item in passages))
                start_trace["structured_retrieval"] = retrieval_snapshot(
                    self.indexes[course_id], passages,
                    round((time.perf_counter() - search_started) * 1000),
                )
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
                start_trace["schema_builder"] = {"status": "failed", "error": str(exc)[:300]}
                start_trace.pop("structured_retrieval", None)
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

        engine = GroundedDemoEngine(
            schema, self.indexes[course_id], self.provider,
            course_blocks=[block for document in course.documents for block in document.chunks])
        start_trace["question_schema"] = _question_dict(schema)
        start_trace["gaps"] = [g.to_dict() for g in engine.qstate.gaps.values()]
        engine.session_trace = start_trace
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
                **_retrieval_log(session.engine.last_retrieval, sources),
                "sources": sources,
                "retrieval_ms": session.engine.last_retrieval_ms,
            },
            issue=_retrieval_issue(session.engine.last_retrieval, sources),
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
                **_retrieval_log(session.engine.last_retrieval, sources),
                "sources": sources,
                "retrieval_ms": session.engine.last_retrieval_ms,
            },
            issue=_retrieval_issue(session.engine.last_retrieval, sources),
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
                        "grounding_status": _retrieval_log(
                            session.engine.last_retrieval, sources
                        )["status"],
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


# ---------------------------------------------------------------------------
# decide() — pure function: maps (turn state) → (action, phase, help_level)
# ---------------------------------------------------------------------------


def _retrieval_log(outcome: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Retrieval status for logs: the index's own report, or the old sources-or-not rule."""
    if not outcome:
        return {"status": "supported" if sources else "no_support_found"}
    return {
        key: outcome[key]
        for key in (
            "status", "mode", "backend", "warnings", "uncovered_needs",
            "reason_code", "query", "query_origin", "skipped",
        )
        if key in outcome
    }


def _retrieval_issue(outcome: dict[str, Any], sources: list[dict[str, Any]]) -> str | None:
    status = _retrieval_log(outcome, sources)["status"]
    if status == "failed":
        return "Retrieval failed; this is a component fault, not missing course material."
    if status in ("supported", "partial") and sources:
        return None
    if status in ("supported", "partial", "no_support_found"):
        return "No supporting course passage was found."
    if status == "not_run":      # the chosen move needs no course material
        return None
    return f"Retrieval stopped before searching: {status}."


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


def _bounded(value: Any, limit: int = 360) -> Any:
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return value[: limit - 1] + "…"
