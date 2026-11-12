"""HTTP checks for the V1 browser integration shell."""

from fastapi.testclient import TestClient

from digital_professor.webapp.app import app


client = TestClient(app)


def test_status_distinguishes_working_and_future_capabilities() -> None:
    response = client.get("/api/status")

    assert response.status_code == 200
    capabilities = response.json()["capabilities"]
    assert capabilities["typed_multi_turn"] == "available"
    assert capabilities["course_ingestion"] == "available"
    assert capabilities["handwriting"] == "available_with_compatible_vision_provider"
    assert capabilities["office_hours"] == "future"


def test_browser_shell_exposes_course_chat_and_provider_surfaces() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Course sources" in response.text
    assert "Tutoring chat" in response.text
    assert "Provider settings" in response.text
    assert 'id="syllabusForm"' in response.text
    assert 'id="notesForm"' in response.text
    assert "katex" in response.text.lower()
    assert "typingBubble" in response.text
    assert "renderRichText" in response.text
    assert "Activity log" in response.text
    assert "Attach handwritten work" in response.text
    assert "loadActivity" in response.text
    assert "$$display equation$$" in response.text
    assert "Course match:" in response.text
    assert 'capture="environment"' in response.text
    assert "Take a photo" in response.text
    assert "drop a handwritten image or PDF here" in response.text
    assert "supportedHandwriting" in response.text
    assert "drop-active" in response.text
    assert 'id="handwritingProgress"' in response.text
    assert 'id="recognizedPreview"' in response.text
    assert "updateRecognizedPreview" in response.text
    assert 'id="courseProgress"' in response.text
    assert 'id="providerProgress"' in response.text
    assert "Model / version" in response.text
    assert 'id="consistencyOverride"' in response.text
    assert 'id="confirmMismatchButton"' in response.text
    assert "course_mismatch_confirmation_required" in response.text
    assert "Question Schema" not in response.text
    assert "Handoff log" not in response.text


def test_empty_message_is_rejected_before_the_pipeline() -> None:
    response = client.post("/api/sessions/missing/turns", json={"text": ""})

    assert response.status_code == 422
