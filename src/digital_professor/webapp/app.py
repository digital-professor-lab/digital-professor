"""FastAPI application exposing the tested V1 turn through a small UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from digital_professor.course_context import JsonQuestionStore
from digital_professor.interaction import (
    InMemoryArtifactStore,
    MockDelivery,
    StudentEvidencePipeline,
    TutoringTurnCoordinator,
    TutoringTurnFailure,
    TypedSubmissionInput,
)
from digital_professor.retrieval import FixtureRetrievalGateway
from digital_professor.tutoring import InitialTutoringEngine


PROJECT_ROOT = Path(__file__).resolve().parents[3]
QUESTION_ID = "calc1.06-integral-applications.by-parts.adhoc-d7df1b60"


class TurnRequest(BaseModel):
    """Display-safe data accepted from the V1 chat composer."""

    text: str = Field(min_length=1, max_length=10_000)
    session_id: str = Field(default_factory=lambda: f"session-{uuid4()}")
    turn_id: str = Field(default_factory=lambda: f"turn-{uuid4()}")


def _build_coordinator() -> TutoringTurnCoordinator:
    question_store = JsonQuestionStore(
        (PROJECT_ROOT / "specs/examples/calc1.question-schema.xcosx.json",),
        course_title="Calculus I",
        course_context_path=PROJECT_ROOT
        / "research/knowledge-retrieval/retrieval-tool/data/course_context/calc1.course-context.json",
    )
    engine = InitialTutoringEngine(question_store, FixtureRetrievalGateway())
    return TutoringTurnCoordinator(
        StudentEvidencePipeline(InMemoryArtifactStore()), engine, MockDelivery()
    )


app = FastAPI(title="Digital Professor V1", version="0.1.0")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (Path(__file__).with_name("static") / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
def status() -> dict[str, Any]:
    return {
        "status": "ready",
        "course": "Calculus I",
        "question_id": QUESTION_ID,
        "capabilities": {
            "typed_turn": "available",
            "course_context": "fixture",
            "retrieval": "fixture",
            "handwriting": "coming_next",
            "voice": "future",
            "avatar": "future",
        },
    }


@app.post("/api/turns")
def create_turn(request: TurnRequest) -> dict[str, Any]:
    try:
        coordinator = _build_coordinator()
        result = coordinator.run_typed_turn(
            TypedSubmissionInput(
                user_id="local-demo-student",
                course_id="calc1",
                session_id=request.session_id,
                turn_id=request.turn_id,
                question_id=QUESTION_ID,
                attempt_id=f"attempt-{uuid4()}",
                submitted_text=request.text,
            )
        )
    except (LookupError, RuntimeError, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    if isinstance(result, TutoringTurnFailure):
        raise HTTPException(
            status_code=502,
            detail={"stage": result.failed_stage, "message": result.message},
        )

    return {
        "message": result.action.content.get("text", ""),
        "action_type": result.action.action_type,
        "grounding_refs": list(result.action.grounding_refs),
        "evidence_status": result.evidence.validation_status,
        "handoff_status": result.handoff_status,
        "trace": [event.event_type for event in result.trace_events],
        "correlation_id": result.evidence.correlation_id,
    }

