"""FastAPI adapter for one V1 typed tutoring turn.

The HTTP layer translates browser input into the Interaction contract. It does
not diagnose the learner or choose how to teach; those responsibilities remain
behind the Tutoring Engine and Delivery ports.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
import os
from pathlib import Path
from typing import Any, Mapping

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from digital_professor.interaction import (
    InMemoryArtifactStore,
    HandwritingEvidenceService,
    HandwritingRecognitionFailure,
    HandwritingSubmissionInput,
    MockDelivery,
    MockTutoringEngine,
    OpenAIHandwritingRecognizer,
    RecordValidationError,
    StudentEvidencePipeline,
    TutoringTurnCoordinator,
    TypedSubmissionInput,
)


COMPONENT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[4]
load_dotenv(COMPONENT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env")


app = FastAPI(title="Digital Professor V1 Interaction API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

artifact_store = InMemoryArtifactStore()
coordinator = TutoringTurnCoordinator(
    StudentEvidencePipeline(artifact_store),
    MockTutoringEngine(),
    MockDelivery(),
)


class LazyOpenAIHandwritingRecognizer:
    """Delay API client creation so typed turns work without an API key."""

    def recognize(self, *, filename: str, media_type: str, data: bytes):
        return OpenAIHandwritingRecognizer().recognize(
            filename=filename, media_type=media_type, data=data
        )


handwriting_service = HandwritingEvidenceService(
    artifact_store,
    LazyOpenAIHandwritingRecognizer(),
    coordinator,
)


class TypedTurnRequest(BaseModel):
    """Browser representation of the typed-input contract."""

    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    turn_id: str = Field(min_length=1)
    question_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    submitted_text: str = Field(min_length=1, max_length=20_000)
    evidence_kind: str = "initial_attempt"
    parent_submission_id: str | None = None
    parent_evidence_id: str | None = None
    response_to_action_id: str | None = None
    student_explanation: str | None = None
    student_uncertainty: dict[str, Any] | None = None


class HandwritingConfirmationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmed_content: str = Field(min_length=1, max_length=30_000)
    actor_id: str = Field(min_length=1)
    ambiguity_resolutions: dict[str, str] = Field(default_factory=dict)


def _to_json(value: Any) -> Any:
    """Convert immutable domain records without changing the domain models."""

    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _to_json(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _to_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_to_json(item) for item in value]
    return value


def _public_handwriting_review(review: Any) -> dict[str, Any]:
    """Expose shared records without echoing the uploaded artifact bytes."""

    return {
        "submission": _to_json(review.submission),
        "recognition": _to_json(review.recognition),
        "confirmation_required": review.confirmation_required,
    }


@app.get("/api/health")
def health() -> dict[str, str | bool]:
    return {
        "status": "ok",
        "engine": "mock",
        "delivery": "mock",
        "handwriting_recognition_configured": bool(os.getenv("OPENAI_API_KEY")),
    }


@app.post("/api/turns")
def run_typed_turn(request: TypedTurnRequest) -> JSONResponse:
    try:
        result = coordinator.run_typed_turn(
            TypedSubmissionInput(
                user_id=request.user_id,
                course_id=request.course_id,
                session_id=request.session_id,
                turn_id=request.turn_id,
                question_id=request.question_id,
                attempt_id=request.attempt_id,
                submitted_text=request.submitted_text,
                evidence_kind=request.evidence_kind,  # validated by the domain pipeline
                parent_submission_id=request.parent_submission_id,
                parent_evidence_id=request.parent_evidence_id,
                response_to_action_id=request.response_to_action_id,
                student_explanation=request.student_explanation,
                student_uncertainty=request.student_uncertainty,
                client_metadata={"client": "v1_browser"},
            )
        )
    except RecordValidationError as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "errors": _to_json(exc.errors)},
        )
    return JSONResponse(content=_to_json(result))


@app.post("/api/handwriting/recognitions")
async def recognize_handwriting(
    file: UploadFile = File(...),
    user_id: str = Form(...),
    course_id: str = Form(...),
    session_id: str = Form(...),
    turn_id: str = Form(...),
    question_id: str = Form(...),
    attempt_id: str = Form(...),
    evidence_kind: str = Form("initial_attempt"),
    parent_submission_id: str | None = Form(None),
    parent_evidence_id: str | None = Form(None),
    response_to_action_id: str | None = Form(None),
    student_explanation: str | None = Form(None),
    student_uncertainty: str | None = Form(None),
    modality: str = Form("handwriting_upload"),
) -> JSONResponse:
    data = await file.read()
    media_type = file.content_type or "application/octet-stream"
    if media_type == "application/octet-stream":
        media_type = {
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }.get(Path(file.filename or "").suffix.lower(), media_type)
    try:
        outcome = handwriting_service.begin(
            HandwritingSubmissionInput(
                user_id=user_id,
                course_id=course_id,
                session_id=session_id,
                turn_id=turn_id,
                question_id=question_id,
                attempt_id=attempt_id,
                filename=file.filename or "handwriting-upload",
                media_type=media_type,
                artifact_bytes=data,
                modality=modality,  # validated by the domain service
                evidence_kind=evidence_kind,
                parent_submission_id=parent_submission_id,
                parent_evidence_id=parent_evidence_id,
                response_to_action_id=response_to_action_id,
                student_explanation=student_explanation,
                student_uncertainty=(
                    {"level": student_uncertainty} if student_uncertainty else None
                ),
                client_metadata={"client": "v1_browser"},
            )
        )
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    if isinstance(outcome, HandwritingRecognitionFailure):
        content = _to_json(outcome)
        content["detail"] = outcome.message
        return JSONResponse(status_code=503, content=content)
    return JSONResponse(content=_public_handwriting_review(outcome))


@app.post("/api/handwriting/recognitions/{recognition_id}/confirm")
def confirm_handwriting(
    recognition_id: str, request: HandwritingConfirmationRequest
) -> JSONResponse:
    try:
        result = handwriting_service.confirm(
            recognition_id,
            confirmed_content=request.confirmed_content,
            actor_id=request.actor_id,
            ambiguity_resolutions=request.ambiguity_resolutions,
        )
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return JSONResponse(content=_to_json(result))
