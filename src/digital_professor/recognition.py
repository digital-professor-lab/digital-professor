"""Provider-backed recognition and response generation behind a reusable service."""

from __future__ import annotations

import base64
import json
from pathlib import Path

from openai import OpenAI

from .config import Settings, load_settings
from .ingestion import ingest_document, render_document
from .prompts import (
    GENERATION_INSTRUCTIONS,
    IMAGE_RECOGNITION_PROMPT,
    RECOGNITION_INSTRUCTIONS,
    TEXT_RECOGNITION_PROMPT,
)
from .schemas import GenerationResult, PageContent, RecognitionPayload, RecognitionResult


def _data_url(data: bytes, media_type: str) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


class RecognitionService:
    """High-level API used by notebooks now and HTTP routes later."""

    def __init__(self, settings: Settings | None = None, client: OpenAI | None = None):
        self.settings = settings or load_settings()
        if client is None and not self.settings.api_enabled:
            raise RuntimeError("Set OPENAI_API_KEY in the root .env before using AI recognition.")
        self.client = client or OpenAI(api_key=self.settings.openai_api_key)

    def _structured_response(self, content: list[dict]) -> RecognitionPayload:
        schema = RecognitionPayload.model_json_schema()
        response = self.client.responses.create(
            model=self.settings.openai_model,
            instructions=RECOGNITION_INSTRUCTIONS,
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
        return RecognitionPayload.model_validate(json.loads(response.output_text))

    def recognize_embedded_text(self, path: str | Path) -> RecognitionResult:
        """Normalize extracted text and recover clearly represented equations."""
        source = Path(path)
        document = ingest_document(source, max_pages=self.settings.max_pages)
        prompt = TEXT_RECOGNITION_PROMPT.format(
            source_name=source.name,
            text=document.combined_text,
        )
        payload = self._structured_response([{"type": "input_text", "text": prompt}])
        return RecognitionResult(
            **payload.model_dump(),
            source_path=str(source.resolve()),
            method="embedded_text_plus_model",
            model=self.settings.openai_model,
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
        for page in rendered:
            prompt = IMAGE_RECOGNITION_PROMPT.format(
                page_number=page.page_number, source_name=source.name
            )
            payload = self._structured_response(
                [
                    {"type": "input_text", "text": prompt},
                    {
                        "type": "input_image",
                        "image_url": _data_url(page.image_bytes, page.media_type),
                        "detail": "high",
                    },
                ]
            )
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
        )

    def generate(self, question: str, context: str) -> GenerationResult:
        """Generate a source-grounded teaching response with rendered mathematics."""
        response = self.client.responses.create(
            model=self.settings.openai_model,
            instructions=GENERATION_INSTRUCTIONS,
            input=f"SOURCE CONTEXT:\n{context}\n\nSTUDENT QUESTION:\n{question}",
            store=False,
        )
        return GenerationResult(
            answer_markdown=response.output_text,
            model=self.settings.openai_model,
            response_id=response.id,
        )
