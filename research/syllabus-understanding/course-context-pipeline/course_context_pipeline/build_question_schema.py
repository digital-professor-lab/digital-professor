"""Phase 3 — QuestionSchema Builder (runtime path, v1).

Produces the per-question **QuestionSchema** target the Tutoring Engine consumes,
from a validated **CourseContext** + a free-text **question**, per course-context.md
§3.2/§3.3. The *runtime* path (`origin: runtime`): the question is not in a bank, so
the builder uses an LLM (provider-agnostic — DeepSeek/OpenAI/Ollama) to solve it and
write the teaching content.

What comes from where (course-context.md §3.2):
- COPIED verbatim from the CourseContext: misconception `description`/`mitigation`,
  prerequisite names.
- WRITTEN by the LLM: `learning_objectives` (derived from concept + question type),
  `correct_approach`, `alternative_approaches`, `reference_answer`, each prerequisite
  `relevance`, each misconception `cue`, `question_type`/modes.
- DERIVED: the runtime id `<primary concept id>.adhoc-<8 hex>` (§3.3 step 6) and
  `built_from.content_sha256` (the exact CourseContext bytes).

Guardrails added for review:
- **Concept match** goes through a replaceable `ConceptMatcher` (default: LLM) so
  Sean's retrieval can slot in without rewriting the builder (§3.3 step 3).
- **Independent answer verification** (`verify_answer`): sympy symbolically checks the
  LLM's claimed antiderivative against the integrand — the LLM does not grade itself.
  A failed check raises (no schema, §3.3 step 5); an uncheckable answer is marked
  `answer_verification.status = "unverified"` and must NOT be trusted as ground truth.
- **Full schema validation** (`validate_question_schema`) + publication gating in the
  CLI: an invalid QuestionSchema is never written as successful output; it goes to a
  `.rejected.json` and the CLI exits nonzero.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import unicodedata
from typing import Callable

from .config import LLMConfig
from .generate import GenerationError, complete_json
from .llm import LLMClient

QUESTION_SCHEMA_VERSION = "1.0"

# enums (course-context.md §3.2 / interfaces.md §3)
ORIGIN = {"bank", "runtime"}
QUESTION_TYPE = {"worked_problem", "conceptual", "proof", "open_question"}
RESPONSE_MODES = {"text", "equation", "steps", "diagram", "explanation"}
GROUNDING = {"reference_only", "excerpt"}
PROVENANCE = {"source_backed", "ai_inferred"}
BLOOM = {"remember", "understand", "apply", "analyze", "evaluate", "create"}


class BuildError(ValueError):
    """Raised when the question can't be resolved, or the answer fails verification."""


# --- deterministic helpers ---------------------------------------------------

def adhoc_id(primary_id: str, prompt: str) -> str:
    """Runtime id per §3.3 step 6: SHA-1 of the NFKC-normalised, lower-cased,
    whitespace-stripped prompt, first 8 hex, prefixed by the primary concept id."""
    norm = unicodedata.normalize("NFKC", prompt).lower()
    norm = "".join(norm.split())
    h = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:8]
    return f"{primary_id}.adhoc-{h}"


def _index(cc: dict) -> dict:
    """Return a concept-id → concept dict for fast lookups."""
    return {c["id"]: c for c in cc.get("Concept", []) if isinstance(c, dict)}


# --- concept matching: a replaceable interface -------------------------------

# A ConceptMatcher maps (prompt, concepts) -> (primary_concept_id, [related ids]).
# The LLM implementation below is a stand-in for Sean's retrieval; swapping it in
# is just passing a different matcher, no builder changes.
ConceptMatcher = Callable[[str, dict], "tuple[str, list[str]]"]


