"""Provider adapters for faithful handwriting recognition."""

from __future__ import annotations

import base64
import json
import os
import time

import pymupdf
from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from .models import RecognizerOutput


SUPPORTED_MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp", "application/pdf"}


class RecognitionConfigurationError(RuntimeError):
    """Raised when a configured recognition provider cannot be initialized."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Step(_StrictModel):
    page_number: int = Field(ge=1)
    region: str
    content: str
    crossed_out: bool


class _Alternative(_StrictModel):
    page_number: int = Field(ge=1)
    region: str
    value: str
    confidence: float | None = Field(ge=0, le=1)


class _Ambiguity(_StrictModel):
    page_number: int = Field(ge=1)
    region: str
    raw_value: str
    candidates: list[str]
    confidence: float | None = Field(ge=0, le=1)
    meaning_may_change: bool
    description: str


class _RecognitionPayload(_StrictModel):
    transcription_markdown: str
    steps: list[_Step]
    alternatives: list[_Alternative]
    ambiguities: list[_Ambiguity]
    incomplete: bool


def _data_url(data: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"


def _render_pages(data: bytes, media_type: str, max_pages: int) -> tuple[list[tuple[int, bytes, str]], int]:
    if media_type != "application/pdf":
        return [(1, data, media_type)], 1
    rendered: list[tuple[int, bytes, str]] = []
    with pymupdf.open(stream=data, filetype="pdf") as document:
        page_count = len(document)
        for index in range(min(page_count, max_pages)):
            image = document[index].get_pixmap(dpi=180, alpha=False).tobytes("png")
            rendered.append((index + 1, image, "image/png"))
    if not rendered:
        raise ValueError("The uploaded PDF contains no pages.")
    return rendered, page_count


class OpenAIHandwritingRecognizer:
    """OpenAI vision adapter that reports uncertainty without repairing math."""

    def __init__(
        self,
        *,
        model: str | None = None,
        client: OpenAI | None = None,
        max_pages: int = 5,
    ) -> None:
        self.model = model or os.getenv("OPENAI_HANDWRITING_MODEL", "gpt-4o-mini")
        if client is None and not os.getenv("OPENAI_API_KEY"):
            raise RecognitionConfigurationError(
                "OPENAI_API_KEY is not configured for handwriting recognition."
            )
        self.client = client or OpenAI()
        self.max_pages = max_pages

    def recognize(self, *, filename: str, media_type: str, data: bytes) -> RecognizerOutput:
        if media_type not in SUPPORTED_MEDIA_TYPES:
            raise ValueError(f"Unsupported handwriting media type: {media_type}")
        pages, page_count = _render_pages(data, media_type, self.max_pages)
        content: list[dict[str, object]] = [{
            "type": "input_text",
            "text": (
                f"Faithfully transcribe the student's work from {filename}. Preserve line order, "
                "visible mistakes, notation, and crossed-out work. Use Markdown with LaTeX. Do not "
                "solve, grade, simplify, or silently correct anything. Return ordered steps with page "
                "and visible region labels. Flag uncertain signs, operators, digits, variables, "
                "exponents, subscripts, inequalities, grouping marks, and missing lines. Mark whether "
                "each ambiguity could change mathematical meaning."
            ),
        }]
        for page_number, image, image_type in pages:
            content.extend((
                {"type": "input_text", "text": f"Page {page_number}"},
                {"type": "input_image", "image_url": _data_url(image, image_type), "detail": "high"},
            ))

        started = time.perf_counter()
        response = self.client.responses.create(
            model=self.model,
            input=[{"role": "user", "content": content}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "handwriting_recognition",
                    "strict": True,
                    "schema": _RecognitionPayload.model_json_schema(),
                }
            },
            store=False,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        payload = _RecognitionPayload.model_validate(json.loads(response.output_text))
        meaning_ambiguity = any(item.meaning_may_change for item in payload.ambiguities)
        incomplete = payload.incomplete or len(pages) < page_count
        status = "partial" if incomplete else "confirmation_required" if meaning_ambiguity else "recognized"
        return RecognizerOutput(
            provider="openai",
            model_version=getattr(response, "model", self.model),
            recognized_content=payload.transcription_markdown,
            content_format="markdown_tex",
            alternatives=tuple(item.model_dump() for item in payload.alternatives),
            ambiguities=tuple(item.model_dump() for item in payload.ambiguities),
            observed_steps=tuple(item.model_dump() for item in payload.steps),
            page_count=page_count,
            processed_pages=tuple(page_number for page_number, _, _ in pages),
            recognition_status=status,
            latency_ms=elapsed_ms,
            raw_provider_output=response.output_text,
        )


class StubHandwritingRecognizer:
    """Deterministic adapter used by contract tests without a model call."""

    def __init__(self, output: RecognizerOutput) -> None:
        self.output = output
        self.calls: list[dict[str, object]] = []

    def recognize(self, *, filename: str, media_type: str, data: bytes) -> RecognizerOutput:
        self.calls.append({"filename": filename, "media_type": media_type, "data": data})
        return self.output
