"""Shared test doubles: a question, a retrieval index, a scripted model and evidence records."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from digital_professor.interaction.models import SCHEMA_VERSION, DeliveryResult, StudentEvidence
from digital_professor.providers import GenerationResult
from digital_professor.course_context.ingestion import IngestedBlock
from digital_professor.retrieval.course_retrieval import RetrievalInfo
from digital_professor.retrieval.index import RetrievedPassage


def make_question(**changes: Any) -> SimpleNamespace:
    """The by-parts question used throughout the spec's examples."""
    fields: dict[str, Any] = dict(
        prompt="Evaluate the integral of x cos(x) dx.",
        correct_approach={"technique": "Integration by parts", "justification": "a product of x and cos x"},
        reference_answer="x sin(x) + cos(x) + C",
        prerequisite_concepts=({"name": "Product rule", "relevance": "by parts reverses it"},
                               {"name": "Antiderivative of cos x", "relevance": "needed for v"}),
        common_misconceptions=({"description": "Uses substitution on a product", "cue": "let u = x cos x",
                                "mitigation": "Ask what the derivative of the inside would have to be."},),
        learning_objectives=({"text": "Apply integration by parts to a product"},),
        answer_verification={"status": "verified", "variable": "x", "integrand": "x*cos(x)"},
        concept_ids=("int-by-parts",), concept_names=("Integration by Parts",), status="partial",
        provenance="ai_inferred",
    )
    fields.update(changes)
    return SimpleNamespace(**fields)


class FakeIndex:
    """Stands in for the course index. Records every search."""

    def __init__(self, passages: tuple = ()) -> None:
        self.passages = passages
        self.searches: list[dict[str, Any]] = []
        self.info = RetrievalInfo(mode="keyword_demo", backend="test", semantic_channel=False)

    def search(self, query: str, **context: Any) -> tuple:
        self.searches.append({"query": query, **context})
        return self.passages


class ScriptedProvider:
    """A language model that answers each role from a script.

    The role is recognized from the system prompt. ``judge`` and ``guard`` entries are dicts (sent as
    JSON) or strings; ``writer`` entries are strings. When a script runs out, its last entry repeats.
    """

    def __init__(self, *, judge: list[Any] | None = None, writer: list[str] | None = None,
                 guard: list[Any] | None = None) -> None:
        self.scripts = {"judge": list(judge or []), "writer": list(writer or ["What would you try next?"]),
                        "guard": list(guard or [{"leak": False, "reason": ""}])}
        self.calls: list[dict[str, Any]] = []

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> GenerationResult:
        role = ("judge" if system.startswith("You are the marking step") else
                "guard" if system.startswith("You check one tutor reply") else "writer")
        self.calls.append({"role": role, "system": system, "messages": messages})
        script = self.scripts[role]
        if not script:
            raise RuntimeError(f"no scripted {role} reply")
        item = script.pop(0) if len(script) > 1 else script[0]
        if isinstance(item, Exception):
            raise item
        text = item if isinstance(item, str) else json.dumps(item)
        return GenerationResult(text=text, model=f"scripted-{role}", latency_ms=5, input_tokens=100,
                                output_tokens=20, estimated_cost_usd=0.0001)

    def roles(self) -> list[str]:
        return [call["role"] for call in self.calls]


def judge_record(diagnosis: str = "UNCLEAR", *, intents: tuple[str, ...] = ("ANSWER",), confidence: str = "high",
                 explanation: str = "none", target_gap: str | None = None, gap_updates: list | None = None,
                 has_work: bool = True, final_answer: str | None = None, whats_right: str = "",
                 first_issue: str = "") -> dict[str, Any]:
    return {"intents": list(intents), "final_answer": final_answer, "has_work": has_work, "safety_signal": False,
            "diagnosis": diagnosis, "confidence": confidence, "explanation": explanation,
            "target_gap": target_gap, "gap_updates": gap_updates or [], "summary": "test",
            "whats_right": whats_right, "first_issue": first_issue}


def evidence(text: str, turn: int = 1, *, prior_action_id: str | None = None) -> StudentEvidence:
    return StudentEvidence(
        record_id=f"evidence-{turn}", record_type="StudentEvidence", schema_version=SCHEMA_VERSION,
        created_at="2026-11-15T00:00:00Z", producer="test", status="valid", correlation_id=f"corr-{turn}",
        evidence_id=f"evidence-{turn}", user_id="student-1", course_id="calc1", session_id="session-1",
        question_id="q1", turn_id=f"turn-{turn}", attempt_id="attempt-1", submission_id=f"sub-{turn}",
        evidence_kind="initial_attempt" if turn == 1 else "follow_up", original_artifact_ref=f"artifact-{turn}",
        confirmed_content=text, recognition_ref=None, correction_refs=(), observed_steps=(), final_answer=None,
        student_explanation=None, student_uncertainty=None,
        prior_assistance=(prior_action_id,) if prior_action_id else (), parent_evidence_id=None,
        validation_status="valid", validation_errors=(), requires_human_review=False, unresolved_ambiguities=())


def delivered(action_id: str, status: str = "presented") -> DeliveryResult:
    fields = {name: None for name in DeliveryResult.__dataclass_fields__}
    fields.update(record_id=f"delivery-{action_id}", record_type="DeliveryResult", schema_version=SCHEMA_VERSION,
                  created_at="2026-11-15T00:00:01Z", producer="test", status="completed", action_id=action_id,
                  presentation_status=status)
    return DeliveryResult(**fields)


class Conversation:
    """Runs turns through an engine the way the coordinator does: select, deliver, link to the last action."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self.turn = 0
        self.last_action_id: str | None = None

    def say(self, text: str, *, deliver: bool = True) -> Any:
        self.turn += 1
        action = self.engine.select_action(evidence(text, self.turn, prior_action_id=self.last_action_id))
        if deliver:
            self.engine.record_delivery(delivered(action.action_id))
            self.last_action_id = action.action_id
        return action


def passage(text: str, *, page: int = 152, block_type: str = "theorem", label: str | None = None,
            heading: str | None = None) -> RetrievedPassage:
    block = IngestedBlock(
        block_id=f"block-{page}-{abs(hash(text)) % 9999}", document_id="doc-1", filename="textbook.pdf",
        document_type="textbook", content_version="v1", chapter_id=None, section_id=None, block_type=block_type,
        concept_ids=(), concept_source="none", visibility="student_visible", page_number=page, page_end=page,
        line_start=1, line_end=9, heading=heading, label=label, text=text, provenance="source_document")
    return RetrievedPassage(block, 1.0, f"/highlight/{page}")
