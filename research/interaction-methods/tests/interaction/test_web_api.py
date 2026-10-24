"""HTTP-boundary checks for the typed tutoring-turn adapter."""

from fastapi.testclient import TestClient

from webapp.backend.app import app


client = TestClient(app)


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
