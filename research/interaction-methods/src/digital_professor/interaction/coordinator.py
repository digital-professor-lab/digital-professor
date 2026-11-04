"""Coordination of one typed tutoring turn across replaceable module ports."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

from .models import (
    InteractionTraceEvent,
    StudentEvidence,
    StudentSubmission,
    TutoringTurnFailure,
    TutoringTurnResult,
    TypedSubmissionInput,
)
from .pipeline import StudentEvidencePipeline
from .ports import DeliveryPort, TutoringEnginePort


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


class TutoringTurnCoordinator:
    """Route validated evidence through Engine and Delivery for one turn."""

    def __init__(
        self,
        pipeline: StudentEvidencePipeline,
        tutoring_engine: TutoringEnginePort,
        delivery: DeliveryPort,
        *,
        id_factory: Callable[[str], str] = _new_id,
    ) -> None:
        self.pipeline = pipeline
        self.tutoring_engine = tutoring_engine
        self.delivery = delivery
        self._id_factory = id_factory

    def run_typed_turn(
        self, request: TypedSubmissionInput
    ) -> TutoringTurnResult | TutoringTurnFailure:
        """Complete one validated typed-input tutoring turn."""

        correlation_id = self._id_factory("correlation")
        submission = self.pipeline.capture_typed_submission(
            request, correlation_id=correlation_id
        )
        submission_event = self._event(
            request,
            correlation_id,
            "submission",
            (submission.record_id,),
        )

        evidence = self.pipeline.build_student_evidence(submission, request)
        evidence_event = self._event(
            request,
            correlation_id,
            "evidence_validated",
            (submission.record_id, evidence.record_id),
        )

        return self.route_validated_evidence(
            submission,
            evidence,
            prior_events=(submission_event, evidence_event),
        )

    def route_validated_evidence(
        self,
        submission: StudentSubmission,
        evidence: StudentEvidence,
        *,
        prior_events: tuple[InteractionTraceEvent, ...] = (),
    ) -> TutoringTurnResult | TutoringTurnFailure:
        """Route modality-independent, validated evidence downstream."""

        correlation_id = evidence.correlation_id

        # Only validated evidence reaches the Tutoring Engine port.
        try:
            action = self.tutoring_engine.select_action(evidence)
        except Exception:
            failure_event = self._record_event(
                evidence.session_id,
                evidence.turn_id,
                correlation_id,
                "failure",
                (evidence.record_id,),
            )
            return TutoringTurnFailure(
                correlation_id=correlation_id,
                failed_stage="tutoring_engine",
                error_code="engine_handoff_failed",
                message="Tutoring Engine handoff failed.",
                submission=submission,
                evidence=evidence,
                action=None,
                trace_events=(*prior_events, failure_event),
            )
        action_event = self._record_event(
            evidence.session_id,
            evidence.turn_id,
            correlation_id,
            "action_selected",
            (evidence.record_id, action.record_id),
        )

        # Interaction forwards the exact action object without changing its
        # pedagogical goal or mathematical content.
        try:
            delivery_result = self.delivery.deliver(action)
        except Exception:
            failure_event = self._record_event(
                evidence.session_id,
                evidence.turn_id,
                correlation_id,
                "failure",
                (action.record_id,),
            )
            return TutoringTurnFailure(
                correlation_id=correlation_id,
                failed_stage="delivery",
                error_code="delivery_handoff_failed",
                message="Delivery handoff failed.",
                submission=submission,
                evidence=evidence,
                action=action,
                trace_events=(*prior_events, action_event, failure_event),
            )
        delivery_event = self._record_event(
            evidence.session_id,
            evidence.turn_id,
            correlation_id,
            "delivery",
            (action.record_id, delivery_result.record_id),
        )

        return TutoringTurnResult(
            submission=submission,
            evidence=evidence,
            action=action,
            delivery=delivery_result,
            trace_events=(*prior_events, action_event, delivery_event),
        )

    def _event(
        self,
        request: TypedSubmissionInput,
        correlation_id: str,
        event_type: str,
        record_refs: tuple[str, ...],
    ) -> InteractionTraceEvent:
        return self._record_event(
            request.session_id,
            request.turn_id,
            correlation_id,
            event_type,
            record_refs,
        )

    def _record_event(
        self,
        session_id: str,
        turn_id: str,
        correlation_id: str,
        event_type: str,
        record_refs: tuple[str, ...],
    ) -> InteractionTraceEvent:
        return InteractionTraceEvent(
            event_id=self._id_factory("event"),
            session_id=session_id,
            turn_id=turn_id,
            correlation_id=correlation_id,
            event_type=event_type,
            record_refs=record_refs,
        )

