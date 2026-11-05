"""Small deterministic vertical slice of the Tutoring Engine specification."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Protocol
from uuid import uuid4

from digital_professor.course_context import QuestionContext
from digital_professor.interaction.models import (
    SCHEMA_VERSION,
    DeliveryResult,
    LearnerState,
    StudentEvidence,
    TutoringAction,
)
from digital_professor.retrieval import GroundingOutcome


class QuestionStorePort(Protocol):
    def get(self, question_id: str) -> QuestionContext: ...


class RetrievalPort(Protocol):
    def retrieve_explanation(
        self, evidence: StudentEvidence, question: QuestionContext
    ) -> GroundingOutcome: ...


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


class InitialTutoringEngine:
    """Select a probe or grounded explanation and track pending delivery."""

    HELP_MARKERS = ("help", "explain", "stuck", "don't know", "do not know", "unsure")

    def __init__(
        self,
        question_store: QuestionStorePort,
        retrieval: RetrievalPort,
        *,
        clock: Callable[[], str] = _utc_now,
        id_factory: Callable[[str], str] = _new_id,
    ) -> None:
        self.question_store = question_store
        self.retrieval = retrieval
        self._clock = clock
        self._id_factory = id_factory
        self.received_evidence: list[StudentEvidence] = []
        self.received_delivery_results: list[DeliveryResult] = []
        self.retrieval_outcomes: list[GroundingOutcome] = []
        self._pending_actions: dict[str, TutoringAction] = {}
        self._pending_states: dict[str, LearnerState] = {}
        self.learner_states: dict[str, LearnerState] = {}

    def select_action(self, evidence: StudentEvidence) -> TutoringAction:
        if evidence.validation_status != "valid" or evidence.unresolved_ambiguities:
            raise ValueError("Tutoring Engine accepts only validated, confirmed evidence")
        question = self.question_store.get(evidence.question_id)
        if question.course_id != evidence.course_id:
            raise ValueError("StudentEvidence course_id does not match QuestionSchema")

        self.received_evidence.append(evidence)
        content = (evidence.confirmed_content or "").lower()
        wants_help = any(marker in content for marker in self.HELP_MARKERS)
        grounding_refs: tuple[str, ...] = ()
        if wants_help:
            action_type = "explain"
            goal = "Ground the next small step in the selected course materials."
            outcome = self.retrieval.retrieve_explanation(evidence, question)
            self.retrieval_outcomes.append(outcome)
            grounding_refs = outcome.grounding_refs
            if grounding_refs:
                topic = ", ".join(question.concept_names)
                reply = (
                    f"Your course material identifies {topic} as the relevant method. "
                    "What would you choose for $u$?"
                )
            else:
                reply = (
                    "I could not find supporting course material for this step. "
                    "What part would you like to examine first?"
                )
        else:
            action_type = "probe"
            goal = "Elicit the student's reasoning without judging the answer."
            reply = "Please explain how you chose your method for this step."

        learner_state_id = self._id_factory("learner-state")
        learner_state = LearnerState(
            record_id=learner_state_id,
            record_type="LearnerState",
            schema_version=SCHEMA_VERSION,
            created_at=self._clock(),
            producer="initial_tutoring_engine",
            status="pending_delivery",
            correlation_id=evidence.correlation_id,
            learner_state_id=learner_state_id,
            user_id=evidence.user_id,
            course_id=evidence.course_id,
            session_id=evidence.session_id,
            question_id=evidence.question_id,
            based_on_evidence_ids=(evidence.evidence_id,),
            demonstrated=(),
            unresolved=(MappingProxyType({"claim": "Student reasoning has not yet been established."}),),
            diagnostic_hypotheses=(),
            assistance_history_summary=MappingProxyType(
                {"visible_action_count": len(evidence.prior_assistance)}
            ),
            state_confidence=MappingProxyType(
                {"level": "low", "limitations": ("No correctness assessment in initial slice.",)}
            ),
            open_gaps=(
                MappingProxyType(
                    {
                        "target_slot": "method_reasoning",
                        "requirement": "Explain the selected method.",
                        "status": "open",
                        "evidence": (evidence.evidence_id,),
                    }
                ),
            ),
            closed_gaps=(),
            off_target_context=(),
            resolved_when="open_gaps is empty",
        )
        action_id = self._id_factory("action")
        action = TutoringAction(
            record_id=action_id,
            record_type="TutoringAction",
            schema_version=SCHEMA_VERSION,
            created_at=self._clock(),
            producer="initial_tutoring_engine",
            status="selected",
            correlation_id=evidence.correlation_id,
            action_id=action_id,
            session_id=evidence.session_id,
            question_id=evidence.question_id,
            turn_id=evidence.turn_id,
            learner_state_id=learner_state_id,
            action_type=action_type,
            pedagogical_goal=goal,
            content=MappingProxyType({"format": "text", "text": reply}),
            grounding_refs=grounding_refs,
            response_expected=MappingProxyType(
                {
                    "expected_kind": "math_with_explanation",
                    "input_modes": ("text", "handwriting_upload", "stylus_canvas"),
                }
            ),
            allowed_presentations=("text",),
            constraints=MappingProxyType({"answer_disclosure": "next_step_only"}),
        )
        self._pending_actions[action.action_id] = action
        self._pending_states[action.action_id] = learner_state
        return action

    def record_delivery(self, result: DeliveryResult) -> None:
        action = self._pending_actions.get(result.action_id)
        if action is None:
            raise LookupError(f"No pending action for delivery result {result.action_id}")
        if result.presentation_status not in {"presented", "partially_presented"}:
            raise ValueError(f"Cannot apply delivery status {result.presentation_status}")
        state = self._pending_states.pop(action.action_id)
        published = replace(state, status="current")
        self.learner_states[published.learner_state_id] = published
        self.received_delivery_results.append(result)
        del self._pending_actions[action.action_id]
