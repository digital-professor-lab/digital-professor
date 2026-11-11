"""FastAPI entry point for the integrated Digital Professor demo."""

from __future__ import annotations

import html
import logging
import os
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from dataclasses import replace

from digital_professor.course_context.generator import (
    CourseContextGenerationError,
    CourseContextGenerator,
    validate_and_flag,
)
from digital_professor.course_context.ingestion import (
    DocumentIngestionService,
    IngestionError,
    SourceUpload,
)
from digital_professor.providers import OpenAICompatibleProvider, ProviderConfiguration
from digital_professor.runtime import DemoApplication
from digital_professor.interaction import OpenAIHandwritingRecognizer


PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


class SessionRequest(BaseModel):
    course_id: str
    question: str = Field(min_length=1, max_length=10_000)
    diagnostic_logging: bool = False


class TurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)


class HandwritingConfirmationRequest(BaseModel):
    recognition_id: str
    confirmed_content: str = Field(min_length=1, max_length=30_000)
    ambiguity_resolutions: dict[str, str] = Field(default_factory=dict)


class ProviderSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=200)
    base_url: str | None = None
    input_cost_per_million: float | None = Field(default=None, ge=0)
    output_cost_per_million: float | None = Field(default=None, ge=0)
    handwriting_model: str = Field(min_length=1, max_length=200)


class CourseNameRequest(BaseModel):
    course_name: str = Field(min_length=1, max_length=200)


class CourseContextFieldUpdate(BaseModel):
    entity: str
    id: str
    field: str
    value: Any


class CourseContextUpdateRequest(BaseModel):
    updates: list[CourseContextFieldUpdate]


def _configured_provider(
    config: ProviderConfiguration | None = None,
) -> OpenAICompatibleProvider | None:
    config = config or ProviderConfiguration.from_environment()
    return OpenAICompatibleProvider(config) if config.api_key else None


def _configured_cc_generator(
    config: ProviderConfiguration,
) -> CourseContextGenerator | None:
    if not config.api_key:
        return None
    return CourseContextGenerator(
        base_url=config.base_url,
        model=config.model,
        api_key=config.api_key,
    )


