"""Shared contracts for notebooks, providers, and the future web backend."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EquationCandidate(StrictModel):
    latex: str = Field(description="Normalized LaTeX without display delimiters.")
    source_text: str = Field(description="What was visibly written in the source.")
    confidence: float = Field(ge=0.0, le=1.0)
    ambiguous: bool
    alternatives: list[str] = Field(description="Plausible LaTeX alternatives, or an empty list.")


class PageContent(StrictModel):
    page_number: int = Field(ge=1)
    markdown: str = Field(description="Faithful transcription with equations in LaTeX delimiters.")
    equations: list[EquationCandidate]
    uncertainties: list[str] = Field(description="Unreadable or ambiguous regions needing review.")


class RecognitionPayload(StrictModel):
    pages: list[PageContent]
    document_summary: str


class RecognitionResult(RecognitionPayload):
    source_path: str
    method: str
    model: str | None


class ExtractedPage(StrictModel):
    page_number: int
    text: str


class DocumentIngestion(StrictModel):
    source_path: str
    media_type: str
    pages: list[ExtractedPage]

    @property
    def combined_text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text)


class RenderedPage(StrictModel):
    page_number: int
    image_bytes: bytes
    media_type: str = "image/png"

    def save(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.write_bytes(self.image_bytes)
        return destination


class GenerationResult(StrictModel):
    answer_markdown: str
    model: str
    response_id: str | None
