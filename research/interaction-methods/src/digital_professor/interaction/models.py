"""Immutable logical records used by the typed Student Evidence pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping


SCHEMA_VERSION = "0.1"

SubmissionRole = Literal["question_intake", "question_response"]
SubmissionModality = Literal["text", "handwriting_upload", "stylus_canvas"]
EvidenceKind = Literal[
    "initial_attempt", "revision", "follow_up", "explanation", "clarification"
]
ValidationStatus = Literal["valid", "partial", "invalid", "unconfirmed"]


@dataclass(frozen=True, slots=True)
class TypedSubmissionInput:
    """Caller-supplied data for one typed submission.

    IDs describing existing objects are supplied by the caller and passed
    through unchanged. Record IDs and timestamps are created by Interaction.
    """

    user_id: str
    course_id: str
    session_id: str
    turn_id: str
    submitted_text: str
    question_id: str | None
    submission_role: SubmissionRole = "question_response"
    attempt_id: str | None = None
    evidence_kind: EvidenceKind = "initial_attempt"
    parent_submission_id: str | None = None
    parent_evidence_id: str | None = None
    response_to_action_id: str | None = None
    student_explanation: str | None = None
    student_uncertainty: Mapping[str, Any] | None = None
    client_metadata: Mapping[str, Any] = field(default_factory=dict)
    consent_flags: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HandwritingSubmissionInput:
    """Student-supplied context and bytes for one handwriting submission."""

    user_id: str
    course_id: str
    session_id: str
    turn_id: str
    question_id: str
    attempt_id: str
    filename: str
    media_type: str
    artifact_bytes: bytes
    modality: Literal["handwriting_upload", "stylus_canvas"] = "handwriting_upload"
    evidence_kind: EvidenceKind = "initial_attempt"
    parent_submission_id: str | None = None
    parent_evidence_id: str | None = None
    response_to_action_id: str | None = None
    student_explanation: str | None = None
    student_uncertainty: Mapping[str, Any] | None = None
    client_metadata: Mapping[str, Any] = field(default_factory=dict)
    consent_flags: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StudentSubmission:
    """Canonical record of exactly what the student submitted."""

    record_id: str
    record_type: Literal["StudentSubmission"]
    schema_version: str
    created_at: str
    producer: str
    status: str
    correlation_id: str
    submission_id: str
    user_id: str
    course_id: str
    session_id: str
    question_id: str | None
    turn_id: str
    submission_role: SubmissionRole
    attempt_id: str | None
    parent_submission_id: str | None
    response_to_action_id: str | None
    modality: SubmissionModality
    original_artifact_ref: str
    submitted_text: str | None
    student_explanation: str | None
    student_uncertainty: Mapping[str, Any] | None
    client_metadata: Mapping[str, Any]
    consent_flags: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class StudentEvidence:
    """Factual evidence derived from a submission without learner diagnosis."""

    record_id: str
    record_type: Literal["StudentEvidence"]
    schema_version: str
    created_at: str
    producer: str
    status: str
    correlation_id: str
    evidence_id: str
    user_id: str
    course_id: str
    session_id: str
    question_id: str
    turn_id: str
    attempt_id: str
    submission_id: str
    evidence_kind: EvidenceKind
    original_artifact_ref: str
    confirmed_content: str | None
    recognition_ref: str | None
    correction_refs: tuple[str, ...]
    observed_steps: tuple[Mapping[str, Any], ...]
    final_answer: str | None
    student_explanation: str | None
    student_uncertainty: Mapping[str, Any] | None
    prior_assistance: tuple[str, ...]
    parent_evidence_id: str | None
    validation_status: ValidationStatus
    validation_errors: tuple[Mapping[str, str], ...]
    requires_human_review: bool
    unresolved_ambiguities: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class RecognizerOutput:
    """Provider-neutral output before Interaction creates a shared record."""

    provider: str
    model_version: str
    recognized_content: str
    content_format: Literal["plain_text", "markdown_tex", "structured_multimodal"]
    alternatives: tuple[Mapping[str, Any], ...]
    ambiguities: tuple[Mapping[str, Any], ...]
    observed_steps: tuple[Mapping[str, Any], ...]
    page_count: int
    processed_pages: tuple[int, ...]
    recognition_status: Literal["recognized", "confirmation_required", "partial", "failed"]
    latency_ms: int | None
    raw_provider_output: str | None = None


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    """Shared recognition record defined by specs/interfaces.md section 5."""

    record_id: str
    record_type: Literal["RecognitionResult"]
    schema_version: str
    created_at: str
    producer: str
    status: str
    correlation_id: str
    recognition_id: str
    submission_id: str
    provider: str
    model_version: str
    raw_output_ref: str | None
    recognized_content: str
    content_format: str
    alternatives: tuple[Mapping[str, Any], ...]
    ambiguities: tuple[Mapping[str, Any], ...]
    recognition_status: Literal["recognized", "confirmation_required", "partial", "failed"]
    latency_ms: int | None
    page_count: int
    processed_pages: tuple[int, ...]
    observed_steps: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class RecognitionCorrection:
    """Shared correction record defined by specs/interfaces.md section 6."""

    record_id: str
    record_type: Literal["RecognitionCorrection"]
    schema_version: str
    created_at: str
    producer: str
    status: str
    correlation_id: str
    correction_id: str
    recognition_id: str
    location: Mapping[str, Any]
    raw_value: str
    corrected_value: str
    correction_type: Literal["student_confirmation", "student_edit"]
    reason: str | None
    actor_id: str
    meaning_changed: bool


@dataclass(frozen=True, slots=True)
class TutoringAction:
    """Structured action returned by a Tutoring Engine implementation."""

    record_id: str
    record_type: Literal["TutoringAction"]
    schema_version: str
    created_at: str
    producer: str
    status: str
    correlation_id: str
    action_id: str
    session_id: str
    question_id: str
    turn_id: str
    learner_state_id: str
    action_type: str
    pedagogical_goal: str
    content: Mapping[str, Any]
    grounding_refs: tuple[str, ...]
    response_expected: Mapping[str, Any]
    allowed_presentations: tuple[str, ...]
    constraints: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """Structured result returned by a Delivery implementation."""

    record_id: str
    record_type: Literal["DeliveryResult"]
    schema_version: str
    created_at: str
    producer: str
    status: str
    correlation_id: str
    delivery_result_id: str
    action_id: str
    channel: str
    presentation_status: str
    presented_content_ref: str
    presented_at: str | None
    adaptations: tuple[Mapping[str, Any], ...]
    next_input_capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InteractionTraceEvent:
    """Minimal operational event needed to trace one tutoring turn."""

    event_id: str
    session_id: str
    turn_id: str
    correlation_id: str
    event_type: str
    record_refs: tuple[str, ...]
    operational_required: bool = True
    diagnostic_payload_ref: str | None = None
    duration_ms: int | None = None
    cost: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class TutoringTurnResult:
    """Records and trace produced by one completed typed tutoring turn."""

    submission: StudentSubmission
    evidence: StudentEvidence
    action: TutoringAction
    delivery: DeliveryResult
    trace_events: tuple[InteractionTraceEvent, ...]
    handoff_status: Literal["complete"] = "complete"


@dataclass(frozen=True, slots=True)
class TutoringTurnFailure:
    """Structured recoverable result when a downstream handoff fails."""

    correlation_id: str
    failed_stage: Literal["tutoring_engine", "delivery"]
    error_code: str
    message: str
    submission: StudentSubmission
    evidence: StudentEvidence
    action: TutoringAction | None
    trace_events: tuple[InteractionTraceEvent, ...]
    handoff_status: Literal["failed"] = "failed"

