"""Reusable interaction-recognition machinery for the Digital Professor demo."""

from .config import Settings, load_settings
from .ingestion import ingest_document, render_document
from .recognition import RecognitionService
from .schemas import (
    DocumentIngestion,
    EquationCandidate,
    GenerationResult,
    PageContent,
    RecognitionResult,
)

__all__ = [
    "DocumentIngestion",
    "EquationCandidate",
    "GenerationResult",
    "PageContent",
    "RecognitionResult",
    "RecognitionService",
    "Settings",
    "ingest_document",
    "load_settings",
    "render_document",
]
