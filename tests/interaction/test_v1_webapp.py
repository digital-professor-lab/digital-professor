"""HTTP checks for the V1 browser integration shell."""

from fastapi.testclient import TestClient

from digital_professor.webapp.app import app


client = TestClient(app)


def test_status_distinguishes_working_and_future_capabilities() -> None:
    response = client.get("/api/status")

    assert response.status_code == 200
    capabilities = response.json()["capabilities"]
    assert capabilities["typed_turn"] == "available"
    assert capabilities["handwriting"] == "coming_next"
    assert capabilities["avatar"] == "future"


def test_typed_turn_runs_through_the_integrated_pipeline() -> None:
    response = client.post(
        "/api/turns",
        json={
            "text": "I chose $u=x$ and $dv=\\cos(x)dx$.",
            "session_id": "session-web-test",
            "turn_id": "turn-web-test",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action_type"] == "probe"
    assert payload["evidence_status"] == "valid"
    assert payload["handoff_status"] == "complete"
    assert payload["trace"][-1] == "delivery_recorded"


def test_empty_message_is_rejected_before_the_pipeline() -> None:
    response = client.post("/api/turns", json={"text": ""})

    assert response.status_code == 422
