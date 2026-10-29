"""Phase 3 — QuestionSchema Builder (runtime path, v1).

Produces the per-question **QuestionSchema** target the Tutoring Engine consumes,
from a validated **CourseContext** + a free-text **question**, per course-context.md
§3.2/§3.3. This is the *runtime* path (`origin: runtime`): the question is not in a
bank, so the builder uses an LLM (provider-agnostic — DeepSeek, OpenAI, Ollama…) to
solve it and write the teaching content.

What comes from where (course-context.md §3.2):
- COPIED verbatim from the CourseContext: `learning_objectives`, misconception
  `description`/`mitigation` (from `Concept.difficulty_notes`), prerequisite names
  (from `Concept.prerequisite_ids`), `source_ids`.
- WRITTEN by the LLM: `correct_approach`, `alternative_approaches`,
  `reference_answer`, each prerequisite `relevance`, each misconception `cue`,
  `question_type`/`expected_response_modes`.
- DERIVED: the runtime id `<primary concept id>.adhoc-<8 hex>` (§3.3 step 6) and
  `built_from.content_sha256` (the exact CourseContext bytes).

Concept match (§3.3 step 3) is normally retrieval's job (Sean). Until that exists,
the builder either takes an explicit `--concept-id` or asks the LLM to pick the
primary concept from the CourseContext's concept list (never a free guess).

CLI:
    python -m course_context_pipeline.build_question_schema \
        --course-context specs/examples/calc1.course-context.json \
        --question "\\int x\\cos(x) dx" \
        --base-url https://api.deepseek.com/v1 --model deepseek-chat \
        --api-key-env DEEPSEEK_API_KEY \
        --out output/qs.xcosx.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
import unicodedata

from .config import LLMConfig
from .generate import complete_json
from .llm import LLMClient

QUESTION_SCHEMA_VERSION = "1.0"


class BuildError(ValueError):
    """Raised when the question can't be resolved against the CourseContext."""


# --- deterministic helpers ---------------------------------------------------

def adhoc_id(primary_id: str, prompt: str) -> str:
    """Runtime id per §3.3 step 6: SHA-1 of the NFKC-normalised, lower-cased,
    whitespace-stripped prompt, first 8 hex, prefixed by the primary concept id."""
    norm = unicodedata.normalize("NFKC", prompt).lower()
    norm = "".join(norm.split())
    h = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:8]
    return f"{primary_id}.adhoc-{h}"


def _index(cc: dict):
    concepts = {c["id"]: c for c in cc.get("Concept", []) if isinstance(c, dict)}
    objectives = {o["id"]: o for o in cc.get("LearningObjective", []) if isinstance(o, dict)}
    sources = {s["id"]: s for s in cc.get("Source", []) if isinstance(s, dict)}
    return concepts, objectives, sources


# --- LLM calls ---------------------------------------------------------------

def match_concept(llm: LLMClient, prompt: str, concepts: dict) -> tuple[str, list[str]]:
    """§3.3 step 3 — pick the primary concept (+ up to 2 related) from the list."""
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
    out = complete_json(llm, system, user)
    primary = out.get("primary_concept_id")
    if primary not in concepts:
        raise BuildError(f"concept match returned unknown id {primary!r} (NO_CONCEPT_MATCH)")
    related = [c for c in (out.get("related_concept_ids") or []) if c in concepts and c != primary][:2]
    return primary, related


def runtime_parts(llm: LLMClient, prompt: str, primary: dict,
                  prereqs: list[dict], misconceptions: list[dict]) -> dict:
    """§3.3 step 5 — solve the question and write the teaching content."""
    keydefs = "\n".join(f"- {d}" for d in (primary.get("key_definitions") or [])) or "- (none)"
    prereq_lines = "\n".join(f"- {p['id']} — {p.get('name','')}" for p in prereqs) or "- (none)"
    misc_lines = "\n".join(
        f"{i+1}. {m.get('misconception','')} — mitigation: {m.get('mitigation','')}"
        for i, m in enumerate(misconceptions)
    ) or "(none)"

    system = ("You are an expert calculus tutor and solver. Solve the problem carefully and "
              "VERIFY the final answer (for an integral, differentiate your result and confirm "
              "it equals the integrand). Output ONLY a single JSON object, no prose outside it.")
    user = (
        f"Question (verbatim, as the student typed it):\n{prompt}\n\n"
        f"Primary concept: {primary.get('name','')}\n"
        f"Summary: {primary.get('summary','')}\n"
        f"Key definitions:\n{keydefs}\n\n"
        f"Direct prerequisites (write why each matters for THIS question):\n{prereq_lines}\n\n"
        f"Known misconceptions for this concept (write an observable cue for each, SAME order):\n{misc_lines}\n\n"
        "Output a JSON object with EXACTLY these keys:\n"
        '{\n'
        '  "question_type": "one of: worked_problem | conceptual | proof | open_question",\n'
        '  "expected_response_modes": ["subset of: text, equation, steps, diagram, explanation"],\n'
        '  "correct_approach": {"technique": "the canonical technique", "justification": "why it is correct"},\n'
        '  "alternative_approaches": [{"technique": "...", "justification": "..."}],\n'
        '  "reference_answer": "the full worked solution ending with the verification step (access-restricted ground truth)",\n'
        '  "prerequisite_relevance": {"<prerequisite id>": "why it matters for THIS question"},\n'
        '  "misconception_cues": ["observable cue for misconception 1", "... same count and order as above"],\n'
        '  "additional_misconceptions": [{"description": "...", "cue": "...", "mitigation": "..."}]\n'
        '}'
    )
    return complete_json(llm, system, user)


