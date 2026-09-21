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


class RequestMetadata(StrictModel):
    """Observable metrics for one provider request."""

    response_id: str | None
    model: str
    elapsed_seconds: float = Field(ge=0.0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0.0)
    cost_basis: str | None = Field(
        default=None,
        description="Rates used for the estimate; absent when rates are not configured.",
    )


class RecognitionResult(RecognitionPayload):
    source_path: str
    method: str
    model: str | None
    requests: list[RequestMetadata]


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
    request: RequestMetadata


class SourceCitation(StrictModel):
    source_id: str = Field(description="Stable source identifier supplied in the context.")
    filename: str = Field(description="Exact source filename supplied in the context.")
    page_number: int | None = Field(
        ge=1,
        description="Page number when page provenance is available; otherwise null.",
    )
    basis: str = Field(description="Brief paraphrase of the source material supporting the answer.")


class TutorPayload(StrictModel):
    interpreted_question: str = Field(
        description="A concise restatement of what the student appears to be asking."
    )
    detected_equations: list[str] = Field(
        description="Equations found in the request, normalized as LaTeX without delimiters."
    )
    answer_markdown: str = Field(
        description="A worked teaching response with mathematical steps in LaTeX."
    )
    assumptions: list[str] = Field(
        description="Assumptions made because the request or notation was underspecified."
    )
    comprehension_check: str = Field(
        description="One short question that checks whether the student follows."
    )
    citations: list[SourceCitation] = Field(
        description="Sources used in the answer, or an empty list when citations are disabled or no source supports the answer."
    )


class TutorResponse(TutorPayload):
    request: RequestMetadata
