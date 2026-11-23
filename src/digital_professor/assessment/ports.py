"""Replaceable boundaries owned by other Digital Professor modules."""

from __future__ import annotations

from typing import Protocol

from digital_professor.interaction.models import TutoringAction

from .models import AssessmentEngineHandoff


class AssessmentTutoringEnginePort(Protocol):
    """Allow assessment evidence to inform the Engine without selecting pedagogy."""

    def record_assessment_result(
        self, handoff: AssessmentEngineHandoff
    ) -> TutoringAction | None:
        """Update learner state and optionally select the next tutoring action."""

