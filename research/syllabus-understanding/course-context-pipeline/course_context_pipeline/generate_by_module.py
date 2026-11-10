"""Chunked Stage A generation: outline first, then one LLM call per module.

Why: a whole CourseContext can exceed a model's per-response output cap
(e.g. ~8K tokens for deepseek-chat), so a single pass truncates into invalid
JSON. Generating module-by-module keeps every response small, then we assemble
the slices into one CourseContext.

The existing syllabus-to-json prompt (design-example/syllabus-to-json-prompt.md)
is reused as the *system* message so the model knows the full schema, field
rules and ID conventions; each call's *user* message restricts what slice of
that schema to emit this time.
"""
from __future__ import annotations

from .generate import complete_json
from .llm import LLMClient


def _outline_user(syllabus_text: str) -> str:
    return (
        "For THIS request, output ONLY the course outline — not the full file.\n\n"
        "Return a single JSON object with EXACTLY these top-level keys:\n"
        '- "course_context_schema_version": "1.1"\n'
        '- "Course": an object with id, title, level, duration_weeks, '
        "assumed_background, module_ids (all module ids in teaching order), provenance\n"
        '- "Module": an array with one object per unit, in teaching order, each with '
        'id, course_id, title, goal, weeks, concept_ids (use an empty array []), provenance\n'
        '- "assumptions": an array of {entity, id, field, assumption, reason, confidence} '
        "objects — one entry per genuinely INFERRED Course- or Module-level value (e.g. level, "
        "duration_weeks, a module goal or week span). Do NOT log an entry for a value copied "
        "from the syllabus (e.g. a module title). Use [] if none.\n"
        '  "confidence" is your honest "high" | "medium" | "low": high = a standard inference a '
        "domain expert would almost certainly agree with; medium = a reasonable default that "
        "could plausibly differ; low = a genuine guess with little basis in the syllabus.\n\n"
        "Field rules:\n"
        '- "weeks" is a STRING, "N" or "N-M" (e.g. "2" or "3-4") — never a number.\n'
        '- "provenance" is EXACTLY one of "source_backed" or "ai_inferred" — never free text. '
        "Mark a record source_backed only when EVERY non-structural value on it is copied from "
        "the syllabus; otherwise ai_inferred.\n"
        '- Consistency: if you add an assumptions entry naming a record, that record\'s '
        'provenance MUST be "ai_inferred" (logging an assumption means a field was inferred). '
        "Never mark a record source_backed and also log an assumption about it.\n\n"
        "Do NOT include Concept, LearningObjective, or Source in this response. "
        "Follow the ID conventions and field rules from the schema above.\n\n"
        "=== SYLLABUS START ===\n"
        f"{syllabus_text}\n"
        "=== SYLLABUS END ==="
    )


