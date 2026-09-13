"""FastAPI adapter around the reusable recognition and tutoring services."""

from __future__ import annotations

import re
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from openai import APIConnectionError, APIStatusError, AuthenticationError, OpenAI, RateLimitError
from pydantic import BaseModel, Field

from digital_professor import (
    RecognitionService,
    SkillInstructions,
    ingest_document,
    load_settings,
    load_skill_instructions,
    faster_whisper_available,
    recognize_with_tesseract,
    transcribe_with_faster_whisper,
    tesseract_available,
)


app = FastAPI(title="Digital Professor API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sources: dict[str, "SourceRecord"] = {}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
TRANSCRIPTION_MODELS = [
    "gpt-transcribe",
    "gpt-4o-transcribe",
    "gpt-4o-mini-transcribe",
    "whisper-1",
]
LOCAL_TRANSCRIPTION_MODELS = ["tiny", "base", "small"]
SUPPORTED_AUDIO_SUFFIXES = {".flac", ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".ogg", ".wav", ".webm"}


def current_settings():
    """Reload the root environment regardless of the server's launch directory."""
    return load_settings(PROJECT_ROOT / ".env")


def provider_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AuthenticationError):
        return HTTPException(
            status_code=401,
            detail="The configured API key was rejected. Check OPENAI_API_KEY in the root .env.",
        )
    if isinstance(exc, RateLimitError):
        return HTTPException(
            status_code=429,
            detail="The provider rate limit or account quota was reached. Try again shortly or check account usage.",
        )
    if isinstance(exc, APIConnectionError):
        return HTTPException(
            status_code=503,
            detail="The backend could not connect to the model provider. Check the network connection and try again.",
        )
    if isinstance(exc, APIStatusError):
        return HTTPException(
            status_code=502,
            detail=f"The model provider returned HTTP {exc.status_code}: {exc.message}",
        )
    return HTTPException(status_code=500, detail=f"Tutor request failed: {exc}")


class CourseMetadata(BaseModel):
    course_name: str | None = None
    course_code: str | None = None
    term: str | None = None


class SourceRecord(BaseModel):
    id: str
    filename: str
    source_type: str
    page_count: int
    text: str
    preview: str
    course: CourseMetadata | None = None
    request_metadata: list[dict] = Field(default_factory=list)
    recognition_method: str


class PublicSource(BaseModel):
    id: str
    filename: str
    source_type: str
    page_count: int
    preview: str
    course: CourseMetadata | None = None
    request_metadata: list[dict] = Field(default_factory=list)
    recognition_method: str


class ProviderConfig(BaseModel):
    provider: str = "OpenAI"
    model: str
    api_key_configured: bool
    input_cost_per_1m: float | None
    output_cost_per_1m: float | None
    models: list[str]
    skills: SkillInstructions
    recognition_provider: str
    tesseract_available: bool
    transcription_model: str
    transcription_models: list[str]
    transcription_provider: str
    local_transcription_models: list[str]
    faster_whisper_available: bool


class TranscriptionResult(BaseModel):
    text: str
    provider: str
    model: str
    elapsed_seconds: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10_000)
    model: str | None = None
    input_cost_per_1m: float | None = Field(default=None, ge=0)
    output_cost_per_1m: float | None = Field(default=None, ge=0)
    skills: SkillInstructions | None = None


def _public(record: SourceRecord) -> PublicSource:
    return PublicSource(**record.model_dump(exclude={"text"}))


