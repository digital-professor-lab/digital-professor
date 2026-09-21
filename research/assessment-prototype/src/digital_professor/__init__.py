"""Reusable interaction-recognition machinery for the Digital Professor demo."""

from .config import Settings, load_settings
from .baseline import recognize_with_tesseract, tesseract_available
from .transcription import faster_whisper_available, transcribe_with_faster_whisper
from .telemetry import MetricsStore, correction_metrics
from .course_parsing import CourseDetails, TopicEntry, classify_document, extract_course_details, extract_textbook_name, extract_topics
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
    SourceCitation,
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
    "SourceCitation",
    "TutorPayload",
    "TutorResponse",
    "Settings",
    "SkillInstructions",
    "ingest_document",
    "load_settings",
    "load_skill_instructions",
    "render_document",
    "recognize_with_tesseract",
    "tesseract_available",
    "faster_whisper_available",
    "transcribe_with_faster_whisper",
    "MetricsStore",
    "correction_metrics",
    "CourseDetails",
    "TopicEntry",
    "classify_document",
    "extract_course_details",
    "extract_textbook_name",
    "extract_topics",
]
