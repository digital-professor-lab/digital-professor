"""Replaceable downstream interfaces used by Interaction coordination."""

from __future__ import annotations

from typing import Protocol

from .models import DeliveryResult, StudentEvidence, TutoringAction


class TutoringEnginePort(Protocol):
    """Minimum engine interface required by the first typed turn."""

    def select_action(self, evidence: StudentEvidence) -> TutoringAction:
        """Interpret evidence and return one structured tutoring action."""


class DeliveryPort(Protocol):
    """Minimum delivery interface required by the first typed turn."""

    def deliver(self, action: TutoringAction) -> DeliveryResult:
        """Present an action without changing its pedagogical meaning."""

