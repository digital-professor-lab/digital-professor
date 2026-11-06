"""One real contract path across Interaction, Question Schema and Retrieval."""

from __future__ import annotations

from pathlib import Path

from digital_professor.course_context import JsonQuestionStore
from digital_professor.interaction import (
    InMemoryArtifactStore,
    MockDelivery,
    StudentEvidencePipeline,
    TutoringTurnCoordinator,
    TypedSubmissionInput,
)
from digital_professor.interaction.models import TutoringTurnResult
from digital_professor.retrieval import FixtureRetrievalGateway
from digital_professor.tutoring import InitialTutoringEngine


PROJECT_ROOT = Path(__file__).resolve().parents[2]
QUESTION_ID = "calc1.06-integral-applications.by-parts.adhoc-d7df1b60"


def _coordinator() -> tuple[TutoringTurnCoordinator, InitialTutoringEngine]:
    store = JsonQuestionStore(
        (PROJECT_ROOT / "specs/examples/calc1.question-schema.xcosx.json",),
        course_title="Calculus I",
        course_context_path=PROJECT_ROOT
        / "research/knowledge-retrieval/retrieval-tool/data/course_context/calc1.course-context.json",
    )
    engine = InitialTutoringEngine(store, FixtureRetrievalGateway())
    coordinator = TutoringTurnCoordinator(
        StudentEvidencePipeline(InMemoryArtifactStore()), engine, MockDelivery()
    )
    return coordinator, engine


def _request(text: str) -> TypedSubmissionInput:
    return TypedSubmissionInput(
        user_id="student-integration",
        course_id="calc1",
        session_id="session-integration",
        turn_id="turn-1",
        question_id=QUESTION_ID,
        attempt_id="attempt-1",
        submitted_text=text,
    )


def test_help_request_retrieves_course_evidence_and_records_delivery() -> None:
    coordinator, engine = _coordinator()

    result = coordinator.run_typed_turn(
        _request("I'm stuck. Please explain how I should begin.")
    )

    assert isinstance(result, TutoringTurnResult)
    assert result.action.action_type == "explain"
    assert result.action.grounding_refs
    assert engine.retrieval_outcomes[0].status in {"supported", "partial"}
    assert engine.received_delivery_results == [result.delivery]
    assert result.action.learner_state_id in engine.learner_states
    assert engine.learner_states[result.action.learner_state_id].status == "current"
    assert result.trace_events[-1].event_type == "delivery_recorded"


def test_student_work_uses_probe_without_unnecessary_retrieval() -> None:
    coordinator, engine = _coordinator()

    result = coordinator.run_typed_turn(_request("I chose $u=x$ and $dv=\\cos(x)dx$."))

    assert isinstance(result, TutoringTurnResult)
    assert result.action.action_type == "probe"
    assert result.action.grounding_refs == ()
    assert engine.retrieval_outcomes == []

