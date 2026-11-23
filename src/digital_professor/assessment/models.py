"""Assessment records aligned with ``specs/assessment.md``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AssessmentQuestion:
    record_id: str
    record_type: str
    schema_version: str
    created_at: str
    producer: str
    status: str
    correlation_id: str
    assessment_question_id: str
    assessment_session_id: str
    question_id: str
    attempt_id: str
    course_id: str
    concept_ids: tuple[str, ...]
    objective_ids: tuple[str, ...]
    difficulty_level: int
    question_type: str
    prompt_latex: str
    choices: tuple[dict[str, str], ...]
    answer_key: dict[str, Any]
    rubric: dict[str, Any]
    grounding_refs: tuple[dict[str, Any], ...]
    content_versions: tuple[str, ...]
    retrieval_snapshot_id: str
    expected_time_ms: int | None
    presented_at: str | None = None


@dataclass(frozen=True, slots=True)
class AssessmentEvaluation:
    record_id: str
    record_type: str
    schema_version: str
    created_at: str
    producer: str
    status: str
    correlation_id: str
    evaluation_id: str
    assessment_session_id: str
    assessment_question_id: str
    question_id: str
    attempt_id: str
    evidence_id: str
    correctness_score: float | None
    dimension_results: tuple[dict[str, Any], ...]
    correct_elements: tuple[str, ...]
    partial_elements: tuple[str, ...]
    incorrect_elements: tuple[str, ...]
    omitted_elements: tuple[str, ...]
    feedback_latex: str
    grounding_refs: tuple[dict[str, Any], ...]
    response_time_ms: int | None
    timing_quality: str
    review_status: str
    limitations: tuple[str, ...]
    evaluator_version: str = "assessment-evaluator@0.1"


@dataclass(frozen=True, slots=True)
class QuestionRating:
    record_id: str
    record_type: str
    schema_version: str
    created_at: str
    producer: str
    status: str
    correlation_id: str
    rating_id: str
    assessment_session_id: str
    assessment_question_id: str
    evaluation_id: str
    user_id: str
    perceived_difficulty: str
    comment: str | None
    submitted_at: str


@dataclass(frozen=True, slots=True)
class DifficultyDecision:
    record_id: str
    record_type: str
    schema_version: str
    created_at: str
    producer: str
    status: str
    correlation_id: str
    difficulty_decision_id: str
    assessment_session_id: str
    assessment_question_id: str
    evaluation_id: str
    previous_level: int
    next_level: int
    correctness_signal: dict[str, Any]
    timing_signal: dict[str, Any]
    student_rating: str
    tutoring_history_signal: dict[str, Any]
    missing_signals: tuple[str, ...]
    rationale: str
    policy_version: str = "assessment-difficulty@0.1"


@dataclass(frozen=True, slots=True)
class AssessmentEngineHandoff:
    """Factual assessment outcome supplied to the Tutoring Engine."""

    handoff_id: str
    assessment_session_id: str
    linked_tutoring_session_id: str | None
    course_id: str
    assessment_question_id: str
    question_id: str
    evidence_id: str
    evaluation_id: str
    rating_id: str
    difficulty_decision_id: str
    concept_ids: tuple[str, ...]
    correctness_score: float | None
    dimension_results: tuple[dict[str, Any], ...]
    correct_elements: tuple[str, ...]
    partial_elements: tuple[str, ...]
    incorrect_elements: tuple[str, ...]
    omitted_elements: tuple[str, ...]
    timing_quality: str
    student_rating: str
    recommended_focus: str
    grounding_refs: tuple[dict[str, Any], ...]
    created_at: str


@dataclass(slots=True)
class AssessmentSessionState:
    assessment_session_id: str
    course_id: str
    session_id: str
    user_id: str
    created_at: str
    correlation_id: str
    allowed_question_types: tuple[str, ...]
    target_concept: str
    current_difficulty: int
    course_context_version: str
    retrieval_snapshot_id: str
    diagnostic_logging: bool
    tutoring_history_signal: dict[str, Any]
    linked_tutoring_session_id: str | None = None
    active_question: AssessmentQuestion | None = None
    completed_questions: list[AssessmentQuestion] = field(default_factory=list)
    evaluations: list[AssessmentEvaluation] = field(default_factory=list)
    ratings: list[QuestionRating] = field(default_factory=list)
    difficulty_decisions: list[DifficultyDecision] = field(default_factory=list)
    engine_handoffs: list[AssessmentEngineHandoff] = field(default_factory=list)
    activity: list[dict[str, Any]] = field(default_factory=list)
    status: str = "ready"
    question_number: int = 0

