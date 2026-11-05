"""The retrieval tool as the tutoring model sees it, and how a tool call becomes a RetrievalRequest.

Split of responsibilities (rag-retrieval.md §6.4):

* The **model** fills only what it can judge from the conversation: what to look for (`query`),
  why (`purpose`) and which kinds of evidence (`evidence_needs`).
* The **system** injects everything the model must not choose: course, question, turn, session,
  pinned snapshot, Course Context version, concept filters, answer-leak exclusions and budgets.
  A model therefore cannot search the wrong course or version, however it phrases the call.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from .records import NEED_TYPES, envelope, new_id

TOOL_NAME = "search_course_materials"

# Purposes a tutoring turn may use. `approach_grounding` is builder-only (§7.10) and
# `citation_check` is issued by the system, not the model.
MODEL_PURPOSES = ("answer_grounding", "diagnosis_support", "hint_support", "definition_lookup",
                  "example_lookup", "prerequisite_review", "practice_generation")

TOOL_DESCRIPTION = (
    "Search this course's approved materials (lecture notes, textbook, worked examples) and return "
    "exact passages with stable IDs and page/line locations.\n"
    "USE it before you state anything course-specific: a definition, formula, theorem, method, "
    "notation convention, or an example the student should study.\n"
    "DO NOT use it for: confirming what the student wrote, asking for missing work, checking whether "
    "an answer is mathematically correct, encouragement, or turn management.\n"
    "Write `query` in neutral course terms (e.g. 'chain rule for composite functions'), not the "
    "student's own words. Split what you need into 1-4 `evidence_needs`, one per kind of evidence.\n"
    "The result has a `retrieval_status`: supported, partial, no_support_found, or failed. Cite only "
    "passages that are returned, using their labels like [P1]. If the status is no_support_found or "
    "failed, say that the course materials do not cover this point instead of inventing a citation."
)

TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query", "purpose", "evidence_needs"],
    "properties": {
        "query": {
            "type": "string", "minLength": 3, "maxLength": 300,
            "description": "What to look for, in course terms. Not the student's raw message.",
        },
        "purpose": {
            "type": "string", "enum": list(MODEL_PURPOSES),
            "description": "Why you need the material in this turn.",
        },
        "evidence_needs": {
            "type": "array", "minItems": 1, "maxItems": 4,
            "description": "The distinct pieces of evidence you need; one entry per kind.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["need_type", "description"],
                "properties": {
                    "need_type": {"type": "string", "enum": list(NEED_TYPES)},
                    "description": {"type": "string", "maxLength": 200,
                                    "description": "What this piece of evidence must state."},
                    "anchor": {"type": "string", "maxLength": 80,
                               "description": "Optional exact term or formula that must appear, "
                                              "e.g. 'chain rule' or \"f'(g(x))g'(x)\"."},
                },
            },
        },
        "contains_student_wording": {
            "type": "boolean",
            "description": "True if `query` copies the student's own words.",
        },
        "concept_id": {
            "type": "string",
            "description": "The ONE course concept this turn is mainly about, from the course concept list in the "
                           "instructions. Choose \"not_in_course\" when the student asks about something this course "
                           "does not teach (do not pick the nearest concept). Omit if you cannot tell.",
        },
        "related_concept_ids": {
            "type": "array", "maxItems": 2, "items": {"type": "string"},
            "description": "Optional other concepts from the list that the reply will also need (e.g. the chain rule "
                           "inside an implicit-differentiation question). Recorded for later scope widening; they do "
                           "not decide which passages count as support. Usually empty.",
        },
    },
}

NOT_IN_COURSE = "not_in_course"


def openai_tool() -> dict[str, Any]:
    """OpenAI-compatible function tool (also accepted by DeepSeek and Gemini's OpenAI endpoint)."""
    return {"type": "function",
            "function": {"name": TOOL_NAME, "description": TOOL_DESCRIPTION,
                         "parameters": copy.deepcopy(TOOL_PARAMETERS)}}


def anthropic_tool() -> dict[str, Any]:
    return {"name": TOOL_NAME, "description": TOOL_DESCRIPTION,
            "input_schema": copy.deepcopy(TOOL_PARAMETERS)}


@dataclass
class TurnContext:
    """What the system already knows about this turn. Filled by the coordinator / Engine, not the model."""

    course_id: str
    session_id: str
    turn_id: str
    question_id: str
    correlation_id: str
    action_type: str
    retrieval_snapshot_id: str | None = None
    course_context_ref: dict[str, str] | None = None
    concept_ids: list[str] = field(default_factory=list)
    concept_names: list[str] = field(default_factory=list)
    question_prompt: str | None = None          # display-safe prompt only
    student_message: str | None = None          # latest confirmed student text (for overlap detection)
    intent_summary: str | None = None           # upstream understanding of what the student needs
    evidence_summary: str | None = None         # minimal context for retrieval (≤ 500 chars)
    bank_sibling_question_ids: list[str] = field(default_factory=list)
    course_title: str | None = None              # e.g. "Calculus I" (Course.title from Course Context)


class ToolArgumentError(ValueError):
    def __init__(self, errors: list[dict[str, str]]):
        super().__init__("; ".join(e["message"] for e in errors))
        self.errors = errors


def validate_tool_arguments(args: Any) -> list[dict[str, str]]:
    """Light JSON-schema check of the model's arguments; returns field/code/message errors."""
    errors: list[dict[str, str]] = []

    def err(field_name: str, code: str, message: str) -> None:
        errors.append({"field": field_name, "code": code, "message": message})

    if not isinstance(args, dict):
        err("$", "type", "arguments must be an object")
        return errors
    for key in args:
        if key not in TOOL_PARAMETERS["properties"]:
            err(key, "unknown_field", f"unknown argument '{key}' (course, question and version are set by the system)")
    query = args.get("query")
    if not isinstance(query, str) or not 3 <= len(query.strip()) <= 300:
        err("query", "invalid", "query must be a string of 3-300 characters")
    if args.get("purpose") not in MODEL_PURPOSES:
        err("purpose", "invalid_enum", f"purpose must be one of {', '.join(MODEL_PURPOSES)}")
    needs = args.get("evidence_needs")
    if not isinstance(needs, list) or not 1 <= len(needs) <= 4:
        err("evidence_needs", "invalid", "evidence_needs must list 1-4 needs")
    else:
        for i, need in enumerate(needs):
            if not isinstance(need, dict) or need.get("need_type") not in NEED_TYPES:
                err(f"evidence_needs[{i}].need_type", "invalid_enum", f"need_type must be one of {', '.join(NEED_TYPES)}")
            elif not isinstance(need.get("description"), str) or not need["description"].strip():
                err(f"evidence_needs[{i}].description", "missing", "each need needs a description")
    if "contains_student_wording" in args and not isinstance(args["contains_student_wording"], bool):
        err("contains_student_wording", "type", "must be a boolean")
    return errors


def _copies_student_text(query: str, student_message: str | None, min_words: int = 6) -> bool:
    """Detect a verbatim run of ≥ min_words student words inside the query (forces the free-text scope check)."""
    if not student_message:
        return False
    words = re.findall(r"\w+", student_message.lower())
    query_text = " ".join(re.findall(r"\w+", query.lower()))
    return any(" ".join(words[i:i + min_words]) in query_text for i in range(len(words) - min_words + 1))


def build_request(args: dict[str, Any], ctx: TurnContext, *, top_k: int | None = None,
                  producer: str = "tutoring-engine") -> dict[str, Any]:
    """Model arguments + system-owned context → canonical RetrievalRequest (interfaces.md §8 + V1 additions)."""
    errors = validate_tool_arguments(args)
    if errors:
        raise ToolArgumentError(errors)
    request_id = new_id("rr")
    needs = []
    for i, need in enumerate(args["evidence_needs"], start=1):
        item = {"need_id": f"n{i}", "need_type": need["need_type"], "description": need["description"].strip()}
        if need.get("anchor"):
            item["anchor"] = need["anchor"].strip()
        if ctx.concept_ids:
            item["concept_ids"] = list(ctx.concept_ids)
        needs.append(item)
    student_text = bool(args.get("contains_student_wording")) or _copies_student_text(args["query"], ctx.student_message)
    request: dict[str, Any] = {
        **envelope("RetrievalRequest", record_id=request_id, correlation_id=ctx.correlation_id,
                   status="valid", producer=producer),
        "retrieval_request_id": request_id,
        "course_id": ctx.course_id,
        "question_id": ctx.question_id,
        "turn_id": ctx.turn_id,
        "session_id": ctx.session_id,
        "query": " ".join(args["query"].split()),
        "query_origin": "student_text" if student_text else "structured",
        "purpose": args["purpose"],
        "evidence_needs": needs,
        "concept_ids": list(ctx.concept_ids),
        "query_language": "en",
    }
    if top_k is not None:  # otherwise the course policy default applies (Week 3: 6)
        request["top_k"] = top_k
    if ctx.retrieval_snapshot_id:
        request["retrieval_snapshot_id"] = ctx.retrieval_snapshot_id
    if ctx.course_context_ref:
        request["course_context_ref"] = dict(ctx.course_context_ref)
    if ctx.evidence_summary:
        request["evidence_summary"] = ctx.evidence_summary[:500]
    if ctx.concept_names:
        request["concept_names"] = list(ctx.concept_names)   # display names for the evidence check (system-owned)
    if ctx.student_message:
        # [Proposed] The student's own words for the free-text scope check (spec §7.4 B). The model may rewrite
        # the query in neutral terms ("gradient vector") and so hide "Calculus II"; the check must see what the
        # student actually wrote. Used only by preflight B; never searched, never stored as text in diagnostics.
        request["scope_check_text"] = ctx.student_message[:2000]
    if args["purpose"] in ("example_lookup", "practice_generation"):
        # answer-leak guard (§6.4): never return the current problem or its bank siblings
        request["exclude"] = {"question_ids": [ctx.question_id, *ctx.bank_sibling_question_ids],
                              "same_problem_as_current": True}
    return request


def tool_for_decision(decision: Any, flavor: str = "openai", concept_menu: list[str] | None = None) -> dict[str, Any]:
    """The tool narrowed to this turn: only the purposes the grounding policy allows for the action, and
    concept fields restricted to the course's concept list (an enum, so a valid call cannot invent a concept)."""
    tool = openai_tool() if flavor == "openai" else anthropic_tool()
    params = tool["function"]["parameters"] if flavor == "openai" else tool["input_schema"]
    if concept_menu:
        params["properties"]["concept_id"]["enum"] = list(concept_menu) + [NOT_IN_COURSE]
        params["properties"]["related_concept_ids"]["items"] = {"type": "string", "enum": list(concept_menu)}
    else:
        params["properties"].pop("concept_id", None)
        params["properties"].pop("related_concept_ids", None)
    allowed = [p for p in decision.purposes if p in MODEL_PURPOSES] or list(MODEL_PURPOSES)
    params["properties"]["purpose"]["enum"] = allowed
    suggested = ", ".join(decision.need_types)
    if suggested:
        params["properties"]["evidence_needs"]["description"] += f" Typical for this turn: {suggested}."
    return tool


def build_structured_request(ctx: TurnContext, decision: Any, *, top_k: int | None = None) -> dict[str, Any]:
    """System pre-fetch for `must` turns when the model cannot be forced to call the tool.

    Built only from structured context (upstream intent + Course Context concept names), never from
    the raw student message, so `query_origin = structured`.
    """
    topic = ctx.intent_summary or ", ".join(ctx.concept_names) or (ctx.question_prompt or "")
    if not topic.strip():
        raise ToolArgumentError([{"field": "intent_summary", "code": "missing",
                                  "message": "no structured context to build a retrieval query from"}])
    concept = ", ".join(ctx.concept_names) or topic
    need_text = {
        "definition": f"Definition of {concept}", "theorem_statement": f"Statement of the theorem or rule for {concept}",
        "formula_statement": f"Formula for {concept}", "worked_example": f"Worked example using {concept}",
        "exercise": f"Practice exercise on {concept}", "method_guidance": f"How to apply {concept}: {topic}",
        "prerequisite_explanation": f"Prerequisite ideas needed for {concept}",
        "notation_convention": f"Notation used for {concept}",
    }
    query = concept if topic.strip().lower() == concept.strip().lower() else f"{concept}: {topic}"
    args = {"query": query[:300], "purpose": decision.purposes[0],
            "evidence_needs": [{"need_type": t, "description": need_text.get(t, f"{t} for {concept}")}
                               for t in decision.need_types[:4]]}
    return build_request(args, ctx, top_k=top_k, producer="tutoring-engine:prefetch")
