"""Contract tests for handwriting recognition and confirmation."""

from __future__ import annotations

import json

import pymupdf
import pytest

from digital_professor.interaction import (
    HandwritingEvidenceService,
    HandwritingLoggingConfiguration,
    HandwritingRecognitionFailure,
    HandwritingReview,
    HandwritingSubmissionInput,
    InMemoryArtifactStore,
    MockDelivery,
    MockTutoringEngine,
    OpenAIHandwritingRecognizer,
    RecognizerOutput,
    StudentEvidencePipeline,
    StubHandwritingRecognizer,
    TutoringTurnCoordinator,
)


def _output(**overrides: object) -> RecognizerOutput:
    values: dict[str, object] = {
        "provider": "stub",
        "model_version": "test-recognizer-1",
        "recognized_content": "$$2(x+3)=10$$\n\n$$x=2$$",
        "content_format": "markdown_tex",
        "alternatives": (),
        "ambiguities": (),
        "observed_steps": (
            {"page_number": 1, "region": "line 1", "content": "2(x+3)=10", "crossed_out": False},
            {"page_number": 1, "region": "line 2", "content": "x=2", "crossed_out": False},
        ),
        "page_count": 1,
        "processed_pages": (1,),
        "recognition_status": "recognized",
        "latency_ms": 12,
        "raw_provider_output": '{"provider":"raw"}',
    }
    values.update(overrides)
    return RecognizerOutput(**values)  # type: ignore[arg-type]


def _request(**overrides: object) -> HandwritingSubmissionInput:
    values: dict[str, object] = {
        "user_id": "student-7",
        "course_id": "course-1",
        "session_id": "session-20",
        "turn_id": "turn-3",
        "question_id": "question-4",
        "attempt_id": "attempt-2",
        "filename": "work.pdf",
        "media_type": "application/pdf",
        "artifact_bytes": b"original-tablet-pdf-bytes",
        "student_uncertainty": {"level": "unsure"},
    }
    values.update(overrides)
    return HandwritingSubmissionInput(**values)  # type: ignore[arg-type]


def _service(output: RecognizerOutput, *, diagnostic_logging: bool = False):
    store = InMemoryArtifactStore()
    engine = MockTutoringEngine()
    delivery = MockDelivery()
    coordinator = TutoringTurnCoordinator(StudentEvidencePipeline(store), engine, delivery)
    recognizer = StubHandwritingRecognizer(output)
    service = HandwritingEvidenceService(
        store,
        recognizer,
        coordinator,
        logging=HandwritingLoggingConfiguration(diagnostic_logging),
    )
    return service, store, engine, delivery, recognizer


def test_clear_handwriting_preserves_original_and_routes_only_after_acceptance() -> None:
    service, store, engine, delivery, recognizer = _service(_output())

    review = service.begin(_request())

    assert isinstance(review, HandwritingReview)
    assert store.read_binary(review.submission.original_artifact_ref) == b"original-tablet-pdf-bytes"
    assert review.submission.submitted_text is None
    assert review.submission.modality == "handwriting_upload"
    assert review.recognition.processed_pages == (1,)
    assert review.recognition.raw_output_ref is None
    assert review.confirmation_required is False
    assert engine.received_evidence == []
    assert delivery.received_actions == []
    assert recognizer.calls[0]["data"] == b"original-tablet-pdf-bytes"

    completed = service.confirm(
        review.recognition.recognition_id,
        confirmed_content=review.recognition.recognized_content,
        actor_id="student-7",
    )

    evidence = completed.result.evidence
    assert evidence.confirmed_content == review.recognition.recognized_content
    assert evidence.recognition_ref == review.recognition.recognition_id
    assert evidence.correction_refs == (completed.corrections[0].correction_id,)
    assert evidence.observed_steps == review.recognition.observed_steps
    assert engine.received_evidence == [evidence]
    assert delivery.received_actions[0] is completed.result.action
    assert [event.event_type for event in completed.result.trace_events] == [
        "submission", "recognition", "correction", "evidence_validated",
        "action_selected", "delivery",
    ]


