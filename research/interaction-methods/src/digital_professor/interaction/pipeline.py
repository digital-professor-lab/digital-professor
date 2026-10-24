"""Typed StudentSubmission capture and StudentEvidence construction."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from .models import (
    SCHEMA_VERSION,
    StudentEvidence,
    StudentSubmission,
    TypedSubmissionInput,
)
from .storage import InMemoryArtifactStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _freeze_value(value: Any) -> Any:
    """Copy JSON-like input into recursively immutable containers."""

    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)
    return value


def _frozen_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if value is None:
        return None
    return _freeze_value(value)


class RecordValidationError(ValueError):
    """Raised before an invalid record can be handed downstream."""

    def __init__(self, record_type: str, errors: list[dict[str, str]]) -> None:
        self.record_type = record_type
        self.errors = tuple(MappingProxyType(dict(error)) for error in errors)
        summary = "; ".join(f"{e['field']}: {e['message']}" for e in errors)
        super().__init__(f"Invalid {record_type}: {summary}")


class StudentEvidencePipeline:
    """V1 typed-input implementation of the Student Evidence pipeline."""

    def __init__(
        self,
        artifact_store: InMemoryArtifactStore,
        *,
        clock: Callable[[], str] = _utc_now,
        id_factory: Callable[[str], str] = _new_id,
    ) -> None:
        self.artifact_store = artifact_store
        self._clock = clock
        self._id_factory = id_factory

    def capture_typed_submission(
        self, request: TypedSubmissionInput, *, correlation_id: str | None = None
    ) -> StudentSubmission:
        """Validate input, preserve exact text, and create StudentSubmission."""

        self._validate_request(request)
        submission_id = self._id_factory("submission")
        correlation_id = correlation_id or self._id_factory("correlation")
        artifact_ref = self.artifact_store.preserve_text(
            submission_id, request.submitted_text
        )

        submission = StudentSubmission(
            record_id=submission_id,
            record_type="StudentSubmission",
            schema_version=SCHEMA_VERSION,
            created_at=self._clock(),
            producer="interaction",
            status="received",
            correlation_id=correlation_id,
            submission_id=submission_id,
            user_id=request.user_id,
            course_id=request.course_id,
            session_id=request.session_id,
            question_id=request.question_id,
            turn_id=request.turn_id,
            submission_role=request.submission_role,
            attempt_id=request.attempt_id,
            parent_submission_id=request.parent_submission_id,
            response_to_action_id=request.response_to_action_id,
            modality="text",
            original_artifact_ref=artifact_ref,
            submitted_text=request.submitted_text,
            student_explanation=request.student_explanation,
            student_uncertainty=_frozen_mapping(request.student_uncertainty),
            client_metadata=_frozen_mapping(request.client_metadata) or MappingProxyType({}),
            consent_flags=_frozen_mapping(request.consent_flags) or MappingProxyType({}),
        )
        self.validate_submission(submission)
        return submission

    def build_student_evidence(
        self, submission: StudentSubmission, request: TypedSubmissionInput
    ) -> StudentEvidence:
        """Create factual evidence from direct text without diagnosing it."""

        self.validate_submission(submission)
        self._validate_request_matches_submission(request, submission)
        if submission.question_id is None or submission.attempt_id is None:
            raise RecordValidationError(
                "StudentEvidence",
                [
                    {
                        "field": "question_id/attempt_id",
                        "code": "context_required",
                        "message": "Answer evidence requires question and attempt IDs.",
                    }
                ],
            )

        evidence_id = self._id_factory("evidence")
        prior_assistance = (
            (submission.response_to_action_id,)
            if submission.response_to_action_id is not None
            else ()
        )
        evidence = StudentEvidence(
            record_id=evidence_id,
            record_type="StudentEvidence",
            schema_version=SCHEMA_VERSION,
            created_at=self._clock(),
            producer="interaction",
            status="ready",
            correlation_id=submission.correlation_id,
            evidence_id=evidence_id,
            user_id=submission.user_id,
            course_id=submission.course_id,
            session_id=submission.session_id,
            question_id=submission.question_id,
            turn_id=submission.turn_id,
            attempt_id=submission.attempt_id,
            submission_id=submission.submission_id,
            evidence_kind=request.evidence_kind,
            original_artifact_ref=submission.original_artifact_ref,
            confirmed_content=submission.submitted_text,
            recognition_ref=None,
            correction_refs=(),
            observed_steps=(),
            final_answer=None,
            student_explanation=submission.student_explanation,
            student_uncertainty=submission.student_uncertainty,
            prior_assistance=prior_assistance,
            parent_evidence_id=request.parent_evidence_id,
            validation_status="valid",
            validation_errors=(),
            requires_human_review=False,
            unresolved_ambiguities=(),
        )
        self.validate_evidence(evidence, submission)
        return evidence

    def validate_submission(self, submission: StudentSubmission) -> None:
        """Reject malformed or no-longer-traceable submission records."""

        errors: list[dict[str, str]] = []
        self._require_text(errors, "record_id", submission.record_id)
        self._require_text(errors, "correlation_id", submission.correlation_id)
        self._require_text(errors, "user_id", submission.user_id)
        self._require_text(errors, "course_id", submission.course_id)
        self._require_text(errors, "session_id", submission.session_id)
        self._require_text(errors, "turn_id", submission.turn_id)
        if submission.record_id != submission.submission_id:
            errors.append(self._error("submission_id", "id_mismatch", "Must equal record_id."))
        if submission.modality != "text":
            errors.append(self._error("modality", "unsupported", "Typed V1 requires text."))
        if not submission.submitted_text.strip():
            errors.append(
                self._error("submitted_text", "required", "Text cannot be empty or whitespace.")
            )
        if submission.submission_role == "question_response":
            self._require_text(errors, "question_id", submission.question_id)
            self._require_text(errors, "attempt_id", submission.attempt_id)
        if submission.original_artifact_ref not in self.artifact_store:
            errors.append(
                self._error(
                    "original_artifact_ref", "missing_artifact", "Original artifact is unavailable."
                )
            )
        elif self.artifact_store.read_text(submission.original_artifact_ref) != submission.submitted_text:
            errors.append(
                self._error(
                    "submitted_text",
                    "artifact_mismatch",
                    "Submitted text differs from the preserved original.",
                )
            )
        if errors:
            raise RecordValidationError("StudentSubmission", errors)

    def validate_evidence(
        self, evidence: StudentEvidence, submission: StudentSubmission
    ) -> None:
        """Ensure evidence is valid, factual, and linked to its submission."""

        errors: list[dict[str, str]] = []
        if evidence.record_id != evidence.evidence_id:
            errors.append(self._error("evidence_id", "id_mismatch", "Must equal record_id."))
        for field_name in (
            "user_id",
            "course_id",
            "session_id",
            "question_id",
            "turn_id",
            "attempt_id",
            "submission_id",
            "original_artifact_ref",
            "correlation_id",
        ):
            if getattr(evidence, field_name) != getattr(submission, field_name):
                errors.append(
                    self._error(field_name, "link_mismatch", "Must match the source submission.")
                )
        if evidence.confirmed_content != submission.submitted_text:
            errors.append(
                self._error(
                    "confirmed_content",
                    "content_mismatch",
                    "Direct typed evidence must preserve submitted text exactly.",
                )
            )
        if evidence.recognition_ref is not None or evidence.correction_refs:
            errors.append(
                self._error(
                    "recognition_ref",
                    "unexpected_recognition",
                    "Direct typed input must bypass recognition.",
                )
            )
        if evidence.validation_status != "valid" or evidence.unresolved_ambiguities:
            errors.append(
                self._error(
                    "validation_status",
                    "not_ready",
                    "Typed evidence must be valid and unambiguous before handoff.",
                )
            )
        if errors:
            raise RecordValidationError("StudentEvidence", errors)

    @staticmethod
    def _validate_request(request: TypedSubmissionInput) -> None:
        errors: list[dict[str, str]] = []
        for field_name in ("user_id", "course_id", "session_id", "turn_id"):
            StudentEvidencePipeline._require_text(
                errors, field_name, getattr(request, field_name)
            )
        if not request.submitted_text.strip():
            errors.append(
                StudentEvidencePipeline._error(
                    "submitted_text",
                    "required",
                    "Typed input cannot be empty or whitespace.",
                )
            )
        if request.submission_role == "question_response":
            StudentEvidencePipeline._require_text(errors, "question_id", request.question_id)
            StudentEvidencePipeline._require_text(errors, "attempt_id", request.attempt_id)
        elif request.attempt_id is not None:
            errors.append(
                StudentEvidencePipeline._error(
                    "attempt_id",
                    "not_allowed",
                    "Question intake cannot have an attempt before a Question Schema exists.",
                )
            )
        if request.submission_role not in {"question_intake", "question_response"}:
            errors.append(
                StudentEvidencePipeline._error(
                    "submission_role", "unsupported", "Unsupported submission role."
                )
            )
        if request.evidence_kind not in {
            "initial_attempt",
            "revision",
            "follow_up",
            "explanation",
            "clarification",
        }:
            errors.append(
                StudentEvidencePipeline._error(
                    "evidence_kind", "unsupported", "Unsupported evidence kind."
                )
            )
        if errors:
            raise RecordValidationError("TypedSubmissionInput", errors)

    @staticmethod
    def _validate_request_matches_submission(
        request: TypedSubmissionInput, submission: StudentSubmission
    ) -> None:
        """Prevent evidence construction from mixing two submission contexts."""

        errors: list[dict[str, str]] = []
        fields = (
            "user_id",
            "course_id",
            "session_id",
            "question_id",
            "turn_id",
            "attempt_id",
            "submission_role",
            "parent_submission_id",
            "response_to_action_id",
            "submitted_text",
        )
        for field_name in fields:
            if getattr(request, field_name) != getattr(submission, field_name):
                errors.append(
                    StudentEvidencePipeline._error(
                        field_name,
                        "request_mismatch",
                        "Evidence request does not match the captured submission.",
                    )
                )
        if errors:
            raise RecordValidationError("StudentEvidence", errors)

    @staticmethod
    def _require_text(
        errors: list[dict[str, str]], field: str, value: str | None
    ) -> None:
        if value is None or not value.strip():
            errors.append(StudentEvidencePipeline._error(field, "required", "Value is required."))

    @staticmethod
    def _error(field: str, code: str, message: str) -> dict[str, str]:
        return {"field": field, "code": code, "message": message}

