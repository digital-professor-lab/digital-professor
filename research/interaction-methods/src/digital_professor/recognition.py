"""Provider-backed recognition and response generation behind a reusable service."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

from openai import OpenAI

from .config import Settings, load_settings
from .ingestion import ingest_document, render_document
from .prompts import IMAGE_RECOGNITION_PROMPT, RECOGNITION_INSTRUCTIONS, TEXT_RECOGNITION_PROMPT, TUTOR_PROMPT
from .skills import SkillInstructions, load_skill_instructions
from .schemas import (
    GenerationResult,
    PageContent,
    RecognitionPayload,
    RecognitionResult,
    RequestMetadata,
    TutorPayload,
    TutorResponse,
)


def _data_url(data: bytes, media_type: str) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


class RecognitionService:
    """High-level API used by notebooks now and HTTP routes later."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: OpenAI | None = None,
        skills: SkillInstructions | None = None,
    ):
        self.settings = settings or load_settings()
        self.skills = skills or load_skill_instructions()
        if client is None and not self.settings.api_enabled:
            raise RuntimeError("Set OPENAI_API_KEY in the root .env before using AI recognition.")
        self.client = client or OpenAI(api_key=self.settings.openai_api_key)

    def _request_metadata(self, response: object, elapsed_seconds: float) -> RequestMetadata:
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", None) if usage else None
        output_tokens = getattr(usage, "output_tokens", None) if usage else None
        total_tokens = getattr(usage, "total_tokens", None) if usage else None

        estimated_cost = None
        cost_basis = None
        if (
            input_tokens is not None
            and output_tokens is not None
            and self.settings.input_cost_per_1m is not None
            and self.settings.output_cost_per_1m is not None
        ):
            estimated_cost = (
                input_tokens * self.settings.input_cost_per_1m
                + output_tokens * self.settings.output_cost_per_1m
            ) / 1_000_000
            cost_basis = (
                f"${self.settings.input_cost_per_1m:g}/1M input tokens + "
                f"${self.settings.output_cost_per_1m:g}/1M output tokens"
            )

        return RequestMetadata(
            response_id=getattr(response, "id", None),
            model=getattr(response, "model", self.settings.openai_model),
            elapsed_seconds=elapsed_seconds,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost,
            cost_basis=cost_basis,
        )

    def _structured_response(
        self, content: list[dict]
    ) -> tuple[RecognitionPayload, RequestMetadata]:
        schema = RecognitionPayload.model_json_schema()
        started_at = time.perf_counter()
        response = self.client.responses.create(
            model=self.settings.openai_model,
            instructions=f"{RECOGNITION_INSTRUCTIONS}\n\n{self.skills.review_instructions}",
            input=[{"role": "user", "content": content}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "document_recognition",
                    "strict": True,
                    "schema": schema,
                }
            },
            store=False,
        )
        elapsed_seconds = time.perf_counter() - started_at
        payload = RecognitionPayload.model_validate(json.loads(response.output_text))
        return payload, self._request_metadata(response, elapsed_seconds)

    def recognize_embedded_text(self, path: str | Path) -> RecognitionResult:
        """Normalize extracted text and recover clearly represented equations."""
        source = Path(path)
        document = ingest_document(source, max_pages=self.settings.max_pages)
        prompt = TEXT_RECOGNITION_PROMPT.format(
            source_name=source.name,
            text=document.combined_text,
        )
        payload, metadata = self._structured_response(
            [{"type": "input_text", "text": prompt}]
        )
        return RecognitionResult(
            **payload.model_dump(),
            source_path=str(source.resolve()),
            method="embedded_text_plus_model",
            model=self.settings.openai_model,
            requests=[metadata],
        )

    def recognize_handwriting(
        self, path: str | Path, *, pages: list[int] | None = None
    ) -> RecognitionResult:
        """Render and transcribe handwriting one page at a time to retain page provenance."""
        source = Path(path)
        rendered = render_document(
            source,
            dpi=self.settings.render_dpi,
            pages=pages,
            max_pages=self.settings.max_pages,
        )
        recognized_pages: list[PageContent] = []
        summaries: list[str] = []
        request_metadata: list[RequestMetadata] = []
        for page in rendered:
            prompt = IMAGE_RECOGNITION_PROMPT.format(
                page_number=page.page_number, source_name=source.name
            )
            payload, metadata = self._structured_response(
                [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "image_url": _data_url(page.image_bytes, page.media_type),
                        "detail": "high",
                    },
                ]
            )
            request_metadata.append(metadata)
            for recognized_page in payload.pages:
                recognized_page.page_number = page.page_number
                recognized_pages.append(recognized_page)
            summaries.append(payload.document_summary)
        return RecognitionResult(
            pages=recognized_pages,
            document_summary=" ".join(summaries),
            source_path=str(source.resolve()),
            method="rendered_page_vision",
            model=self.settings.openai_model,
            requests=request_metadata,
        )

    def generate(self, question: str, context: str) -> GenerationResult:
        """Generate a source-grounded teaching response with rendered mathematics."""
        started_at = time.perf_counter()
        response = self.client.responses.create(
            model=self.settings.openai_model,
            instructions=self.skills.tutor_prompt(),
            input=f"SOURCE CONTEXT:\n{context}\n\nSTUDENT QUESTION:\n{question}",
            store=False,
        )
        elapsed_seconds = time.perf_counter() - started_at
        return GenerationResult(
            answer_markdown=response.output_text,
            model=self.settings.openai_model,
            response_id=response.id,
            request=self._request_metadata(response, elapsed_seconds),
        )

    def help_student(self, question: str, context: str | None = None) -> TutorResponse:
        """Reason about a student question or equation and return a teaching response."""
        if not question.strip():
            raise ValueError("The student question or equation cannot be empty.")

        prompt = TUTOR_PROMPT.format(
            question=question.strip(),
            context=(context or "No course-specific context was supplied.").strip(),
        )
        started_at = time.perf_counter()
        response = self.client.responses.create(
            model=self.settings.openai_model,
            instructions=self.skills.tutor_prompt(),
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "tutor_response",
                    "strict": True,
                    "schema": TutorPayload.model_json_schema(),
                }
            },
            store=False,
        )
        elapsed_seconds = time.perf_counter() - started_at
        payload = TutorPayload.model_validate_json(response.output_text)
        return TutorResponse(
            **payload.model_dump(),
            request=self._request_metadata(response, elapsed_seconds),
        )
