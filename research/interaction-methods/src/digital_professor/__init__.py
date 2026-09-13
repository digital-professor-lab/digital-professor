"""Reusable interaction-recognition machinery for the Digital Professor demo."""

from .config import Settings, load_settings
from .ingestion import ingest_document, render_document
from .recognition import RecognitionService
from .skills import SkillInstructions, load_skill_instructions
from .schemas import (
    DocumentIngestion,
    EquationCandidate,
    GenerationResult,
    PageContent,
    RequestMetadata,
    RecognitionResult,
    TutorPayload,
    TutorResponse,
)

__all__ = [
    "DocumentIngestion",
    "EquationCandidate",
    "GenerationResult",
    "PageContent",
    "RequestMetadata",
    "RecognitionResult",
    "RecognitionService",
    "TutorPayload",
    "TutorResponse",
    "Settings",
    "SkillInstructions",
    "ingest_document",
    "load_settings",
    "load_skill_instructions",
    "render_document",
]
