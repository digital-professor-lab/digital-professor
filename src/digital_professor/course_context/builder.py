"""Runtime QuestionSchema builder (application path).

Ported from the research pipeline's build_question_schema.py and adapted to use the
application's TextProvider interface instead of the research LLMClient.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any, Callable, Protocol

QUESTION_SCHEMA_VERSION = "1.0"

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


class BuildError(ValueError):
    """Raised when the question cannot be resolved or the answer fails verification."""


class _TextProvider(Protocol):
    def generate(self, *, system: str, messages: list[dict[str, str]]) -> Any: ...


class LLMAdapter:
    """Thin adapter exposing a `.complete(system, user) -> str` interface over TextProvider."""

    def __init__(self, provider: _TextProvider) -> None:
        self._provider = provider

    def complete(self, system: str, user: str) -> str:
        result = self._provider.generate(
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return result.text


def _extract_json_text(text: str) -> str:
    t = _THINK.sub("", text).strip()
    m = _FENCE.search(t)
    if m:
        t = m.group(1).strip()
    start = t.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model output.")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return t[start : i + 1]
    return t[start:]


def _complete_json(adapter: LLMAdapter, system: str, user: str) -> dict:
    raw = adapter.complete(system, user)
    try:
        json_text = _extract_json_text(raw)
    except ValueError as exc:
        raise BuildError(f"No JSON object in model output: {exc}") from exc
    try:
        return json.loads(json_text, strict=False)
    except json.JSONDecodeError as exc:
        raise BuildError(f"Model output was not valid JSON: {exc}") from exc


# --- deterministic helpers ---------------------------------------------------

def adhoc_id(primary_id: str, prompt: str) -> str:
    """Runtime id: SHA-1 of NFKC-normalised lower-cased whitespace-stripped prompt, 8 hex."""
    norm = unicodedata.normalize("NFKC", prompt).lower()
    norm = "".join(norm.split())
    h = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:8]
    return f"{primary_id}.adhoc-{h}"


def _index(cc: dict) -> dict[str, dict]:
    return {c["id"]: c for c in cc.get("Concept", []) if isinstance(c, dict)}


# --- concept matching --------------------------------------------------------

ConceptMatcher = Callable[[str, dict], "tuple[str, list[str]]"]


class LLMConceptMatcher:
    def __init__(self, adapter: LLMAdapter) -> None:
        self._adapter = adapter

    def __call__(self, prompt: str, concepts: dict) -> tuple[str, list[str]]:
        listing = "\n".join(
            f"- {c['id']} — {c.get('name', '')}: {(c.get('summary') or '')[:120]}"
            for c in concepts.values()
        )
        system = (
            "You identify the single concept a question primarily tests, chosen ONLY "
            "from a fixed list. Output ONLY a JSON object, no prose."
        )
        user = (
            f"Student question:\n{prompt}\n\n"
            f"Concepts in this course (choose ids from this list only):\n{listing}\n\n"
            'Output JSON: {"primary_concept_id": "<exactly one id from the list>", '
            '"related_concept_ids": ["<up to two other ids, or empty>"]}\n'
            "Pick the concept whose technique the question most directly requires."
        )
        out = _complete_json(self._adapter, system, user)
        primary = out.get("primary_concept_id")
        related = [c for c in (out.get("related_concept_ids") or []) if c != primary]
        return primary, related


# --- answer verification -----------------------------------------------------

def verify_answer(payload: object) -> tuple[str, str]:
    if not isinstance(payload, dict):
        return "unverified", "no verification payload"
    var_s = payload.get("variable")
    integ_s = payload.get("integrand")
    anti_s = payload.get("antiderivative")
    if not (var_s and integ_s and anti_s):
        return "unverified", "incomplete verification payload"
    try:
        import sympy
    except ImportError:
        return "unverified", "sympy not installed"
    try:
        var = sympy.Symbol(str(var_s))
        loc = {str(var_s): var}
        integrand = sympy.sympify(str(integ_s), locals=loc)
        anti = sympy.sympify(str(anti_s), locals=loc)
        if sympy.simplify(sympy.diff(anti, var) - integrand) == 0:
            return "verified", f"d/d{var_s}[{anti_s}] = {integ_s}"
        return "failed", f"d/d{var_s}[{anti_s}] != {integ_s}"
    except Exception as exc:
        return "unverified", f"symbolic check not possible: {exc}"


# --- LLM call: solve + teaching content --------------------------------------

def _runtime_parts(
    adapter: LLMAdapter,
    prompt: str,
    primary: dict,
    prereqs: list[dict],
    misconceptions: list[dict],
) -> dict:
    prereq_lines = (
        "\n".join(f"- {p['id']} — {p.get('name', '')}" for p in prereqs) or "- (none)"
    )
    misc_lines = (
        "\n".join(
            f"{i+1}. {m.get('misconception', '')} — mitigation: {m.get('mitigation', '')}"
            for i, m in enumerate(misconceptions)
        )
        or "(none)"
    )
    system = (
        "You are an expert calculus tutor and solver. Solve the problem carefully. "
        "Output ONLY a single JSON object, no prose outside it."
    )
    user = (
        f"Question (verbatim, as the student typed it):\n{prompt}\n\n"
        f"Primary concept: {primary.get('name', '')}\n"
        f"Summary: {primary.get('summary', '')}\n\n"
        f"Direct prerequisites (write why each matters for THIS question):\n{prereq_lines}\n\n"
        f"Known misconceptions for this concept (write an observable cue for each, SAME order):\n{misc_lines}\n\n"
        "Output a JSON object with EXACTLY these keys:\n"
        "{\n"
        '  "learning_objectives": [{"text": "...", "bloom_level": "..."}],\n'
        "  // 1-2 objectives this SPECIFIC question tests; bloom_level one of:\n"
        "  // remember | understand | apply | analyze | evaluate | create\n"
        '  "question_type": "one of: worked_problem | conceptual | proof | open_question",\n'
        '  "expected_response_modes": ["subset of: text, equation, steps, diagram, explanation"],\n'
        '  "correct_approach": {"technique": "the canonical technique", "justification": "why it is correct"},\n'
        '  "alternative_approaches": [{"technique": "...", "justification": "..."}],\n'
        '  "reference_answer": "the full worked solution (access-restricted ground truth)",\n'
        '  "prerequisite_relevance": {"<prerequisite id>": "why it matters for THIS question"},\n'
        '  "misconception_cues": ["observable cue for misconception 1", "... same count and order as above"],\n'
        '  "additional_misconceptions": [{"description": "...", "cue": "...", "mitigation": "..."}],\n'
        '  "verification": {"variable": "x", "integrand": "sympy-parseable integrand",'
        ' "antiderivative": "sympy-parseable antiderivative without +C"}\n'
        "  // ONLY for an indefinite integral; use null otherwise. Plain ASCII, e.g. \"x*cos(x)\".\n"
        "}"
    )
    return _complete_json(adapter, system, user)


# --- assembly ----------------------------------------------------------------

def build_runtime_question_schema(
    cc: dict,
    cc_sha256: str,
    prompt: str,
    adapter: LLMAdapter,
    *,
    concept_id: str | None = None,
    matcher: ConceptMatcher | None = None,
) -> dict:
    concepts = _index(cc)
    if not concepts:
        raise BuildError("CourseContext has no concepts")

    if concept_id:
        if concept_id not in concepts:
            raise BuildError(f"concept_id {concept_id!r} not found in CourseContext")
        primary_id, related = concept_id, []
    else:
        _matcher = matcher or LLMConceptMatcher(adapter)
        primary_id, related = _matcher(prompt, concepts)
        if primary_id not in concepts:
            raise BuildError(
                f"concept match returned unknown id {primary_id!r} (NO_CONCEPT_MATCH)"
            )
    related = [c for c in related if c in concepts and c != primary_id][:2]

    primary = concepts[primary_id]
    concept_ids = [primary_id, *related]

    prereq_records = [
        {"id": pid, "name": concepts.get(pid, {}).get("name", pid)}
        for pid in (primary.get("prerequisite_ids") or [])
    ]
    difficulty_notes = [
        dn for dn in (primary.get("difficulty_notes") or []) if isinstance(dn, dict)
    ]

    parts = _runtime_parts(adapter, prompt, primary, prereq_records, difficulty_notes)

    v_status, v_detail = verify_answer(parts.get("verification"))
    if v_status == "failed":
        raise BuildError(f"reference answer failed independent verification ({v_detail})")

    raw_los = parts.get("learning_objectives") or []
    learning_objectives = [
        {
            "id": f"{primary_id}.lo.{i}",
            "text": lo.get("text", ""),
            "bloom_level": lo.get("bloom_level", "apply"),
        }
        for i, lo in enumerate(raw_los[:3])
        if isinstance(lo, dict) and lo.get("text")
    ]

    rel = parts.get("prerequisite_relevance") or {}
    cues = parts.get("misconception_cues") or []

    prerequisite_concepts = [
        {
            "concept_id": p["id"],
            "name": p["name"],
            "relevance": rel.get(p["id"]) or f"{p['name']} is a direct prerequisite.",
            "provenance": "ai_inferred",
            "derived_from": "runtime",
        }
        for p in prereq_records
    ]

    common_misconceptions: list[dict] = []
    for i, dn in enumerate(difficulty_notes):
        common_misconceptions.append(
            {
                "description": dn.get("misconception", ""),
                "cue": (cues[i] if i < len(cues) else "") or "Written by the builder.",
                "mitigation": dn.get("mitigation", ""),
                "provenance": "ai_inferred",
                "derived_from": f"{primary_id}#difficulty_notes[{i}]",
            }
        )
    for extra in parts.get("additional_misconceptions") or []:
        if isinstance(extra, dict) and extra.get("description"):
            common_misconceptions.append(
                {
                    "description": extra.get("description", ""),
                    "cue": extra.get("cue", ""),
                    "mitigation": extra.get("mitigation", ""),
                    "provenance": "ai_inferred",
                    "derived_from": "runtime",
                }
            )

    alt = [
        {
            "technique": a.get("technique", ""),
            "justification": a.get("justification", ""),
            "provenance": "ai_inferred",
            "derived_from": "runtime",
        }
        for a in (parts.get("alternative_approaches") or [])
        if isinstance(a, dict)
    ]

    return {
        "question_schema_version": QUESTION_SCHEMA_VERSION,
        "question_id": adhoc_id(primary_id, prompt),
        "origin": "runtime",
        "course_id": (cc.get("Course") or {}).get("id"),
        "module_id": primary.get("module_id"),
        "concept_ids": concept_ids,
        "concept_names": [
            concepts.get(cid, {}).get("name", cid) for cid in concept_ids
        ],
        "prompt": prompt,
        "question_type": parts.get("question_type", "worked_problem"),
        "expected_response_modes": parts.get("expected_response_modes") or [],
        "learning_objectives": learning_objectives,
        "prerequisite_concepts": prerequisite_concepts,
        "correct_approach": {
            "technique": (parts.get("correct_approach") or {}).get("technique", ""),
            "justification": (parts.get("correct_approach") or {}).get("justification", ""),
        },
        "alternative_approaches": alt,
        "reference_answer": parts.get("reference_answer", ""),
        "common_misconceptions": common_misconceptions,
        "source_reference": {
            "concept_ids": concept_ids,
            "source_ids": [],
            "sibling_question_ids": [],
            "citation": "",
            "grounding": "reference_only",
        },
        "answer_verification": {
            "status": v_status,
            "method": "sympy-diff" if parts.get("verification") else "none",
            "detail": v_detail,
        },
        "provenance": "ai_inferred",
        "built_from": {
            "course_context_schema_version": cc.get("course_context_schema_version"),
            "content_sha256": cc_sha256,
        },
    }
