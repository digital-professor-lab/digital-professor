"""Student Interaction and Evidence V1 typed-input pipeline."""

from .coordinator import TutoringTurnCoordinator
from .handwriting import (
    ConfirmedHandwritingTurn,
    HandwritingEvidenceService,
    HandwritingLoggingConfiguration,
    HandwritingRecognitionFailure,
    HandwritingReview,
)
from .mocks import MockDelivery, MockTutoringEngine
from .models import (
    DeliveryResult,
    HandwritingSubmissionInput,
    InteractionTraceEvent,
    RecognitionCorrection,
    RecognitionResult,
    RecognizerOutput,
    StudentEvidence,
    StudentSubmission,
    TutoringAction,
    TutoringTurnFailure,
    TutoringTurnResult,
    TypedSubmissionInput,
)
from .pipeline import RecordValidationError, StudentEvidencePipeline
from .recognition import (
    OpenAIHandwritingRecognizer,
    RecognitionConfigurationError,
    StubHandwritingRecognizer,
)
from .storage import InMemoryArtifactStore

__all__ = [
    "DeliveryResult",
    "ConfirmedHandwritingTurn",
    "HandwritingEvidenceService",
    "HandwritingLoggingConfiguration",
    "HandwritingRecognitionFailure",
    "HandwritingReview",
    "HandwritingSubmissionInput",
    "InMemoryArtifactStore",
    "InteractionTraceEvent",
    "MockDelivery",
    "MockTutoringEngine",
    "RecordValidationError",
    "RecognitionCorrection",
    "RecognitionConfigurationError",
    "RecognitionResult",
    "RecognizerOutput",
    "OpenAIHandwritingRecognizer",
    "StudentEvidence",
    "StudentEvidencePipeline",
    "StubHandwritingRecognizer",
    "StudentSubmission",
    "TutoringAction",
    "TutoringTurnCoordinator",
    "TutoringTurnFailure",
    "TutoringTurnResult",
    "TypedSubmissionInput",
]