def _course_metadata(text: str) -> CourseMetadata:
    """Return conservative syllabus metadata without inventing absent fields."""
    lines = [line.strip() for line in text.splitlines() if line.strip()][:40]
    code_pattern = re.compile(r"\b[A-Z]{2,}(?:[ -][A-Z]{2,})?[ -]?\d{3,4}[A-Z]?\b")
    term_pattern = re.compile(
        r"\b(Spring|Summer|Fall|Winter)\s+20\d{2}\b", re.IGNORECASE
    )
    code = next((match.group(0) for line in lines if (match := code_pattern.search(line))), None)
    term = next((match.group(0) for line in lines if (match := term_pattern.search(line))), None)
    candidates = [
        line
        for line in lines
        if 4 <= len(line) <= 120
        and not re.search(r"syllabus|instructor|office|email|semester", line, re.I)
    ]
    name = candidates[0] if candidates else None
    if name and code:
        name = re.sub(re.escape(code), "", name, flags=re.IGNORECASE).strip(" :-–—") or None
    return CourseMetadata(course_name=name, course_code=code, term=term)


@app.get("/api/health")
def health() -> dict:
    runtime = current_settings()
    return {"status": "ok", "api_key_configured": runtime.api_enabled}


@app.get("/api/config", response_model=ProviderConfig)
def provider_config() -> ProviderConfig:
    runtime = current_settings()
    models = [runtime.openai_model]
    if runtime.api_enabled:
        try:
            available = OpenAI(api_key=runtime.openai_api_key).models.list()
            models = sorted({model.id for model in available.data})
            if runtime.openai_model not in models:
                models.insert(0, runtime.openai_model)
        except Exception:
            # Configuration should remain usable during a transient provider outage.
            pass
    return ProviderConfig(
        model=runtime.openai_model,
        api_key_configured=runtime.api_enabled,
        input_cost_per_1m=runtime.input_cost_per_1m,
        output_cost_per_1m=runtime.output_cost_per_1m,
        models=models,
        skills=load_skill_instructions(),
        recognition_provider="openai_vision",
        tesseract_available=tesseract_available(),
        transcription_model="gpt-4o-mini-transcribe",
        transcription_models=TRANSCRIPTION_MODELS,
        transcription_provider="openai",
        local_transcription_models=LOCAL_TRANSCRIPTION_MODELS,
        faster_whisper_available=faster_whisper_available(),
    )


@app.post("/api/transcriptions", response_model=TranscriptionResult)
async def transcribe_audio(
    file: UploadFile = File(...),
    provider: str = Form("openai"),
    model: str = Form("gpt-4o-mini-transcribe"),
) -> TranscriptionResult:
    runtime = current_settings()
    if provider == "openai" and not runtime.api_enabled:
        raise HTTPException(status_code=503, detail="Transcription requires OPENAI_API_KEY in the backend .env.")
    if provider == "openai" and model not in TRANSCRIPTION_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported transcription model.")
    if provider == "faster_whisper" and model not in LOCAL_TRANSCRIPTION_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported local Whisper model.")
    if provider == "faster_whisper" and not faster_whisper_available():
        raise HTTPException(
            status_code=503,
            detail="The local faster-whisper baseline is not installed. Install it with `python -m pip install faster-whisper` and restart the backend.",
        )
    if provider not in {"openai", "faster_whisper"}:
        raise HTTPException(status_code=400, detail="Unsupported transcription provider.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Audio exceeds the 20 MB demo limit.")
    suffix = Path(file.filename or "recording.webm").suffix.lower()
    if suffix not in SUPPORTED_AUDIO_SUFFIXES:
        raise HTTPException(status_code=415, detail="Unsupported audio format.")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary.write(data)
            temporary_path = Path(temporary.name)
        started = time.perf_counter()
        if provider == "faster_whisper":
            text = transcribe_with_faster_whisper(temporary_path, model)
            usage = None
        else:
            with temporary_path.open("rb") as audio:
                result = OpenAI(api_key=runtime.openai_api_key).audio.transcriptions.create(
                    model=model,
                    file=audio,
                )
            text = result.text.strip()
            usage = getattr(result, "usage", None)
        elapsed = time.perf_counter() - started
        return TranscriptionResult(
            text=text,
            provider=provider,
            model=model,
            elapsed_seconds=elapsed,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise provider_error(exc) from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@app.get("/api/sources", response_model=list[PublicSource])
def list_sources() -> list[PublicSource]:
    return [_public(record) for record in sources.values()]


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: str) -> dict[str, bool]:
    if sources.pop(source_id, None) is None:
        raise HTTPException(status_code=404, detail="Source not found.")
    return {"deleted": True}


