"""Executable checks for required fields in specs/interfaces.md."""

from __future__ import annotations

from dataclasses import fields

from digital_professor.interaction.models import (
    DeliveryResult,
    LearnerState,
    StudentEvidence,
    StudentSubmission,
    TutoringAction,
)


COMMON_ENVELOPE = {
    "record_id",
    "record_type",
    "schema_version",
    "created_at",
    "producer",
    "status",
    "correlation_id",
}


def _field_names(record_type: type) -> set[str]:
    return {field.name for field in fields(record_type)}


def test_student_submission_implements_shared_contract() -> None:
    required = COMMON_ENVELOPE | {
        "submission_id",
        "user_id",
        "course_id",
        "session_id",
        "question_id",
        "turn_id",
        "submission_role",
        "attempt_id",
        "parent_submission_id",
        "response_to_action_id",
        "modality",
        "original_artifact_ref",
        "submitted_text",
        "student_explanation",
        "student_uncertainty",
    }
    assert required <= _field_names(StudentSubmission)


def test_student_evidence_is_factual_and_implements_shared_contract() -> None:
    required = COMMON_ENVELOPE | {
        "evidence_id",
        "submission_id",
        "question_id",
        "attempt_id",
        "evidence_kind",
        "confirmed_content",
        "observed_steps",
        "final_answer",
        "student_explanation",
        "student_uncertainty",
        "prior_assistance",
        "parent_evidence_id",
        "validation_status",
        "validation_errors",
        "requires_human_review",
        "unresolved_ambiguities",
    }
    names = _field_names(StudentEvidence)
    assert required <= names
    assert {"mastery", "misconception", "correctness", "diagnosis"}.isdisjoint(names)


def test_tutoring_action_and_delivery_result_implement_handoff_contracts() -> None:
    action_required = COMMON_ENVELOPE | {
        "action_id",
        "session_id",
        "question_id",
        "turn_id",
        "learner_state_id",
        "action_type",
        "pedagogical_goal",
        "content",
        "grounding_refs",
        "response_expected",
        "allowed_presentations",
        "constraints",
    }
    delivery_required = COMMON_ENVELOPE | {
        "delivery_result_id",
        "action_id",
        "channel",
        "presentation_status",
        "presented_content_ref",
        "presented_at",
        "adaptations",
        "next_input_capabilities",
    }
    assert action_required <= _field_names(TutoringAction)
    assert delivery_required <= _field_names(DeliveryResult)


def test_learner_state_implements_shared_contract() -> None:
    required = COMMON_ENVELOPE | {
        "learner_state_id",
        "user_id",
        "course_id",
        "session_id",
        "question_id",
        "based_on_evidence_ids",
        "demonstrated",
        "unresolved",
        "diagnostic_hypotheses",
        "assistance_history_summary",
        "state_confidence",
        "open_gaps",
        "closed_gaps",
        "off_target_context",
        "resolved_when",
    }
    assert required <= _field_names(LearnerState)
