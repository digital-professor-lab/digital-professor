"""HTTP-boundary checks for the typed tutoring-turn adapter."""

import importlib

from fastapi.testclient import TestClient

from digital_professor.interaction import (
    HandwritingEvidenceService,
    InMemoryArtifactStore,
    MockDelivery,
    MockTutoringEngine,
    RecognizerOutput,
    StudentEvidencePipeline,
    StubHandwritingRecognizer,
    TutoringTurnCoordinator,
)
from webapp.backend.app import app


client = TestClient(app)
app_module = importlib.import_module("webapp.backend.app")


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "user_id": "browser-student",
        "course_id": "demo-course",
        "session_id": "demo-session",
        "turn_id": "turn-1",
        "question_id": "question-1",
        "attempt_id": "attempt-1",
        "submitted_text": "$$2(x+3)=10$$ so $x=2$.",
        "student_explanation": "I divided after simplifying.",
        "student_uncertainty": {"level": "unsure"},
    }
    payload.update(overrides)
    return payload


def test_browser_turn_preserves_text_and_completes_mock_handoffs() -> None:
    response = client.post("/api/turns", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["submission"]["submitted_text"] == _payload()["submitted_text"]
    assert body["evidence"]["confirmed_content"] == _payload()["submitted_text"]
    assert body["evidence"]["recognition_ref"] is None
    assert body["action"]["action_type"] == "probe"
    assert body["delivery"]["presentation_status"] == "presented"
    assert [event["event_type"] for event in body["trace_events"]] == [
        "submission",
        "evidence_validated",
        "action_selected",
        "delivery",
    ]


def test_browser_turn_rejects_whitespace_before_downstream_handoff() -> None:
    response = client.post("/api/turns", json=_payload(submitted_text="   "))

    assert response.status_code == 422


def test_handwriting_http_flow_reviews_then_routes_confirmed_evidence(monkeypatch) -> None:
    output = RecognizerOutput(
        provider="stub",
        model_version="test-1",
        recognized_content="$$x^2=4$$",
        content_format="markdown_tex",
        alternatives=(),
        ambiguities=(),
        observed_steps=(
            {"page_number": 1, "region": "line 1", "content": "x^2=4", "crossed_out": False},
        ),
        page_count=1,
        processed_pages=(1,),
        recognition_status="recognized",
        latency_ms=1,
    )
    store = InMemoryArtifactStore()
    coordinator = TutoringTurnCoordinator(
        StudentEvidencePipeline(store), MockTutoringEngine(), MockDelivery()
    )
    service = HandwritingEvidenceService(store, StubHandwritingRecognizer(output), coordinator)
    monkeypatch.setattr(app_module, "handwriting_service", service)

    recognition_response = client.post(
        "/api/handwriting/recognitions",
        data={
            "user_id": "student-7",
            "course_id": "course-1",
            "session_id": "session-1",
            "turn_id": "turn-1",
            "question_id": "question-1",
            "attempt_id": "attempt-1",
            "student_uncertainty": "unsure",
        },
        files={"file": ("work.png", b"original-image", "image/png")},
    )

    assert recognition_response.status_code == 200
    review = recognition_response.json()
    assert review["recognition"]["recognized_content"] == "$$x^2=4$$"
    assert review["submission"]["submitted_text"] is None

    confirm_response = client.post(
        f"/api/handwriting/recognitions/{review['recognition']['recognition_id']}/confirm",
        json={
            "confirmed_content": "$$x^2=4$$",
            "actor_id": "student-7",
            "ambiguity_resolutions": {},
        },
    )

    assert confirm_response.status_code == 200
    completed = confirm_response.json()
    assert completed["result"]["evidence"]["recognition_ref"] == review["recognition"]["recognition_id"]
    assert completed["result"]["handoff_status"] == "complete"