def test_meaning_changing_ambiguity_blocks_handoff_until_resolved() -> None:
    ambiguity = {
        "page_number": 1,
        "region": "line 2 exponent",
        "raw_value": "x2",
        "candidates": ("x^2", "x_2"),
        "confidence": 0.55,
        "meaning_may_change": True,
        "description": "Exponent or subscript is unclear.",
    }
    service, _, engine, _, _ = _service(
        _output(ambiguities=(ambiguity,), recognition_status="confirmation_required")
    )
    review = service.begin(_request())
    assert isinstance(review, HandwritingReview)
    assert review.confirmation_required is True

    with pytest.raises(ValueError, match="Resolve every meaning-changing ambiguity"):
        service.confirm(
            review.recognition.recognition_id,
            confirmed_content=review.recognition.recognized_content,
            actor_id="student-7",
        )
    assert engine.received_evidence == []

    ambiguity_id = str(review.recognition.ambiguities[0]["ambiguity_id"])
    with pytest.raises(ValueError, match="Update the recognized work"):
        service.confirm(
            review.recognition.recognition_id,
            confirmed_content=review.recognition.recognized_content,
            actor_id="student-7",
            ambiguity_resolutions={ambiguity_id: "x^2"},
        )
    assert engine.received_evidence == []

    completed = service.confirm(
        review.recognition.recognition_id,
        confirmed_content="$$x^2=2$$",
        actor_id="student-7",
        ambiguity_resolutions={ambiguity_id: "x^2"},
    )
    assert completed.corrections[0].location["ambiguity_id"] == ambiguity_id
    assert completed.corrections[0].meaning_changed is True
    assert completed.result.evidence.unresolved_ambiguities == ()
    assert completed.result.evidence.observed_steps == ()
    assert engine.received_evidence == [completed.result.evidence]


def test_diagnostic_logging_controls_raw_provider_output() -> None:
    service, store, _, _, _ = _service(_output(), diagnostic_logging=True)
    review = service.begin(_request())
    assert isinstance(review, HandwritingReview)
    assert review.recognition.raw_output_ref is not None
    assert store.read_text(review.recognition.raw_output_ref) == '{"provider":"raw"}'


def test_recognition_failure_preserves_submission_but_creates_no_evidence() -> None:
    class FailingRecognizer:
        def recognize(self, **_: object) -> RecognizerOutput:
            raise TimeoutError("provider unavailable")

    store = InMemoryArtifactStore()
    engine = MockTutoringEngine()
    coordinator = TutoringTurnCoordinator(StudentEvidencePipeline(store), engine, MockDelivery())
    service = HandwritingEvidenceService(store, FailingRecognizer(), coordinator)

    failure = service.begin(_request())

    assert isinstance(failure, HandwritingRecognitionFailure)
    assert failure.error_code == "recognition_service_unavailable"
    assert store.read_binary(failure.submission.original_artifact_ref) == b"original-tablet-pdf-bytes"
    assert engine.received_evidence == []


def test_partial_multi_page_result_requires_review_and_retains_page_provenance() -> None:
    service, _, _, _, _ = _service(
        _output(page_count=3, processed_pages=(1, 2), recognition_status="recognized")
    )
    review = service.begin(_request())

    assert isinstance(review, HandwritingReview)
    assert review.recognition.recognition_status == "partial"
    assert review.recognition.page_count == 3
    assert review.recognition.processed_pages == (1, 2)
    assert review.confirmation_required is True


def test_openai_adapter_renders_bounded_pdf_pages_and_reports_partial() -> None:
    document = pymupdf.open()
    for number in range(1, 7):
        page = document.new_page()
        page.insert_text((72, 72), f"handwritten page {number}")
    pdf_bytes = document.tobytes()
    document.close()

    class FakeResponse:
        model = "vision-test-model"
        output_text = json.dumps({
            "transcription_markdown": "page-limited transcription",
            "steps": [
                {"page_number": 1, "region": "line 1", "content": "x=1", "crossed_out": False}
            ],
            "alternatives": [],
            "ambiguities": [],
            "incomplete": False,
        })

    class FakeResponses:
        def __init__(self) -> None:
            self.request: dict[str, object] | None = None

        def create(self, **kwargs: object) -> FakeResponse:
            self.request = kwargs
            return FakeResponse()

    class FakeClient:
        def __init__(self) -> None:
            self.responses = FakeResponses()

    client = FakeClient()
    recognizer = OpenAIHandwritingRecognizer(
        model="vision-test-model", client=client, max_pages=5  # type: ignore[arg-type]
    )

    output = recognizer.recognize(
        filename="six-pages.pdf", media_type="application/pdf", data=pdf_bytes
    )

    assert output.page_count == 6
    assert output.processed_pages == (1, 2, 3, 4, 5)
    assert output.recognition_status == "partial"
    assert output.model_version == "vision-test-model"
    assert client.responses.request is not None
    text_config = client.responses.request["text"]  # type: ignore[index]
    schema = text_config["format"]["schema"]  # type: ignore[index]
    definitions = schema["$defs"]
    assert "confidence" in definitions["_Alternative"]["required"]
    assert "confidence" in definitions["_Ambiguity"]["required"]
