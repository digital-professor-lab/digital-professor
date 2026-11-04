"""Behavior tests for the first typed Student Evidence pipeline slice."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from digital_professor.interaction import (
    InMemoryArtifactStore,
    MockDelivery,
    MockTutoringEngine,
    RecordValidationError,
    StudentEvidencePipeline,
    TutoringTurnCoordinator,
    TypedSubmissionInput,
)
from digital_professor.interaction.models import TutoringTurnFailure, TutoringTurnResult


def _request(**overrides: object) -> TypedSubmissionInput:
    values: dict[str, object] = {
        "user_id": "student-7",
        "course_id": "course-1",
        "session_id": "session-20",
        "turn_id": "turn-3",
        "question_id": "question-4",
        "attempt_id": "attempt-2",
        "submitted_text": "  I used `x = 2`.\n\n$$2(x+3)=10$$  ",
        "student_explanation": "I distributed first.",
        "student_uncertainty": {"level": "unsure"},
    }
    values.update(overrides)
    return TypedSubmissionInput(**values)  # type: ignore[arg-type]


def test_typed_input_is_preserved_exactly_and_bypasses_recognition() -> None:
    store = InMemoryArtifactStore()
    pipeline = StudentEvidencePipeline(store)
    request = _request()

    submission = pipeline.capture_typed_submission(request)
    evidence = pipeline.build_student_evidence(submission, request)

    assert submission.submitted_text == request.submitted_text
    assert store.read_text(submission.original_artifact_ref) == request.submitted_text
    assert evidence.confirmed_content == request.submitted_text
    assert evidence.original_artifact_ref == submission.original_artifact_ref
    assert evidence.recognition_ref is None
    assert evidence.correction_refs == ()
    assert evidence.validation_status == "valid"
    assert evidence.requires_human_review is False


def test_submission_and_nested_metadata_cannot_be_mutated_through_pipeline() -> None:
    store = InMemoryArtifactStore()
    pipeline = StudentEvidencePipeline(store)
    request = _request(client_metadata={"device": "browser"})
    submission = pipeline.capture_typed_submission(request)

    with pytest.raises(FrozenInstanceError):
        submission.submitted_text = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        submission.client_metadata["device"] = "other"  # type: ignore[index]


def test_invalid_request_stops_before_engine_or_delivery() -> None:
    store = InMemoryArtifactStore()
    engine = MockTutoringEngine()
    delivery = MockDelivery()
    coordinator = TutoringTurnCoordinator(
        StudentEvidencePipeline(store), engine, delivery
    )

    with pytest.raises(RecordValidationError) as exc_info:
        coordinator.run_typed_turn(_request(submitted_text="   ", question_id=None))

    assert {error["field"] for error in exc_info.value.errors} == {
        "submitted_text",
        "question_id",
    }
    assert engine.received_evidence == []
    assert delivery.received_actions == []


def test_complete_turn_routes_validated_evidence_and_unchanged_action() -> None:
    store = InMemoryArtifactStore()
    engine = MockTutoringEngine()
    delivery = MockDelivery()
    coordinator = TutoringTurnCoordinator(
        StudentEvidencePipeline(store), engine, delivery
    )

    result = coordinator.run_typed_turn(_request())

    assert isinstance(result, TutoringTurnResult)
    assert engine.received_evidence == [result.evidence]
    assert delivery.received_actions[0] is result.action
    assert result.delivery.action_id == result.action.action_id
    assert result.delivery.presentation_status == "presented"
    assert result.handoff_status == "complete"
    assert [event.event_type for event in result.trace_events] == [
        "submission",
        "evidence_validated",
        "action_selected",
        "delivery",
    ]
    assert all(
        event.correlation_id == result.submission.correlation_id
        for event in result.trace_events
    )


def test_revision_links_prior_submission_evidence_and_action() -> None:
    store = InMemoryArtifactStore()
    pipeline = StudentEvidencePipeline(store)
    request = _request(
        submitted_text="2x + 6 = 10, so x = 2",
        evidence_kind="revision",
        parent_submission_id="submission-prior",
        parent_evidence_id="evidence-prior",
        response_to_action_id="action-hint",
    )

    submission = pipeline.capture_typed_submission(request)
    evidence = pipeline.build_student_evidence(submission, request)

    assert submission.parent_submission_id == "submission-prior"
    assert submission.response_to_action_id == "action-hint"
    assert evidence.parent_evidence_id == "evidence-prior"
    assert evidence.prior_assistance == ("action-hint",)
    assert evidence.evidence_kind == "revision"


def test_question_intake_is_preserved_but_not_converted_to_answer_evidence() -> None:
    store = InMemoryArtifactStore()
    pipeline = StudentEvidencePipeline(store)
    request = _request(
        submission_role="question_intake",
        question_id=None,
        attempt_id=None,
        submitted_text="Can you help me understand this equation?",
    )

    submission = pipeline.capture_typed_submission(request)

    assert store.read_text(submission.original_artifact_ref) == request.submitted_text
    with pytest.raises(RecordValidationError, match="Answer evidence requires"):
        pipeline.build_student_evidence(submission, request)


def test_evidence_cannot_be_built_from_a_different_request() -> None:
    store = InMemoryArtifactStore()
    pipeline = StudentEvidencePipeline(store)
    original_request = _request()
    submission = pipeline.capture_typed_submission(original_request)

    with pytest.raises(RecordValidationError) as exc_info:
        pipeline.build_student_evidence(
            submission,
            _request(submitted_text="A different response"),
        )
    assert exc_info.value.errors[0]["code"] == "request_mismatch"


def test_engine_failure_returns_structured_handoff_failure() -> None:
    class FailingEngine:
        def select_action(self, evidence: object) -> object:
            raise TimeoutError("engine timed out")

    store = InMemoryArtifactStore()
    delivery = MockDelivery()
    coordinator = TutoringTurnCoordinator(
        StudentEvidencePipeline(store), FailingEngine(), delivery  # type: ignore[arg-type]
    )

    result = coordinator.run_typed_turn(_request())

    assert isinstance(result, TutoringTurnFailure)
    assert result.failed_stage == "tutoring_engine"
    assert result.error_code == "engine_handoff_failed"
    assert result.action is None
    assert result.trace_events[-1].event_type == "failure"
    assert delivery.received_actions == []


def test_delivery_failure_preserves_selected_action_in_failure_result() -> None:
    class FailingDelivery:
        def deliver(self, action: object) -> object:
            raise RuntimeError("channel unavailable")

    store = InMemoryArtifactStore()
    engine = MockTutoringEngine()
    coordinator = TutoringTurnCoordinator(
        StudentEvidencePipeline(store), engine, FailingDelivery()  # type: ignore[arg-type]
    )

    result = coordinator.run_typed_turn(_request())

    assert isinstance(result, TutoringTurnFailure)
    assert result.failed_stage == "delivery"
    assert result.error_code == "delivery_handoff_failed"
    assert result.action is not None
    assert result.action.question_id == "question-4"
    assert result.trace_events[-1].event_type == "failure"