def create_app(*, runtime: DemoApplication | None = None) -> FastAPI:
    app = FastAPI(title="Digital Professor integrated demo", version="0.2.0")
    provider_config = ProviderConfiguration.from_environment()
    app.state.provider_config = provider_config
    app.state.handwriting_model = os.getenv("OPENAI_HANDWRITING_MODEL", "gpt-4o-mini")
    app.state.runtime = runtime or DemoApplication(_configured_provider(provider_config))
    app.state.ingestion = DocumentIngestionService()
    app.state.cc_generator = _configured_cc_generator(provider_config)
    app.state.handwriting_recognizer = None
    app.state.pending_syllabus = None
    app.state.pending_notes = []

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (Path(__file__).with_name("static") / "index.html").read_text(
            encoding="utf-8"
        )

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        config = app.state.provider_config
        return {
            "status": "ready" if app.state.runtime.courses else "course_setup_required",
            "ready_for_query": bool(app.state.runtime.courses),
            "courses": len(app.state.runtime.courses),
            "sessions": len(app.state.runtime.sessions),
            "course_setup": {
                "syllabus_uploaded": app.state.pending_syllabus is not None,
                "notes_uploaded": len(app.state.pending_notes),
            },
            "provider": {
                "name": config.provider,
                "model": config.model,
                "base_url": config.base_url,
                "api_key_env": config.api_key_env,
                "key_configured": bool(config.api_key),
                "input_cost_per_million": config.input_cost_per_million,
                "output_cost_per_million": config.output_cost_per_million,
                "handwriting_model": app.state.handwriting_model,
            },
            "capabilities": {
                "course_ingestion": "available",
                "typed_multi_turn": "available",
                "source_links": "available",
                "diagnostic_logging": "available",
                "handwriting": "available_with_openai_key",
                "office_hours": "future",
                "assessments": "future",
            },
        }

    @app.post("/api/provider/test")
    def test_provider() -> dict[str, Any]:
        provider = OpenAICompatibleProvider(app.state.provider_config)
        result = provider.test_connection()
        if result["ok"]:
            app.state.runtime.provider = provider
        return result

    @app.put("/api/provider/settings")
    def update_provider_settings(request: ProviderSettingsRequest) -> dict[str, Any]:
        current = app.state.provider_config
        config = ProviderConfiguration(
            provider=request.provider,
            model=request.model,
            base_url=request.base_url.strip() if request.base_url else None,
            api_key_env=current.api_key_env,
            input_cost_per_million=request.input_cost_per_million,
            output_cost_per_million=request.output_cost_per_million,
        )
        app.state.provider_config = config
        app.state.handwriting_model = request.handwriting_model
        app.state.handwriting_recognizer = None
        app.state.runtime.provider = _configured_provider(config)
        return {
            "ok": True,
            "message": "Runtime provider settings updated. The API key remains server-side.",
            "provider": config.provider,
            "model": config.model,
            "base_url": config.base_url,
            "input_cost_per_million": config.input_cost_per_million,
            "output_cost_per_million": config.output_cost_per_million,
            "handwriting_model": app.state.handwriting_model,
            "api_key_env": config.api_key_env,
            "key_configured": bool(config.api_key),
        }

    @app.get("/api/courses")
    def list_courses() -> list[dict[str, Any]]:
        return [_course_summary(course) for course in app.state.runtime.courses.values()]

    @app.post("/api/course-setup/syllabus")
    async def upload_syllabus(file: UploadFile = File(...)) -> dict[str, Any]:
        upload = SourceUpload(
            filename=file.filename or "syllabus-upload",
            media_type=file.content_type or "application/octet-stream",
            data=await file.read(),
        )
        app.state.pending_syllabus = upload
        return {"status": "received", "filename": upload.filename}

    @app.post("/api/course-setup/notes")
    async def upload_notes(files: list[UploadFile] = File(...)) -> dict[str, Any]:
        uploads = [
            SourceUpload(
                filename=file.filename or "notes-upload",
                media_type=file.content_type or "application/octet-stream",
                data=await file.read(),
            )
            for file in files
        ]
        app.state.pending_notes = uploads
        return {
            "status": "received",
            "files": [upload.filename for upload in uploads],
        }

    @app.post("/api/course-setup/publish")
    def prepare_course() -> dict[str, Any]:
        if app.state.pending_syllabus is None:
            raise HTTPException(status_code=422, detail="Upload a syllabus first.")
        if not app.state.pending_notes:
            raise HTTPException(status_code=422, detail="Upload one or more notes files first.")
        try:
            workspace = app.state.ingestion.ingest_course(
                [app.state.pending_syllabus, *app.state.pending_notes]
            )
        except IngestionError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        workspace = _enrich_with_course_context(workspace, app.state.cc_generator)
        app.state.runtime.publish_course(workspace)
        return _course_summary(workspace)

    @app.post("/api/courses")
    async def ingest_course(files: list[UploadFile] = File(...)) -> dict[str, Any]:
        uploads = [
            SourceUpload(
                filename=file.filename or "upload",
                media_type=file.content_type or "application/octet-stream",
                data=await file.read(),
            )
            for file in files
        ]
        try:
            workspace = app.state.ingestion.ingest_course(uploads)
        except IngestionError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        workspace = _enrich_with_course_context(workspace, app.state.cc_generator)
        app.state.runtime.publish_course(workspace)
        return _course_summary(workspace)

    @app.get("/api/courses/{course_id}")
    def get_course(course_id: str) -> dict[str, Any]:
        course = app.state.runtime.courses.get(course_id)
        if course is None:
            raise HTTPException(status_code=404, detail="Course not found")
        return _course_summary(course, include_topics=True)

    @app.patch("/api/courses/{course_id}")
    def rename_course(course_id: str, request: CourseNameRequest) -> dict[str, Any]:
        try:
            course = app.state.runtime.rename_course(course_id, request.course_name)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return _course_summary(course, include_topics=True)

    @app.get("/api/courses/{course_id}/course-context")
    def get_course_context(course_id: str) -> dict[str, Any]:
        course = app.state.runtime.courses.get(course_id)
        if course is None:
            raise HTTPException(status_code=404, detail="Course not found")
        if course.course_context is None:
            raise HTTPException(status_code=404, detail="No CourseContext for this course")
        return {
            "course_context": course.course_context,
            "status": course.course_context_status,
            "review": course.course_context_review,
        }

    @app.patch("/api/courses/{course_id}/course-context")
    def update_course_context(
        course_id: str, request: CourseContextUpdateRequest
    ) -> dict[str, Any]:
        try:
            updates = [u.model_dump() for u in request.updates]
            course = app.state.runtime.update_course_context(course_id, updates)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "course_context": course.course_context,
            "status": course.course_context_status,
            "review": course.course_context_review,
        }

    @app.get(
        "/api/courses/{course_id}/sources/{document_id}", response_class=HTMLResponse
    )
    def view_source(
        course_id: str,
        document_id: str,
        page: int = 1,
        line_start: int = 1,
        line_end: int = 1,
    ) -> str:
        course = app.state.runtime.courses.get(course_id)
        if course is None:
            raise HTTPException(status_code=404, detail="Course not found")
        document = next(
            (doc for doc in course.documents if doc.document_id == document_id), None
        )
        if document is None or page < 1 or page > len(document.pages):
            raise HTTPException(status_code=404, detail="Source location not found")
        rows = []
        for number, line in enumerate(document.pages[page - 1], 1):
            selected = line_start <= number <= line_end
            rows.append(
                f'<div class="line {"selected" if selected else ""}">'
                f'<span>{number}</span>{html.escape(line)}</div>'
            )
        return (
            "<!doctype html><meta charset='utf-8'><title>Source passage</title>"
            "<style>body{font:16px/1.55 system-ui;margin:32px;max-width:1000px}"
            ".line{display:grid;grid-template-columns:55px 1fr;padding:4px 8px}"
            ".line span{color:#667085}.selected{background:#fff0a8}</style>"
            f"<h1>{html.escape(document.filename)}</h1><p>Page {page}, "
            f"lines {line_start}-{line_end}</p>{''.join(rows)}"
        )

    @app.post("/api/sessions")
    def start_session(request: SessionRequest) -> dict[str, Any]:
        try:
            session = app.state.runtime.start_session(
                course_id=request.course_id,
                question=request.question,
                diagnostic_logging=request.diagnostic_logging,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {
            "session_id": session.session_id,
            "course_name": session.course.course_name,
            "diagnostic_logging": session.diagnostic_logging,
        }

    @app.post("/api/sessions/{session_id}/turns")
    def create_turn(session_id: str, request: TurnRequest) -> dict[str, Any]:
        try:
            return app.state.runtime.run_turn(session_id, request.text)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        try:
            return app.state.runtime.session_snapshot(session_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.get("/api/sessions/{session_id}/activity")
    def get_session_activity(session_id: str) -> dict[str, Any]:
        """Return a bounded, student-safe view derived from backend trace files."""
        try:
            return {"turns": app.state.runtime.activity_summary(session_id)}
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post("/api/sessions/{session_id}/handwriting/recognitions")
    async def recognize_handwriting(
        session_id: str, file: UploadFile = File(...)
    ) -> dict[str, Any]:
        try:
            recognizer = app.state.handwriting_recognizer
            if recognizer is None:
                recognizer = OpenAIHandwritingRecognizer(model=app.state.handwriting_model)
                app.state.handwriting_recognizer = recognizer
            return app.state.runtime.begin_handwriting(
                session_id,
                filename=file.filename or "handwriting-upload",
                media_type=file.content_type or "application/octet-stream",
                data=await file.read(),
                recognizer=recognizer,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.post("/api/sessions/{session_id}/handwriting/confirmations")
    def confirm_handwriting(
        session_id: str, request: HandwritingConfirmationRequest
    ) -> dict[str, Any]:
        try:
            return app.state.runtime.confirm_handwriting(
                session_id,
                recognition_id=request.recognition_id,
                confirmed_content=request.confirmed_content,
                ambiguity_resolutions=request.ambiguity_resolutions,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    return app


def _enrich_with_course_context(
    workspace,
    generator: CourseContextGenerator | None,
):
    """Generate, validate, and flag a CourseContext; fall back gracefully on any failure.

    Retries generation once when the first attempt produces a structurally invalid
    CourseContext — LLM output is stochastic and a second pass often passes validation.
    """
    if generator is None:
        return workspace
    syllabus_doc = next(
        (d for d in workspace.documents if d.document_type == "syllabus"), None
    )
    if syllabus_doc is None:
        return workspace
    syllabus_text = "\n".join(line for page in syllabus_doc.pages for line in page)

    cc = status = review = None
    generation_failed = False
    for _attempt in range(2):
        try:
            cc = generator.generate(syllabus_text)
            generation_failed = False
        except (CourseContextGenerationError, Exception) as exc:
            _log.warning("CourseContext generation attempt %d failed: %s", _attempt + 1, exc, exc_info=True)
            generation_failed = True
            continue
        try:
            status, review = validate_and_flag(cc)
        except Exception:
            status, review = "validated", None
        if status != "validation_failed":
            break
        cc = None

    if generation_failed and cc is None:
        return replace(workspace, course_context_status="generation_failed")
    if status == "validation_failed":
        return replace(workspace, course_context_status="validation_failed")
    return replace(
        workspace,
        course_context=cc,
        course_context_status=status,
        course_context_review=review,
    )


def _course_summary(course, *, include_topics: bool = False) -> dict[str, Any]:
    result = {
        "course_id": course.course_id,
        "course_name": course.course_name,
        "course_number": course.course_number,
        "term": course.term,
        "overview": course.overview,
        "consistency_status": course.consistency_status,
        "consistency_notes": list(course.consistency_notes),
        "status": course.status,
        "documents": [
            {
                "document_id": doc.document_id,
                "filename": doc.filename,
                "document_type": doc.document_type,
                "content_version": doc.content_version,
                "page_count": doc.page_count,
                "chunk_count": len(doc.chunks),
            }
            for doc in course.documents
        ],
    }
    if include_topics:
        result["topics"] = list(course.topics)
    if course.course_context_status:
        result["course_context_status"] = course.course_context_status
        review = course.course_context_review
        result["course_context_review_summary"] = (
            review["summary"] if review else None
        )
    return result


app = create_app()
