"""FastAPI adapter for one V1 typed tutoring turn.

The HTTP layer translates browser input into the Interaction contract. It does
not diagnose the learner or choose how to teach; those responsibilities remain
behind the Tutoring Engine and Delivery ports.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any, Mapping

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from digital_professor.interaction import (
    InMemoryArtifactStore,
    MockDelivery,
    MockTutoringEngine,
    RecordValidationError,
    StudentEvidencePipeline,
    TutoringTurnCoordinator,
    TypedSubmissionInput,
)


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


def _to_json(value: Any) -> Any:
    """Convert immutable domain records without changing the domain models."""

    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _to_json(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _to_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_to_json(item) for item in value]
    return value


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "engine": "mock", "delivery": "mock"}


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
