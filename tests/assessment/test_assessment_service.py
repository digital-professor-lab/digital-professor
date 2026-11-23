"""Assessment module behavior and schema-contract tests."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from digital_professor.assessment import AssessmentEngineHandoff, AssessmentService
from digital_professor.course_context.ingestion import DocumentIngestionService, SourceUpload
from digital_professor.retrieval.index import CourseRetrievalIndex
from digital_professor.runtime import DemoApplication, TimestampedTraceStore
from digital_professor.webapp.app import create_app


SYLLABUS = b"""110.108 Calculus I
Fall 2026
Course overview: Derivatives, limits, and integrals.
"""

NOTES = b"""110.108 Calculus I Lecture Notes
Derivative rules
The derivative measures the instantaneous rate of change of a function.
The product rule differentiates a product by differentiating each factor in turn.
The chain rule differentiates a composition by multiplying the outer derivative by the inner derivative.
"""


def _workspace():
    return DocumentIngestionService().ingest_course(
        [
            SourceUpload("calculus_syllabus.txt", "text/plain", SYLLABUS),
            SourceUpload("calculus_lecture_notes.txt", "text/plain", NOTES),
        ]
    )


def _service(tmp_path: Path, *, engine=None) -> tuple[AssessmentService, str]:
    workspace = _workspace()
    courses = {workspace.course_id: workspace}
    indexes = {workspace.course_id: CourseRetrievalIndex(workspace)}
    return (
        AssessmentService(
            courses,
            indexes,
            TimestampedTraceStore(tmp_path / "logs"),
            tutoring_engine_port=engine,
        ),
        workspace.course_id,
    )


def _schema(name: str) -> dict:
    path = Path("specs/schemas") / name
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonable(value):
    return json.loads(json.dumps(value))


def test_question_is_note_only_and_matches_json_schema(tmp_path: Path) -> None:
    service, course_id = _service(tmp_path)
    started = service.start(
        course_id=course_id,
        concept="derivative",
        allowed_question_types=("open_ended",),
    )

    state = service.sessions[started["assessment_session_id"]]
    question = state.active_question
    assert question is not None
    assert question.question_type == "open_ended"
    assert question.status == "active"
    assert question.grounding_refs
    assert {item["source_type"] for item in question.grounding_refs} == {"lecture_notes"}
    Draft202012Validator(_schema("assessment-question.schema.json")).validate(
        _jsonable(asdict(question))
    )
    Draft202012Validator(_schema("assessment-session.schema.json")).validate(
        _jsonable(started["session_record"])
    )


def test_response_is_non_binary_then_rating_creates_one_next_question(tmp_path: Path) -> None:
    service, course_id = _service(tmp_path)
    started = service.start(
        course_id=course_id,
        concept="derivative",
        allowed_question_types=("open_ended",),
        starting_difficulty=3,
    )
    assessment_id = started["assessment_session_id"]
    first_question = started["question"]["assessment_question_id"]

    response = service.submit_response(
        assessment_id,
        "A derivative describes change and uses a function.",
    )

    evaluation = response["evaluation"]
    assert 0 < evaluation["correctness_score"] < 1
    assert response["status"] == "awaiting_rating"
    assert evaluation["grounding_refs"]
    Draft202012Validator(_schema("assessment-evaluation.schema.json")).validate(
        _jsonable(evaluation)
    )

    continued = service.rate_and_continue(assessment_id, rating="just_right")

    assert continued["question"]["assessment_question_id"] != first_question
    decision = continued["difficulty_decision"]
    assert abs(decision["next_level"] - decision["previous_level"]) <= 1
    assert len(service.sessions[assessment_id].completed_questions) == 1
    assert service.sessions[assessment_id].active_question is not None
    Draft202012Validator(_schema("difficulty-decision.schema.json")).validate(
        _jsonable(decision)
    )
    rating = service.sessions[assessment_id].ratings[-1]
    Draft202012Validator(_schema("question-rating.schema.json")).validate(
        _jsonable(asdict(rating))
    )

    summary = service.end(assessment_id)
    Draft202012Validator(_schema("assessment-summary.schema.json")).validate(summary)
    assert summary["completed_question_count"] == 1
    assert summary["concept_evidence"][0]["evidence_status"] == "insufficient_evidence"


class _RecordingEngine:
    def __init__(self) -> None:
        self.handoffs: list[AssessmentEngineHandoff] = []

    def record_assessment_result(self, handoff: AssessmentEngineHandoff):
        self.handoffs.append(handoff)
        return None


def test_completed_cycle_can_inform_tutoring_engine_without_selecting_action(
    tmp_path: Path,
) -> None:
    engine = _RecordingEngine()
    service, course_id = _service(tmp_path, engine=engine)
    started = service.start(
        course_id=course_id,
        concept="derivative",
        allowed_question_types=("open_ended",),
        linked_tutoring_session_id="tutoring-session-1",
    )
    assessment_id = started["assessment_session_id"]

    service.submit_response(assessment_id, "A derivative describes change.")
    continued = service.rate_and_continue(assessment_id, rating="too_hard")

    assert len(engine.handoffs) == 1
    handoff = engine.handoffs[0]
    assert handoff.linked_tutoring_session_id == "tutoring-session-1"
    assert handoff.evidence_id
    assert handoff.evaluation_id
    assert handoff.concept_ids == ("derivative",)
    assert handoff.dimension_results
    assert handoff.grounding_refs
    assert handoff.recommended_focus in {"concept", "method", "execution", "communication"}
    assert continued["tutoring_engine_handoff"]["status"] == "recorded"
    assert continued["tutoring_engine_handoff"]["tutoring_action_id"] is None


def test_missing_engine_adapter_leaves_a_visible_pending_handoff(tmp_path: Path) -> None:
    service, course_id = _service(tmp_path)
    started = service.start(
        course_id=course_id,
        concept="derivative",
        allowed_question_types=("true_false",),
    )
    assessment_id = started["assessment_session_id"]
    service.submit_response(assessment_id, "true")

    continued = service.rate_and_continue(assessment_id, rating="just_right")

    assert continued["tutoring_engine_handoff"]["status"] == "pending_engine_integration"
    assert len(service.sessions[assessment_id].engine_handoffs) == 1


def test_api_runs_complete_assessment_cycle_and_exposes_activity(tmp_path: Path) -> None:
    runtime = DemoApplication(trace_store=TimestampedTraceStore(tmp_path / "logs"))
    workspace = _workspace()
    runtime.publish_course(workspace)
    client = TestClient(create_app(runtime=runtime))

    started = client.post(
        "/api/assessments",
        json={
            "course_id": workspace.course_id,
            "concept": "derivative",
            "question_types": ["true_false"],
            "starting_difficulty": 2,
        },
    )
    assert started.status_code == 200, started.text
    assessment_id = started.json()["assessment_session_id"]

    answered = client.post(
        f"/api/assessments/{assessment_id}/responses",
        json={"response": "true"},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["evaluation"]["correctness_score"] == 1.0

    rated = client.post(
        f"/api/assessments/{assessment_id}/ratings",
        json={"rating": "too_easy"},
    )
    assert rated.status_code == 200, rated.text
    assert rated.json()["difficulty_decision"]["next_level"] == 3

    activity = client.get(f"/api/assessments/{assessment_id}/activity")
    assert activity.status_code == 200
    events = [item["event"] for item in activity.json()["events"]]
    assert "assessment_question_presented" in events
    assert "assessment_response_received" in events
    assert "assessment_evaluated" in events
    assert "assessment_rating_recorded" in events

    ended = client.post(f"/api/assessments/{assessment_id}/end")
    assert ended.status_code == 200
    assert ended.json()["record_type"] == "AssessmentSummary"

