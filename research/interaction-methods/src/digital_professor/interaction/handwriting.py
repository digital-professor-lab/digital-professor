"""Handwriting capture, review, confirmation, and evidence routing."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from .coordinator import TutoringTurnCoordinator
from .models import (
    SCHEMA_VERSION,
    HandwritingSubmissionInput,
    InteractionTraceEvent,
    RecognitionCorrection,
    RecognitionResult,
    StudentEvidence,
    StudentSubmission,
    TutoringTurnFailure,
    TutoringTurnResult,
)
from .ports import HandwritingRecognizerPort
from .pipeline import RecordValidationError
from .recognition import RecognitionConfigurationError
from .storage import InMemoryArtifactStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class HandwritingLoggingConfiguration:
    diagnostic_logging_enabled: bool = False


@dataclass(frozen=True, slots=True)
class HandwritingReview:
    submission: StudentSubmission
    recognition: RecognitionResult
    request: HandwritingSubmissionInput
    confirmation_required: bool


@dataclass(frozen=True, slots=True)
class HandwritingRecognitionFailure:
    submission: StudentSubmission
    error_code: str
    message: str
    retryable: bool


@dataclass(frozen=True, slots=True)
class ConfirmedHandwritingTurn:
    corrections: tuple[RecognitionCorrection, ...]
    result: TutoringTurnResult | TutoringTurnFailure


class HandwritingEvidenceService:
    """Own handwriting processing until validated evidence is safe downstream."""

    SUPPORTED_TYPES = {"image/png", "image/jpeg", "image/webp", "application/pdf"}
    MAX_UPLOAD_BYTES = 20 * 1024 * 1024

    def __init__(
        self,
        artifact_store: InMemoryArtifactStore,
        recognizer: HandwritingRecognizerPort,
        coordinator: TutoringTurnCoordinator,
        *,
        logging: HandwritingLoggingConfiguration = HandwritingLoggingConfiguration(),
        clock: Callable[[], str] = _utc_now,
        id_factory: Callable[[str], str] = _new_id,
    ) -> None:
        self.artifact_store = artifact_store
        self.recognizer = recognizer
        self.coordinator = coordinator
        self.logging = logging
        self._clock = clock
        self._id_factory = id_factory
        self._pending: dict[str, HandwritingReview] = {}

    def begin(
        self, request: HandwritingSubmissionInput
    ) -> HandwritingReview | HandwritingRecognitionFailure:
        self._validate_request(request)
        submission_id = self._id_factory("submission")
        correlation_id = self._id_factory("correlation")
        artifact_ref = self.artifact_store.preserve_binary(
            submission_id, request.artifact_bytes, filename=request.filename
        )
        submission = StudentSubmission(
            record_id=submission_id,
            record_type="StudentSubmission",
            schema_version=SCHEMA_VERSION,
            created_at=self._clock(),
            producer="interaction",
            status="recognition_pending",
            correlation_id=correlation_id,
            submission_id=submission_id,
            user_id=request.user_id,
            course_id=request.course_id,
            session_id=request.session_id,
            question_id=request.question_id,
            turn_id=request.turn_id,
            submission_role="question_response",
            attempt_id=request.attempt_id,
            parent_submission_id=request.parent_submission_id,
            response_to_action_id=request.response_to_action_id,
            modality=request.modality,
            original_artifact_ref=artifact_ref,
            submitted_text=None,
            student_explanation=request.student_explanation,
            student_uncertainty=_freeze(request.student_uncertainty),
            client_metadata=_freeze(request.client_metadata),
            consent_flags=_freeze(request.consent_flags),
        )
        try:
            output = self.recognizer.recognize(
                filename=request.filename,
                media_type=request.media_type,
                data=request.artifact_bytes,
            )
        except RecognitionConfigurationError as exc:
            return HandwritingRecognitionFailure(
                submission=submission,
                error_code="recognition_not_configured",
                message=str(exc),
                retryable=False,
            )
        except Exception:
            return HandwritingRecognitionFailure(
                submission=submission,
                error_code="recognition_service_unavailable",
                message="Recognition could not process the preserved submission. Retry or enter a transcription.",
                retryable=True,
            )
        if output.recognition_status == "failed" or not output.recognized_content.strip():
            return HandwritingRecognitionFailure(
                submission=submission,
                error_code="recognition_failed",
                message="No usable handwriting content was recognized. Upload a clearer file or enter a transcription.",
                retryable=True,
            )
        try:
            self._validate_output(output)
        except ValueError:
            return HandwritingRecognitionFailure(
                submission=submission,
                error_code="invalid_recognition_result",
                message="Recognition returned incomplete provenance. Retry or enter a transcription.",
                retryable=True,
            )

        recognition_id = self._id_factory("recognition")
        raw_output_ref = None
        if self.logging.diagnostic_logging_enabled and output.raw_provider_output is not None:
            raw_output_ref = self.artifact_store.preserve_diagnostic_text(
                f"diagnostic://{recognition_id}/provider-output.json",
                output.raw_provider_output,
            )
        ambiguities = tuple(
            _freeze({"ambiguity_id": self._id_factory("ambiguity"), **dict(item)})
            for item in output.ambiguities
        )
        meaning_ambiguity = any(bool(item.get("meaning_may_change")) for item in ambiguities)
        incomplete = len(output.processed_pages) < output.page_count
        effective_status = (
            "partial"
            if incomplete or output.recognition_status == "partial"
            else "confirmation_required"
            if meaning_ambiguity
            else output.recognition_status
        )
        recognition = RecognitionResult(
            record_id=recognition_id,
            record_type="RecognitionResult",
            schema_version=SCHEMA_VERSION,
            created_at=self._clock(),
            producer="interaction.recognition",
            status=effective_status,
            correlation_id=correlation_id,
            recognition_id=recognition_id,
            submission_id=submission_id,
            provider=output.provider,
            model_version=output.model_version,
            raw_output_ref=raw_output_ref,
            recognized_content=output.recognized_content,
            content_format=output.content_format,
            alternatives=tuple(_freeze(item) for item in output.alternatives),
            ambiguities=ambiguities,
            recognition_status=effective_status,
            latency_ms=output.latency_ms,
            page_count=output.page_count,
            processed_pages=output.processed_pages,
            observed_steps=tuple(_freeze(item) for item in output.observed_steps),
        )
        review = HandwritingReview(
            submission=submission,
            recognition=recognition,
            request=request,
            confirmation_required=(
                effective_status in {"confirmation_required", "partial"}
            ),
        )
        self._pending[recognition_id] = review
        return review

    def confirm(
        self,
        recognition_id: str,
        *,
        confirmed_content: str,
        actor_id: str,
        ambiguity_resolutions: Mapping[str, str] | None = None,
    ) -> ConfirmedHandwritingTurn:
        review = self._pending.get(recognition_id)
        if review is None:
            raise ValueError("Recognition review was not found or was already completed.")
        if not confirmed_content.strip():
            raise ValueError("Confirmed handwriting content cannot be empty.")
        resolutions = ambiguity_resolutions or {}
        required_ids = {
            str(item["ambiguity_id"])
            for item in review.recognition.ambiguities
            if item.get("meaning_may_change")
        }
        missing = sorted(item for item in required_ids if not resolutions.get(item, "").strip())
        if missing:
            raise ValueError("Resolve every meaning-changing ambiguity before continuing.")
        unresolved_edits = sorted(
            ambiguity_id
            for ambiguity_id in required_ids
            if resolutions[ambiguity_id].strip() not in confirmed_content
        )
        if unresolved_edits:
            raise ValueError(
                "Update the recognized work so it contains each confirmed ambiguity resolution."
            )

        corrections: list[RecognitionCorrection] = []
        for ambiguity in review.recognition.ambiguities:
            ambiguity_id = str(ambiguity["ambiguity_id"])
            if ambiguity_id not in resolutions:
                continue
            corrections.append(
                self._correction(
                    review,
                    raw_value=str(ambiguity.get("raw_value", "")),
                    corrected_value=resolutions[ambiguity_id],
                    actor_id=actor_id,
                    location={
                        "ambiguity_id": ambiguity_id,
                        "page_number": ambiguity.get("page_number"),
                        "region": ambiguity.get("region"),
                    },
                    reason="Student resolved a recognition ambiguity.",
                )
            )
        if confirmed_content != review.recognition.recognized_content or not corrections:
            corrections.append(
                self._correction(
                    review,
                    raw_value=review.recognition.recognized_content,
                    corrected_value=confirmed_content,
                    actor_id=actor_id,
                    location={"scope": "full_transcription"},
                    reason="Student reviewed the recognized transcription.",
                )
            )

        evidence = self._build_evidence(review, confirmed_content, tuple(corrections))
        self.validate_evidence(review, evidence, tuple(corrections))
        events = (
            self._event(review.submission, "submission", (review.submission.record_id,)),
            self._event(review.submission, "recognition", (recognition_id,)),
            *(self._event(review.submission, "correction", (item.record_id,)) for item in corrections),
            self._event(review.submission, "evidence_validated", (evidence.record_id,)),
        )
        result = self.coordinator.route_validated_evidence(
            review.submission, evidence, prior_events=events
        )
        del self._pending[recognition_id]
        return ConfirmedHandwritingTurn(corrections=tuple(corrections), result=result)

    def _build_evidence(
        self,
        review: HandwritingReview,
        confirmed_content: str,
        corrections: tuple[RecognitionCorrection, ...],
    ) -> StudentEvidence:
        request = review.request
        submission = review.submission
        evidence_id = self._id_factory("evidence")
        content_unchanged = confirmed_content == review.recognition.recognized_content
        return StudentEvidence(
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
            question_id=request.question_id,
            turn_id=submission.turn_id,
            attempt_id=request.attempt_id,
            submission_id=submission.submission_id,
            evidence_kind=request.evidence_kind,
            original_artifact_ref=submission.original_artifact_ref,
            confirmed_content=confirmed_content,
            recognition_ref=review.recognition.recognition_id,
            correction_refs=tuple(item.correction_id for item in corrections),
            observed_steps=(review.recognition.observed_steps if content_unchanged else ()),
            final_answer=None,
            student_explanation=submission.student_explanation,
            student_uncertainty=submission.student_uncertainty,
            prior_assistance=((submission.response_to_action_id,) if submission.response_to_action_id else ()),
            parent_evidence_id=request.parent_evidence_id,
            validation_status="valid",
            validation_errors=(),
            requires_human_review=False,
            unresolved_ambiguities=(),
        )

    def validate_evidence(
        self,
        review: HandwritingReview,
        evidence: StudentEvidence,
        corrections: tuple[RecognitionCorrection, ...],
    ) -> None:
        """Block malformed, ambiguous, or untraceable handwriting evidence."""

        errors: list[dict[str, str]] = []
        submission = review.submission
        linked_fields = (
            "user_id", "course_id", "session_id", "question_id", "turn_id",
            "attempt_id", "submission_id", "original_artifact_ref", "correlation_id",
        )
        for field_name in linked_fields:
            if getattr(evidence, field_name) != getattr(submission, field_name):
                errors.append({
                    "field": field_name,
                    "code": "link_mismatch",
                    "message": "Must match the preserved handwriting submission.",
                })
        if evidence.record_id != evidence.evidence_id:
            errors.append({"field": "evidence_id", "code": "id_mismatch", "message": "Must equal record_id."})
        if evidence.original_artifact_ref not in self.artifact_store:
            errors.append({"field": "original_artifact_ref", "code": "missing_artifact", "message": "Original upload is unavailable."})
        elif self.artifact_store.read_binary(evidence.original_artifact_ref) != review.request.artifact_bytes:
            errors.append({"field": "original_artifact_ref", "code": "artifact_mismatch", "message": "Original upload bytes changed."})
        if evidence.recognition_ref != review.recognition.recognition_id:
            errors.append({"field": "recognition_ref", "code": "link_mismatch", "message": "Must reference the reviewed recognition."})
        if evidence.correction_refs != tuple(item.correction_id for item in corrections):
            errors.append({"field": "correction_refs", "code": "link_mismatch", "message": "Must reference every applied correction."})
        if not evidence.confirmed_content or not evidence.confirmed_content.strip():
            errors.append({"field": "confirmed_content", "code": "required", "message": "Confirmed content is required."})
        if evidence.validation_status != "valid" or evidence.unresolved_ambiguities:
            errors.append({"field": "validation_status", "code": "not_ready", "message": "Unresolved handwriting cannot be routed downstream."})
        if errors:
            raise RecordValidationError("StudentEvidence", errors)

    def _correction(
        self,
        review: HandwritingReview,
        *,
        raw_value: str,
        corrected_value: str,
        actor_id: str,
        location: Mapping[str, Any],
        reason: str,
    ) -> RecognitionCorrection:
        correction_id = self._id_factory("correction")
        return RecognitionCorrection(
            record_id=correction_id,
            record_type="RecognitionCorrection",
            schema_version=SCHEMA_VERSION,
            created_at=self._clock(),
            producer="interaction",
            status="confirmed",
            correlation_id=review.submission.correlation_id,
            correction_id=correction_id,
            recognition_id=review.recognition.recognition_id,
            location=_freeze(location),
            raw_value=raw_value,
            corrected_value=corrected_value,
            correction_type=("student_confirmation" if raw_value == corrected_value else "student_edit"),
            reason=reason,
            actor_id=actor_id,
            meaning_changed=raw_value != corrected_value,
        )

    def _event(
        self, submission: StudentSubmission, event_type: str, refs: tuple[str, ...]
    ) -> InteractionTraceEvent:
        return InteractionTraceEvent(
            event_id=self._id_factory("event"),
            session_id=submission.session_id,
            turn_id=submission.turn_id,
            correlation_id=submission.correlation_id,
            event_type=event_type,
            record_refs=refs,
        )

    @classmethod
    def _validate_request(cls, request: HandwritingSubmissionInput) -> None:
        if not request.artifact_bytes:
            raise ValueError("Handwriting upload cannot be empty.")
        if len(request.artifact_bytes) > cls.MAX_UPLOAD_BYTES:
            raise ValueError("Handwriting upload exceeds the 20 MB V1 limit.")
        if request.media_type not in cls.SUPPORTED_TYPES:
            raise ValueError("Handwriting must be a PNG, JPEG, WEBP, or PDF.")
        if request.modality not in {"handwriting_upload", "stylus_canvas"}:
            raise ValueError("Unsupported handwriting modality.")
        if request.evidence_kind not in {
            "initial_attempt", "revision", "follow_up", "explanation", "clarification"
        }:
            raise ValueError("Unsupported evidence kind.")
        for name in ("user_id", "course_id", "session_id", "turn_id", "question_id", "attempt_id"):
            if not getattr(request, name).strip():
                raise ValueError(f"{name} is required.")

    @staticmethod
    def _validate_output(output: Any) -> None:
        if output.page_count < 1 or not output.processed_pages:
            raise ValueError("Recognizer returned invalid page provenance.")
        if any(page < 1 or page > output.page_count for page in output.processed_pages):
            raise ValueError("Recognizer returned an invalid processed page number.")
        for ambiguity in output.ambiguities:
            required = {"page_number", "region", "raw_value", "candidates", "meaning_may_change"}
            if not required.issubset(ambiguity):
                raise ValueError("Recognizer returned an incomplete ambiguity record.")
