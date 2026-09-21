"""Model fallback for source layouts that deterministic parsing cannot resolve."""

from __future__ import annotations

import time
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from .course_parsing import CourseDetails


class ModelTopic(BaseModel):
    title: str
    level: int
    section_number: str | None = None
    page_number: int | None = None


class SourceAnalysis(BaseModel):
    document_type: Literal["syllabus", "lecture_notes", "textbook", "document", "handwriting"]
    course: CourseDetails
    topics: list[ModelTopic] = Field(default_factory=list)
    textbook_name: str | None = None


def analyze_source_text(
    text: str,
    *,
    api_key: str,
    model: str,
    client: OpenAI | None = None,
) -> tuple[SourceAnalysis, dict]:
    """Classify and extract only facts supported by uploaded text."""
    started = time.perf_counter()
    response = (client or OpenAI(api_key=api_key)).responses.parse(
        model=model,
        store=False,
        input=[
            {
                "role": "system",
                "content": (
                    "Classify this academic source by its CONTENT, not its filename. "
                    "For a syllabus, extract the course name, course number, semester, "
                    "and an overview paragraph. For lecture notes, extract a detailed "
                    "hierarchical list of topics and page numbers when explicit. "
                    "For a textbook, extract the book's title as textbook_name. "
                    "Use only evidence present in the source. Return null for missing "
                    "syllabus fields and an empty list when topics are not identifiable. "
                    "Do not invent a title, term, overview, or topic. "
                    "Normalize course number and semester to lowercase; retain the "
                    "source capitalization in the course name and overview."
                ),
            },
            {"role": "user", "content": text[:50000]},
        ],
        text_format=SourceAnalysis,
    )
    if response.output_parsed is None:
        raise ValueError("The model returned no structured source analysis.")
    usage = response.usage
    metadata = {
        "model": model,
        "elapsed_seconds": time.perf_counter() - started,
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
        "estimated_cost_usd": None,
    }
    return response.output_parsed, metadata
