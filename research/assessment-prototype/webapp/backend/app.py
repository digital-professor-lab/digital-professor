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
    MetricsStore,
    RecognitionService,
    SkillInstructions,
    ingest_document,
    load_settings,
    load_skill_instructions,
    faster_whisper_available,
    recognize_with_tesseract,
    transcribe_with_faster_whisper,
    tesseract_available,
    correction_metrics,
)


app = FastAPI(title="Digital Professor Assessment Prototype API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
sources: dict[str, "SourceRecord"] = {}
metrics = MetricsStore(PROJECT_ROOT / "research" / "assessment-prototype" / "logs" / "interaction_metrics.jsonl")
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
    expose_sources: bool


class TranscriptionResult(BaseModel):
    interaction_id: str
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
    expose_sources: bool = True
    recognition_interaction_id: str | None = None
    recognition_draft: str | None = Field(default=None, max_length=10_000)


class EvaluationFeedback(BaseModel):
    interaction_id: str
    quality_rating: int = Field(ge=1, le=5)


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
        and not re.fullmatch(r"\[PAGE \d+\]", line, re.I)
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
        expose_sources=True,
    )


@app.get("/api/evaluation/metrics")
def evaluation_metrics() -> list[dict]:
    """Return metadata-only events captured during this backend session."""
    return metrics.list()


@app.post("/api/evaluation/feedback")
def evaluation_feedback(feedback: EvaluationFeedback) -> dict:
    return metrics.record(
        {
            "event_type": "quality_feedback",
            "interaction_id": feedback.interaction_id,
            "quality_rating": feedback.quality_rating,
        }
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
    interaction_id = str(uuid4())
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
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        metrics.record(
            {
                "event_type": "recognition",
                "interaction_id": interaction_id,
                "modality": "voice",
                "provider": provider,
                "model": model,
                "elapsed_seconds": elapsed,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "estimated_cost_usd": None,
                "quality_rating": None,
                "recognition_quality_proxy": None,
                "correction_edit_distance": None,
                "correction_rate": None,
            }
        )
        return TranscriptionResult(
            interaction_id=interaction_id,
            text=text,
            provider=provider,
            model=model,
            elapsed_seconds=elapsed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
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
    upload_started = time.perf_counter()
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
        quality_proxy: float | None = None
        text = ""
        page_count = 0
        recognition_method = "embedded_text"
        image_suffixes = {".png", ".jpg", ".jpeg", ".webp"}
        requires_visual_recognition = source_type == "handwriting" or suffix in image_suffixes

        if not requires_visual_recognition:
            ingestion = ingest_document(temporary_path, max_pages=runtime.max_pages)
            text = "\n\n".join(
                f"[PAGE {page.page_number}]\n{page.text}"
                for page in ingestion.pages
                if page.text
            )
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
            page_text = [f"[PAGE {page.page_number}]\n{page.markdown}" for page in recognition.pages]
            text = "\n\n".join(page_text)
            page_count = len(recognition.pages)
            request_metadata = [item.model_dump() for item in recognition.requests]
            recognition_method = recognition.method
            confidences = [
                equation.confidence
                for page in recognition.pages
                for equation in page.equations
            ]
            quality_proxy = sum(confidences) / len(confidences) if confidences else None

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
        costs = [item.get("estimated_cost_usd") for item in request_metadata]
        known_costs = [cost for cost in costs if cost is not None]
        metrics.record(
            {
                "event_type": "recognition",
                "interaction_id": source_id,
                "modality": source_type,
                "provider": recognition_provider if requires_visual_recognition else "local_extraction",
                "model": request_metadata[0].get("model") if request_metadata else None,
                "recognition_method": recognition_method,
                "page_count": page_count,
                "elapsed_seconds": time.perf_counter() - upload_started,
                "input_tokens": sum(item.get("input_tokens") or 0 for item in request_metadata) or None,
                "output_tokens": sum(item.get("output_tokens") or 0 for item in request_metadata) or None,
                "total_tokens": sum(item.get("total_tokens") or 0 for item in request_metadata) or None,
                "estimated_cost_usd": sum(known_costs) if known_costs else (0.0 if recognition_method in {"embedded_text", "tesseract_local"} else None),
                "quality_rating": None,
                "recognition_quality_proxy": quality_proxy,
                "correction_edit_distance": None,
                "correction_rate": None,
            }
        )
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
        f"SOURCE_ID: {record.id}\nFILENAME: {record.filename}\nCONTENT:\n{record.text}"
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
            expose_sources=request.expose_sources,
        )
        allowed_sources = {record.id: record for record in sources.values()}
        if request.expose_sources:
            result.citations = [
                citation.model_copy(update={"filename": allowed_sources[citation.source_id].filename})
                for citation in result.citations
                if citation.source_id in allowed_sources
            ]
        else:
            result.citations = []
        correction = (
            correction_metrics(request.recognition_draft, request.question)
            if request.recognition_interaction_id and request.recognition_draft is not None
            else {"correction_edit_distance": None, "correction_rate": None}
        )
        metrics.record(
            {
                "event_type": "tutoring",
                "interaction_id": str(uuid4()),
                "recognition_interaction_id": request.recognition_interaction_id,
                "modality": "voice_to_chat" if request.recognition_interaction_id else "text_chat",
                "provider": "openai",
                "model": result.request.model,
                "elapsed_seconds": result.request.elapsed_seconds,
                "input_tokens": result.request.input_tokens,
                "output_tokens": result.request.output_tokens,
                "total_tokens": result.request.total_tokens,
                "estimated_cost_usd": result.request.estimated_cost_usd,
                "quality_rating": None,
                "recognition_quality_proxy": None,
                "sources_exposed": request.expose_sources,
                "citation_count": len(result.citations),
                **correction,
            }
        )
        return result.model_dump()
    except Exception as exc:
        raise provider_error(exc) from exc