@app.post("/api/sources", response_model=PublicSource)
async def add_source(
    file: UploadFile = File(...),
    source_type: str = Form("document"),
    recognition_provider: str = Form("openai_vision"),
) -> PublicSource:
    runtime = current_settings()
    if source_type not in {"syllabus", "document", "handwriting"}:
        raise HTTPException(status_code=400, detail="Unsupported source type.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds the 20 MB demo limit.")
    suffix = Path(file.filename or "upload.pdf").suffix.lower()
    if suffix not in {".pdf", ".txt", ".md", ".tex", ".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=415, detail="Unsupported file format.")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary.write(data)
            temporary_path = Path(temporary.name)

        request_metadata: list[dict] = []
        text = ""
        page_count = 0
        recognition_method = "embedded_text"
        image_suffixes = {".png", ".jpg", ".jpeg", ".webp"}
        requires_visual_recognition = source_type == "handwriting" or suffix in image_suffixes

        if not requires_visual_recognition:
            ingestion = ingest_document(temporary_path, max_pages=runtime.max_pages)
            text = ingestion.combined_text
            page_count = len(ingestion.pages)
            visible_characters = len(re.sub(r"\s+", "", text))
            requires_visual_recognition = suffix == ".pdf" and visible_characters < 40

        if requires_visual_recognition:
            if recognition_provider == "tesseract":
                try:
                    recognition = recognize_with_tesseract(
                        temporary_path,
                        dpi=runtime.render_dpi,
                        max_pages=runtime.max_pages,
                    )
                except Exception as exc:
                    raise HTTPException(status_code=503, detail=str(exc)) from exc
            elif recognition_provider != "openai_vision":
                raise HTTPException(status_code=400, detail="Unknown recognition provider.")
            elif not runtime.api_enabled:
                raise HTTPException(
                    status_code=503,
                    detail="This file has no usable embedded text, so visual recognition requires OPENAI_API_KEY in .env.",
                )
            else:
                try:
                    recognition = RecognitionService(runtime).recognize_handwriting(temporary_path)
                except Exception as exc:
                    raise provider_error(exc) from exc
            page_text = [page.markdown for page in recognition.pages]
            text = "\n\n".join(page_text)
            page_count = len(recognition.pages)
            request_metadata = [item.model_dump() for item in recognition.requests]
            recognition_method = recognition.method

        course = _course_metadata(text) if source_type == "syllabus" else None
        source_id = str(uuid4())
        record = SourceRecord(
            id=source_id,
            filename=file.filename or temporary_path.name,
            source_type=source_type,
            page_count=page_count,
            text=text,
            preview=text[:500],
            course=course,
            request_metadata=request_metadata,
            recognition_method=recognition_method,
        )
        sources[source_id] = record
        return _public(record)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not process file: {exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@app.post("/api/chat")
def chat(request: ChatRequest) -> dict:
    runtime = current_settings()
    if not runtime.api_enabled:
        raise HTTPException(
            status_code=503,
            detail="Chat requires OPENAI_API_KEY in the backend .env.",
        )
    request_settings = replace(
        runtime,
        openai_model=request.model or runtime.openai_model,
        input_cost_per_1m=request.input_cost_per_1m,
        output_cost_per_1m=request.output_cost_per_1m,
    )
    context_parts = [
        f"SOURCE: {record.filename}\n{record.text}"
        for record in sources.values()
        if record.text
    ]
    context = "\n\n---\n\n".join(context_parts) or None
    try:
        result = RecognitionService(
            request_settings,
            skills=request.skills or load_skill_instructions(),
        ).help_student(
            request.question,
            context=context,
        )
        return result.model_dump()
    except Exception as exc:
        raise provider_error(exc) from exc