def _module_user(syllabus_text: str, course: dict, modules: list[dict],
                 module: dict, prior_concept_ids: list[str]) -> str:
    module_list = "\n".join(
        f"  {m.get('id')} — {m.get('title')}" for m in modules
    )
    prior = "\n".join(f"  {cid}" for cid in prior_concept_ids) or "  (none yet)"
    mid = module.get("id", "")
    return (
        "For THIS request, expand ONE module of a course whose outline is already "
        "decided. Output ONLY that module's content.\n\n"
        f"Course: id=\"{course.get('id')}\", title=\"{course.get('title')}\", "
        f"level=\"{course.get('level')}\", "
        f"assumed_background=\"{course.get('assumed_background')}\".\n\n"
        "All modules in this course (teaching order) — valid targets for cross-module "
        "prerequisites:\n"
        f"{module_list}\n\n"
        "Concept IDs already created in earlier modules (also valid prerequisite targets):\n"
        f"{prior}\n\n"
        "Expand THIS module only:\n"
        f"  id:    {mid}\n"
        f"  title: {module.get('title')}\n"
        f"  goal:  {module.get('goal')}\n\n"
        "Return a single JSON object with EXACTLY these top-level keys:\n"
        f'- "Concept": the concepts for THIS module. Each: id (= "{mid}.<slug>"), '
        f'module_id (= "{mid}"), name, summary, key_definitions[], prerequisite_ids[] '
        "(concept ids from THIS module or from the lists above only — never invent an id; "
        "empty array if the only prerequisite is assumed background), objective_ids[], "
        "difficulty_notes[] (each entry EXACTLY {misconception, mitigation}; [] if none), "
        "source_ids[], provenance\n"
        '- "LearningObjective": the objectives referenced by this module\'s concepts. '
        'Each: id (= "<concept id>.lo<n>"), concept_id, text, bloom_level, provenance\n'
        '- "Source": the Sources this module\'s concepts cite. Each: id, type, citation, '
        "section, text_chunk, provenance. Reuse a stable id (e.g. \"neuhauser.s7-2\") if "
        "the same source recurs across modules.\n"
        '- "assumptions": an array of {entity, id, field, assumption, reason, confidence} '
        "objects — one entry per genuinely INFERRED value in THIS module (summaries, "
        "prerequisites, difficulty notes, objectives, etc.). Do NOT log an entry for a value "
        "copied from the syllabus, and in particular do NOT log assumptions about Source "
        "records whose citation/section come straight from the syllabus. Use [] if none.\n"
        '  "confidence" is your honest "high" | "medium" | "low": high = a standard inference a '
        "domain expert would almost certainly agree with; medium = a reasonable default that "
        "could plausibly differ; low = a genuine guess with little basis in the syllabus.\n\n"
        "Field rules:\n"
        '- "provenance" is EXACTLY one of "source_backed" or "ai_inferred" — never free text. '
        "Mark a record source_backed only when EVERY non-structural value on it is copied from "
        "the syllabus (a Source whose citation and section are from the syllabus is "
        "source_backed); otherwise ai_inferred.\n"
        '- Consistency: if you add an assumptions entry naming a record, that record\'s '
        'provenance MUST be "ai_inferred" — never mark a record source_backed and also log an '
        "assumption about it.\n"
        '- each "difficulty_notes" entry has exactly the keys misconception and mitigation.\n\n'
        "Do NOT include Course or Module. Do NOT reference prerequisite ids that are not in "
        "the lists above.\n\n"
        "=== SYLLABUS START ===\n"
        f"{syllabus_text}\n"
        "=== SYLLABUS END ==="
    )


def generate_outline(syllabus_text: str, prompt_text: str, llm: LLMClient) -> dict:
    """Call 1: Course header + Module shells (no concepts yet)."""
    return complete_json(llm, prompt_text, _outline_user(syllabus_text))


def generate_module(syllabus_text: str, prompt_text: str, course: dict,
                    modules: list[dict], module: dict,
                    prior_concept_ids: list[str], llm: LLMClient) -> dict:
    """Call N: the Concept/LearningObjective/Source slice for one module."""
    user = _module_user(syllabus_text, course, modules, module, prior_concept_ids)
    return complete_json(llm, prompt_text, user)


def assemble(outline: dict, module_results: list[dict]) -> dict:
    """Merge the outline + per-module slices into one CourseContext dict.

    - concatenates Concept / LearningObjective arrays
    - de-duplicates Source by id (one source can back several modules)
    - back-fills Module.concept_ids and Course.module_ids from what was produced
    """
    course = outline.get("Course") or {}
    cc: dict = {
        "course_context_schema_version": outline.get("course_context_schema_version", "1.1"),
        "Course": course,
        "Module": outline.get("Module") or [],
        "Concept": [],
        "LearningObjective": [],
        "Source": [],
    }
    assumptions = list(outline.get("assumptions") or [])
    seen_sources: set[str] = set()

    for res in module_results:
        cc["Concept"].extend(res.get("Concept") or [])
        cc["LearningObjective"].extend(res.get("LearningObjective") or [])
        for s in (res.get("Source") or []):
            sid = s.get("id")
            if sid and sid in seen_sources:
                continue
            if sid:
                seen_sources.add(sid)
            cc["Source"].append(s)
        assumptions.extend(res.get("assumptions") or [])

    # back-fill Module.concept_ids from the concepts' module_id
    by_mod: dict[str, list[str]] = {}
    for c in cc["Concept"]:
        by_mod.setdefault(c.get("module_id"), []).append(c.get("id"))
    for m in cc["Module"]:
        m["concept_ids"] = by_mod.get(m.get("id"), [])

    # back-fill Course.module_ids if the outline left it empty
    if not course.get("module_ids"):
        course["module_ids"] = [m.get("id") for m in cc["Module"]]

    if assumptions:
        cc["assumptions"] = assumptions
    return cc