# --- assembly ----------------------------------------------------------------

def build_runtime_question_schema(cc: dict, cc_sha256: str, prompt: str, llm: LLMClient,
                                  concept_id: str | None = None) -> dict:
    concepts, objectives, sources = _index(cc)
    if not concepts:
        raise BuildError("CourseContext has no concepts")

    if concept_id:                                   # explicit concept wins (skips the LLM match)
        if concept_id not in concepts:
            raise BuildError(f"--concept-id {concept_id!r} not found in CourseContext")
        primary_id, related = concept_id, []
    else:
        primary_id, related = match_concept(llm, prompt, concepts)

    primary = concepts[primary_id]
    concept_ids = [primary_id, *related]

    # --- copied verbatim from the CourseContext ---
    lo_ids: list[str] = []
    for cid in concept_ids:
        lo_ids.extend(concepts[cid].get("objective_ids") or [])
    learning_objectives = [
        {"id": objectives[o]["id"], "text": objectives[o]["text"], "bloom_level": objectives[o]["bloom_level"]}
        for o in dict.fromkeys(lo_ids) if o in objectives
    ]
    prereq_records = [{"id": pid, "name": concepts.get(pid, {}).get("name", pid)}
                      for pid in (primary.get("prerequisite_ids") or [])]
    difficulty_notes = [dn for dn in (primary.get("difficulty_notes") or []) if isinstance(dn, dict)]

    # --- LLM-written runtime content ---
    parts = runtime_parts(llm, prompt, primary, prereq_records, difficulty_notes)
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

    source_ids = list(primary.get("source_ids") or [])
    citation = "; ".join(
        " ".join(x for x in (sources[sid].get("citation"), sources[sid].get("section")) if x)
        for sid in source_ids if sid in sources
    )

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
            "source_ids": source_ids,
            "sibling_question_ids": [],              # no external bank in v1
            "citation": citation,
            "grounding": "reference_only",
        },
        "provenance": "ai_inferred",                 # weakest link
        "built_from": {
            "course_context_schema_version": cc.get("course_context_schema_version"),
            "content_sha256": cc_sha256,
        },
    }


CORE_KEYS = {
    "question_schema_version", "question_id", "origin", "course_id", "module_id",
    "concept_ids", "prompt", "question_type", "learning_objectives",
    "prerequisite_concepts", "correct_approach", "alternative_approaches",
    "reference_answer", "common_misconceptions", "source_reference", "provenance", "built_from",
}


def shape_errors(qs: dict) -> list[str]:
    errs = []
    missing = CORE_KEYS - set(qs.keys())
    if missing:
        errs.append(f"missing keys: {sorted(missing)}")
    if not qs.get("reference_answer"):
        errs.append("reference_answer is empty (the LLM did not return a solution)")
    if not (qs.get("correct_approach") or {}).get("technique"):
        errs.append("correct_approach.technique is empty")
    return errs


# --- CLI --------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="build-question-schema",
        description="Build a QuestionSchema from a CourseContext + a free-text question (runtime path).")
    ap.add_argument("--course-context", required=True, help="validated CourseContext JSON")
    ap.add_argument("--question", required=True, help="the question, exactly as the student typed it")
    ap.add_argument("--concept-id", help="skip LLM concept-match and use this primary concept id")
    ap.add_argument("--out", help="output QuestionSchema path (default: stdout)")
    # LLM (provider-agnostic; defaults to the LLMConfig defaults = local Ollama)
    ap.add_argument("--base-url"); ap.add_argument("--model"); ap.add_argument("--api-key-env")
    ap.add_argument("--temperature", type=float); ap.add_argument("--max-tokens", type=int)
    args = ap.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    kw = {k: getattr(args, k) for k in ("base_url", "model", "api_key_env", "temperature", "max_tokens")
          if getattr(args, k) is not None}
    llm = LLMClient(LLMConfig(**kw))

    cc_path = pathlib.Path(args.course_context)
    cc_text = cc_path.read_text(encoding="utf-8")
    cc = json.loads(cc_text)
    cc_sha256 = hashlib.sha256(cc_text.encode("utf-8")).hexdigest()

    try:
        qs = build_runtime_question_schema(cc, cc_sha256, args.question, llm, concept_id=args.concept_id)
    except BuildError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2

    for e in shape_errors(qs):
        print(f"[warn] {e}", file=sys.stderr)

    text = json.dumps(qs, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"[done] wrote {out}  id={qs['question_id']} concept={qs['concept_ids'][0]} "
              f"objectives={len(qs['learning_objectives'])} prereqs={len(qs['prerequisite_concepts'])} "
              f"misconceptions={len(qs['common_misconceptions'])}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
