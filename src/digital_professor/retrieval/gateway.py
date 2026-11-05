"""Adapter from product contracts to Retrieval V1.

Retrieval searches and validates course evidence. It does not diagnose the
student or select the tutoring action, following ``specs/rag-retrieval.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from digital_professor.course_context import QuestionContext
from digital_professor.interaction.models import StudentEvidence


@dataclass(frozen=True, slots=True)
class GroundingOutcome:
    status: str
    grounding_refs: tuple[str, ...]
    record: Mapping[str, Any]


class FixtureRetrievalGateway:
    """Use Retrieval V1's dependency-free fixture backend for integration."""

    def __init__(self) -> None:
        try:
            from retrieval_tool import build_service
        except ImportError as error:
            raise RuntimeError(
                "retrieval_tool is unavailable; install the Retrieval V1 package"
            ) from error
        self._service = build_service("fixture")

    def retrieve_explanation(
        self, evidence: StudentEvidence, question: QuestionContext
    ) -> GroundingOutcome:
        from retrieval_tool import TurnContext, recommend_grounding
        from retrieval_tool.tool_schema import build_structured_request

        policy = self._service.policies[question.course_id]
        context = TurnContext(
            course_id=question.course_id,
            session_id=evidence.session_id,
            turn_id=evidence.turn_id,
            question_id=question.question_id,
            correlation_id=evidence.correlation_id,
            action_type="explain",
            retrieval_snapshot_id=policy.retrieval_snapshot_id,
            concept_ids=list(question.concept_ids),
            concept_names=list(question.concept_names),
            question_prompt=question.prompt,
            student_message=evidence.confirmed_content,
            intent_summary=", ".join(question.concept_names),
            evidence_summary=(evidence.confirmed_content or "")[:500],
            bank_sibling_question_ids=list(question.sibling_question_ids),
            course_title=question.course_title,
        )
        decision = recommend_grounding("explain")
        request = build_structured_request(context, decision)
        record = self._service.handle(request)
        passages = record.get("passages") or []
        return GroundingOutcome(
            status=record.get("retrieval_status") or record.get("stop_reason", "failed"),
            grounding_refs=tuple(passage["passage_id"] for passage in passages[:1]),
            record=MappingProxyType(record),
        )
