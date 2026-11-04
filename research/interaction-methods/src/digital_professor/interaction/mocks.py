"""Deterministic mock Tutoring Engine and Delivery implementations."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from types import MappingProxyType
from uuid import uuid4

from .models import (
    SCHEMA_VERSION,
    DeliveryResult,
    StudentEvidence,
    TutoringAction,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


class MockTutoringEngine:
    """Returns a neutral probe without judging whether the work is correct."""

    def __init__(
        self,
        *,
        clock: Callable[[], str] = _utc_now,
        id_factory: Callable[[str], str] = _new_id,
    ) -> None:
        self._clock = clock
        self._id_factory = id_factory
        self.received_evidence: list[StudentEvidence] = []

    def select_action(self, evidence: StudentEvidence) -> TutoringAction:
        self.received_evidence.append(evidence)
        action_id = self._id_factory("action")
        return TutoringAction(
            record_id=action_id,
            record_type="TutoringAction",
            schema_version=SCHEMA_VERSION,
            created_at=self._clock(),
            producer="mock_tutoring_engine",
            status="selected",
            correlation_id=evidence.correlation_id,
            action_id=action_id,
            session_id=evidence.session_id,
            question_id=evidence.question_id,
            turn_id=evidence.turn_id,
            learner_state_id=self._id_factory("mock-learner-state"),
            action_type="probe",
            pedagogical_goal="Elicit the student's reasoning for the submitted work.",
            content=MappingProxyType(
                {"format": "text", "text": "Please explain how you reached this step."}
            ),
            grounding_refs=(),
            response_expected=MappingProxyType({"modalities": ("text",)}),
            allowed_presentations=("text",),
            constraints=MappingProxyType({"mock": True}),
        )


class MockDelivery:
    """Records an unchanged action as presented through chat."""

    def __init__(
        self,
        *,
        clock: Callable[[], str] = _utc_now,
        id_factory: Callable[[str], str] = _new_id,
    ) -> None:
        self._clock = clock
        self._id_factory = id_factory
        self.received_actions: list[TutoringAction] = []

    def deliver(self, action: TutoringAction) -> DeliveryResult:
        self.received_actions.append(action)
        result_id = self._id_factory("delivery")
        return DeliveryResult(
            record_id=result_id,
            record_type="DeliveryResult",
            schema_version=SCHEMA_VERSION,
            created_at=self._clock(),
            producer="mock_delivery",
            status="complete",
            correlation_id=action.correlation_id,
            delivery_result_id=result_id,
            action_id=action.action_id,
            channel="chat",
            presentation_status="presented",
            presented_content_ref=f"action://{action.action_id}/content",
            presented_at=self._clock(),
            adaptations=(),
            next_input_capabilities=("text",),
        )