class LLMConceptMatcher:
    """Default ConceptMatcher: asks the LLM to pick from the concept list."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    def __call__(self, prompt: str, concepts: dict) -> tuple[str, list[str]]:
        listing = "\n".join(
            f"- {c['id']} — {c.get('name','')}: {(c.get('summary') or '')[:120]}"
            for c in concepts.values()
        )
        system = ("You identify the single concept a question primarily tests, chosen ONLY "
                  "from a fixed list. Output ONLY a JSON object, no prose.")
        user = (
            f"Student question:\n{prompt}\n\n"
            f"Concepts in this course (choose ids from this list only):\n{listing}\n\n"
            'Output JSON: {"primary_concept_id": "<exactly one id from the list>", '
            '"related_concept_ids": ["<up to two other ids, or empty>"]}\n'
            "Pick the concept whose technique the question most directly requires."
        )
        out = complete_json(self.llm, system, user)
        primary = out.get("primary_concept_id")
        related = [c for c in (out.get("related_concept_ids") or []) if c != primary]
        return primary, related


# --- independent answer verification -----------------------------------------

def verify_answer(payload: object) -> tuple[str, str]:
    """Independently check the answer with sympy (the LLM does NOT grade itself).

    `payload` = {variable, integrand, antiderivative} (sympy-parseable strings) that
    the LLM supplies for an integral. sympy differentiates the claimed antiderivative
    and compares it to the integrand. Returns (status, detail):
      - "verified"   : d/dvar[antiderivative] == integrand
      - "failed"     : it does NOT equal (a wrong answer — caller must reject)
      - "unverified" : no/invalid payload, sympy missing, or unparseable
    """
    if not isinstance(payload, dict):
        return "unverified", "no verification payload"
    var_s, integ_s, anti_s = payload.get("variable"), payload.get("integrand"), payload.get("antiderivative")
    if not (var_s and integ_s and anti_s):
        return "unverified", "incomplete verification payload"
    try:
        import sympy
    except ImportError:                                  # pragma: no cover
        return "unverified", "sympy not installed"
    try:
        var = sympy.Symbol(str(var_s))
        loc = {str(var_s): var}
        integrand = sympy.sympify(str(integ_s), locals=loc)
        anti = sympy.sympify(str(anti_s), locals=loc)
        if sympy.simplify(sympy.diff(anti, var) - integrand) == 0:
            return "verified", f"d/d{var_s}[{anti_s}] = {integ_s}"
        return "failed", f"d/d{var_s}[{anti_s}] != {integ_s}"
    except Exception as e:                               # unparseable -> can't check
        return "unverified", f"symbolic check not possible: {e}"


# --- LLM call: solve + teaching content --------------------------------------

def runtime_parts(llm: LLMClient, prompt: str, primary: dict,
                  prereqs: list[dict], misconceptions: list[dict]) -> dict:
    """§3.3 step 5 — solve the question and write the teaching content.

    Learning objectives are derived here (not pre-defined in the CourseContext)
    because they are inherently question-scoped: the same concept can be tested
    at different Bloom levels depending on the question.
    """
    prereq_lines = "\n".join(f"- {p['id']} — {p.get('name','')}" for p in prereqs) or "- (none)"
    misc_lines = "\n".join(
        f"{i+1}. {m.get('misconception','')} — mitigation: {m.get('mitigation','')}"
        for i, m in enumerate(misconceptions)
    ) or "(none)"

    system = ("You are an expert calculus tutor and solver. Solve the problem carefully. "
              "Output ONLY a single JSON object, no prose outside it.")
    user = (
        f"Question (verbatim, as the student typed it):\n{prompt}\n\n"
        f"Primary concept: {primary.get('name','')}\n"
        f"Summary: {primary.get('summary','')}\n\n"
        f"Direct prerequisites (write why each matters for THIS question):\n{prereq_lines}\n\n"
        f"Known misconceptions for this concept (write an observable cue for each, SAME order):\n{misc_lines}\n\n"
        "Output a JSON object with EXACTLY these keys:\n"
        '{\n'
        '  "learning_objectives": [{"text": "...", "bloom_level": "..."}],\n'
        '  // 1-2 objectives this SPECIFIC question tests; bloom_level one of:\n'
        '  // remember | understand | apply | analyze | evaluate | create\n'
        '  "question_type": "one of: worked_problem | conceptual | proof | open_question",\n'
        '  "expected_response_modes": ["subset of: text, equation, steps, diagram, explanation"],\n'
        '  "correct_approach": {"technique": "the canonical technique", "justification": "why it is correct"},\n'
        '  "alternative_approaches": [{"technique": "...", "justification": "..."}],\n'
        '  "reference_answer": "the full worked solution (access-restricted ground truth)",\n'
        '  "prerequisite_relevance": {"<prerequisite id>": "why it matters for THIS question"},\n'
        '  "misconception_cues": ["observable cue for misconception 1", "... same count and order as above"],\n'
        '  "additional_misconceptions": [{"description": "...", "cue": "...", "mitigation": "..."}],\n'
        '  "verification": {"variable": "x", "integrand": "sympy-parseable integrand",'
        ' "antiderivative": "sympy-parseable antiderivative without +C"}'
        '  // ONLY for an indefinite integral; use null otherwise. Plain ASCII, e.g. "x*cos(x)".\n'
        '}'
    )
    return complete_json(llm, system, user)


# --- assembly ----------------------------------------------------------------

def build_runtime_question_schema(cc: dict, cc_sha256: str, prompt: str, llm: LLMClient,
                                  concept_id: str | None = None,
                                  matcher: ConceptMatcher | None = None) -> dict:
    concepts = _index(cc)
    if not concepts:
        raise BuildError("CourseContext has no concepts")

    if concept_id:                                   # explicit concept wins (skips matching)
        if concept_id not in concepts:
            raise BuildError(f"--concept-id {concept_id!r} not found in CourseContext")
        primary_id, related = concept_id, []
    else:
        matcher = matcher or LLMConceptMatcher(llm)
        primary_id, related = matcher(prompt, concepts)
        if primary_id not in concepts:
            raise BuildError(f"concept match returned unknown id {primary_id!r} (NO_CONCEPT_MATCH)")
    related = [c for c in related if c in concepts and c != primary_id][:2]

    primary = concepts[primary_id]
    concept_ids = [primary_id, *related]

    prereq_records = [{"id": pid, "name": concepts.get(pid, {}).get("name", pid)}
                      for pid in (primary.get("prerequisite_ids") or [])]
    difficulty_notes = [dn for dn in (primary.get("difficulty_notes") or []) if isinstance(dn, dict)]

    # --- LLM-written runtime content ---
    parts = runtime_parts(llm, prompt, primary, prereq_records, difficulty_notes)

    # independent verification (the LLM does not grade itself)
    v_status, v_detail = verify_answer(parts.get("verification"))
    if v_status == "failed":
        raise BuildError(f"reference answer failed independent verification ({v_detail})")

    # learning_objectives: derived from concept + question type by the LLM,
    # assigned synthetic ids since the CourseContext no longer carries LO records.
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

    prerequisite_concepts = [{
        "concept_id": p["id"],
        "name": p["name"],
        "relevance": rel.get(p["id"]) or f"{p['name']} is a direct prerequisite for this question.",
        "provenance": "ai_inferred",
        "derived_from": "runtime",
    } for p in prereq_records]

    common_misconceptions = []
    for i, dn in enumerate(difficulty_notes):
        common_misconceptions.append({
            "description": dn.get("misconception", ""),
            "cue": (cues[i] if i < len(cues) else "") or "Written by the builder.",
            "mitigation": dn.get("mitigation", ""),
            "provenance": "ai_inferred",
            "derived_from": f"{primary_id}#difficulty_notes[{i}]",
        })
    for extra in (parts.get("additional_misconceptions") or []):
        if isinstance(extra, dict) and extra.get("description"):
            common_misconceptions.append({
                "description": extra.get("description", ""),
                "cue": extra.get("cue", ""),
                "mitigation": extra.get("mitigation", ""),
                "provenance": "ai_inferred",
                "derived_from": "runtime",
            })

    alt = [{"technique": a.get("technique", ""), "justification": a.get("justification", ""),
            "provenance": "ai_inferred", "derived_from": "runtime"}
           for a in (parts.get("alternative_approaches") or []) if isinstance(a, dict)]

    return {
        "question_schema_version": QUESTION_SCHEMA_VERSION,
        "question_id": adhoc_id(primary_id, prompt),
        "origin": "runtime",
        "course_id": (cc.get("Course") or {}).get("id"),
        "module_id": primary.get("module_id"),
        "concept_ids": concept_ids,
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
            # source_ids removed from CourseContext schema; filled by retrieval tool if available
            "source_ids": [],
            "sibling_question_ids": [],
            "citation": "",
            "grounding": "reference_only",
        },
        # additive marker: whether the reference_answer was independently checked.
        # "unverified" MUST NOT be treated as trusted ground truth downstream.
        "answer_verification": {
            "status": v_status,                      # verified | unverified
            "method": "sympy-diff" if parts.get("verification") else "none",
            "detail": v_detail,
        },
        "provenance": "ai_inferred",                 # weakest link
        "built_from": {
            "course_context_schema_version": cc.get("course_context_schema_version"),
            "content_sha256": cc_sha256,
        },
    }


# --- full QuestionSchema validation ------------------------------------------

_REQUIRED_KEYS = {
    "question_schema_version", "question_id", "origin", "course_id", "module_id",
    "concept_ids", "prompt", "question_type", "learning_objectives",
    "prerequisite_concepts", "correct_approach", "alternative_approaches",
    "reference_answer", "common_misconceptions", "source_reference", "provenance", "built_from",
}
_OPTIONAL_KEYS = {"expected_response_modes", "rubric", "constraints", "answer_verification"}


def validate_question_schema(qs: dict, cc: dict) -> list[str]:
    """Structural + referential + consistency validation against the CourseContext.
    Returns a list of error strings (empty = valid).
    """
    e: list[str] = []
    if not isinstance(qs, dict):
        return ["QuestionSchema is not a JSON object"]
    concepts = _index(cc)

    # top-level: required present, no unknown keys
    keys = set(qs.keys())
    for k in _REQUIRED_KEYS - keys:
        e.append(f"missing required field: {k}")
    for k in keys - (_REQUIRED_KEYS | _OPTIONAL_KEYS):
        e.append(f"unknown field: {k}")

    def _ne(field):
        v = qs.get(field)
        if v is None or (isinstance(v, str) and not v.strip()):
            e.append(f"{field} is empty")

    for f in ("question_id", "course_id", "module_id", "prompt", "reference_answer"):
        _ne(f)

    # enums
    if qs.get("origin") not in ORIGIN:
        e.append(f"origin {qs.get('origin')!r} not in {sorted(ORIGIN)}")
    if qs.get("question_type") not in QUESTION_TYPE:
        e.append(f"question_type {qs.get('question_type')!r} not in {sorted(QUESTION_TYPE)}")
    for m in qs.get("expected_response_modes") or []:
        if m not in RESPONSE_MODES:
            e.append(f"expected_response_modes value {m!r} not in {sorted(RESPONSE_MODES)}")
    if qs.get("provenance") not in PROVENANCE:
        e.append(f"provenance {qs.get('provenance')!r} not in {sorted(PROVENANCE)}")

    # concept_ids resolve; module/course consistency
    cids = qs.get("concept_ids") or []
    if not isinstance(cids, list) or not cids:
        e.append("concept_ids must be a non-empty list")
        cids = []
    for cid in cids:
        if cid not in concepts:
            e.append(f"concept_ids -> {cid!r} not found in CourseContext")
    primary = concepts.get(cids[0]) if cids else None
    if primary is not None:
        if qs.get("module_id") != primary.get("module_id"):
            e.append("module_id does not match the primary concept's module_id")
    if qs.get("course_id") != (cc.get("Course") or {}).get("id"):
        e.append("course_id does not match the CourseContext Course.id")

    # learning_objectives: structure only (ids are synthetic, no LO records to cross-reference)
    for lo in qs.get("learning_objectives") or []:
        if not isinstance(lo, dict) or {"id", "text", "bloom_level"} - set(lo):
            e.append("learning_objectives entry must have id, text, bloom_level")
            continue
        if lo.get("bloom_level") not in BLOOM:
            e.append(f"learning_objectives entry has invalid bloom_level {lo.get('bloom_level')!r}")

    # prerequisite_concepts: resolve + are DIRECT prerequisites of the primary
    direct = set(primary.get("prerequisite_ids") or []) if primary else set()
    for p in qs.get("prerequisite_concepts") or []:
        if not isinstance(p, dict) or {"concept_id", "name", "relevance", "provenance", "derived_from"} - set(p):
            e.append("prerequisite_concepts entry missing required keys")
            continue
        if p["concept_id"] not in concepts:
            e.append(f"prerequisite concept {p['concept_id']!r} not found in CourseContext")
        elif p["concept_id"] not in direct:
            e.append(f"prerequisite {p['concept_id']!r} is not a direct prerequisite of the primary concept")
        if p.get("provenance") not in PROVENANCE:
            e.append(f"prerequisite {p.get('concept_id')!r} provenance invalid")

    # correct_approach
    ca = qs.get("correct_approach") or {}
    if not isinstance(ca, dict) or not ca.get("technique") or not ca.get("justification"):
        e.append("correct_approach must have non-empty technique and justification")

    # alternative_approaches
    for a in qs.get("alternative_approaches") or []:
        if not isinstance(a, dict) or {"technique", "justification", "provenance", "derived_from"} - set(a):
            e.append("alternative_approaches entry missing required keys")
        elif a.get("provenance") not in PROVENANCE:
            e.append("alternative_approaches provenance invalid")

    # common_misconceptions
    for m in qs.get("common_misconceptions") or []:
        if not isinstance(m, dict) or {"description", "cue", "provenance", "derived_from"} - set(m):
            e.append("common_misconceptions entry missing required keys")
        elif m.get("provenance") not in PROVENANCE:
            e.append("common_misconceptions provenance invalid")

    # source_reference: structure only (source_ids empty in v1; retrieval fills later)
    sr = qs.get("source_reference") or {}
    if not isinstance(sr, dict) or {"concept_ids", "source_ids", "sibling_question_ids", "citation", "grounding"} - set(sr):
        e.append("source_reference missing required keys")
    elif sr.get("grounding") not in GROUNDING:
        e.append(f"source_reference.grounding {sr.get('grounding')!r} not in {sorted(GROUNDING)}")

    # built_from
    bf = qs.get("built_from") or {}
    if not isinstance(bf, dict) or {"course_context_schema_version", "content_sha256"} - set(bf):
        e.append("built_from must have course_context_schema_version and content_sha256")

    # answer_verification (optional, additive)
    av = qs.get("answer_verification")
    if av is not None:
        if not isinstance(av, dict) or av.get("status") not in {"verified", "unverified"}:
            e.append("answer_verification.status must be 'verified' or 'unverified'")

    return e


# --- CLI ---------------------------------------------------------------------

def main(argv: list[str] | None = None, llm: LLMClient | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="build-question-schema",
        description="Build a QuestionSchema from a CourseContext + a free-text question (runtime path).")
    ap.add_argument("--course-context", required=True, help="validated CourseContext JSON")
    ap.add_argument("--question", required=True, help="the question, exactly as the student typed it")
    ap.add_argument("--concept-id", help="skip LLM concept-match and use this primary concept id")
    ap.add_argument("--out", help="output QuestionSchema path (default: stdout)")
    ap.add_argument("--base-url"); ap.add_argument("--model"); ap.add_argument("--api-key-env")
    ap.add_argument("--temperature", type=float); ap.add_argument("--max-tokens", type=int)
    args = ap.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    if llm is None:                                      # injectable for testing
        kw = {k: getattr(args, k) for k in ("base_url", "model", "api_key_env", "temperature", "max_tokens")
              if getattr(args, k) is not None}
        llm = LLMClient(LLMConfig(**kw))

    cc_path = pathlib.Path(args.course_context)
    cc_text = cc_path.read_text(encoding="utf-8")
    cc = json.loads(cc_text)
    cc_sha256 = hashlib.sha256(cc_text.encode("utf-8")).hexdigest()

    try:
        qs = build_runtime_question_schema(cc, cc_sha256, args.question, llm, concept_id=args.concept_id)
    except (BuildError, GenerationError) as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2

    # Gate publication: an invalid QuestionSchema is NOT written as successful output.
    errors = validate_question_schema(qs, cc)
    text = json.dumps(qs, indent=2, ensure_ascii=False) + "\n"
    if errors:
        for err in errors:
            print(f"[error] {err}", file=sys.stderr)
        if args.out:
            out = pathlib.Path(args.out)
            rejected = out.parent / (out.stem + ".rejected.json")
            rejected.parent.mkdir(parents=True, exist_ok=True)
            rejected.write_text(text, encoding="utf-8")
            print(f"[reject] {len(errors)} schema error(s) — not published; wrote {rejected}", file=sys.stderr)
        return 2

    if args.out:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"[done] wrote {out}  id={qs['question_id']} concept={qs['concept_ids'][0]} "
              f"verification={qs['answer_verification']['status']}")
    else:
        print(text)
    if qs["answer_verification"]["status"] != "verified":
        print("[warn] reference_answer is UNVERIFIED — do not treat it as trusted ground truth", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
