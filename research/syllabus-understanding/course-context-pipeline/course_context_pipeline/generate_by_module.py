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
        '- "Course": an object with id, title, level, '
        "assumed_background, module_ids (all module ids in teaching order), provenance\n"
        '- "Module": an array with one object per unit, in teaching order, each with '
        'id, course_id, title, goal, concept_ids (use an empty array []), provenance\n'
        '- "assumptions": an array of {entity, id, field, assumption, reason, confidence} '
        "objects — one entry per genuinely INFERRED Course- or Module-level value (e.g. level, "
        "a module goal). Do NOT log an entry for a value copied "
        "from the syllabus (e.g. a module title). Use [] if none.\n"
        '  "confidence" is your honest "high" | "medium" | "low": high = a standard inference a '
        "domain expert would almost certainly agree with; medium = a reasonable default that "
        "could plausibly differ; low = a genuine guess with little basis in the syllabus.\n\n"
        "Field rules:\n"
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
        f'module_id (= "{mid}"), name, summary, prerequisite_ids[] '
        "(concept ids from THIS module or from the lists above only — never invent an id; "
        "empty array if the only prerequisite is assumed background), "
        "difficulty_notes[] (each entry EXACTLY {misconception, mitigation}; [] if none), "
        "provenance\n"
        '- "assumptions": an array of {entity, id, field, assumption, reason, confidence} '
        "objects — one entry per genuinely INFERRED value in THIS module (summaries, "
        "prerequisites, difficulty notes). Use [] if none.\n"
        '  "confidence" is your honest "high" | "medium" | "low": high = a standard inference a '
        "domain expert would almost certainly agree with; medium = a reasonable default that "
        "could plausibly differ; low = a genuine guess with little basis in the syllabus.\n\n"
        "Field rules:\n"
        '- "provenance" is EXACTLY one of "source_backed" or "ai_inferred" — never free text.\n'
        '- each "difficulty_notes" entry has exactly the keys misconception and mitigation.\n\n'
        "Do NOT include Course, Module, LearningObjective, or Source. "
        "Do NOT reference prerequisite ids that are not in the lists above.\n\n"
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


def _cross_module_prereqs_user(cc: dict) -> str:
    course = cc.get("Course") or {}
    module_order = course.get("module_ids") or [m.get("id") for m in (cc.get("Module") or [])]
    module_titles = {m.get("id"): m.get("title", "") for m in (cc.get("Module") or [])}
    by_module: dict[str, list[dict]] = {}
    for c in (cc.get("Concept") or []):
        by_module.setdefault(c.get("module_id"), []).append(c)

    lines: list[str] = ["Concepts in teaching order:\n"]
    for mid in module_order:
        lines.append(f"Module: {mid} — {module_titles.get(mid, '')}")
        for c in by_module.get(mid, []):
            existing = c.get("prerequisite_ids") or []
            note = f"  [within-module prereqs: {existing}]" if existing else ""
            lines.append(f"  {c.get('id')}: {c.get('name')}{note}")
        lines.append("")

    return (
        "Below is the full concept list for a course, in teaching order.\n\n"
        + "\n".join(lines)
        + "Task: identify concepts in LATER modules that genuinely cannot be understood "
        "without first mastering a concept from an EARLIER module. Only add a cross-module "
        "prerequisite when the dependency is real and direct — not just thematically related.\n\n"
        "Rules:\n"
        "- Only use concept IDs exactly as they appear in the list above.\n"
        "- Only add prerequisites from modules that appear EARLIER in the list.\n"
        "- Do not repeat within-module prerequisites already listed above.\n"
        "- Omit a concept entirely if it needs no new cross-module prerequisites.\n\n"
        'Return ONLY a JSON object: {"updates": [{"id": "<concept_id>", '
        '"add_prerequisites": ["<earlier_concept_id>", ...]}, ...]}\n'
        'If nothing to add, return: {"updates": []}'
    )


def generate_cross_module_prerequisites(cc: dict, prompt_text: str, llm: LLMClient) -> list[dict]:
    """One LLM call that wires cross-module prerequisite links after parallel assembly."""
    user = _cross_module_prereqs_user(cc)
    result = complete_json(llm, prompt_text, user)
    return result.get("updates") or []


def apply_cross_module_prerequisites(cc: dict, updates: list[dict]) -> int:
    """Apply cross-module prerequisite updates to the CC in-place.

    Returns the number of concepts updated. Only adds IDs that exist, are not
    already present, and come from an earlier module — guards against model errors.
    """
    concept_index = {c.get("id"): c for c in (cc.get("Concept") or []) if isinstance(c, dict)}
    all_ids = set(concept_index.keys())
    module_order = {
        mid: i for i, mid in
        enumerate((cc.get("Course") or {}).get("module_ids") or [])
    }

    def mod_idx(cid: str) -> int:
        c = concept_index.get(cid)
        return module_order.get((c or {}).get("module_id"), -1) if c else -1

    updated = 0
    for entry in (updates or []):
        if not isinstance(entry, dict):
            continue
        cid = entry.get("id")
        if cid not in concept_index:
            continue
        concept = concept_index[cid]
        existing = set(concept.get("prerequisite_ids") or [])
        ci = mod_idx(cid)
        to_add = [
            p for p in (entry.get("add_prerequisites") or [])
            if p in all_ids and p not in existing and p != cid and 0 <= mod_idx(p) < ci
        ]
        if to_add:
            concept["prerequisite_ids"] = sorted(existing) + to_add
            updated += 1
    return updated


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
    }
    assumptions = list(outline.get("assumptions") or [])

    for res in module_results:
        cc["Concept"].extend(res.get("Concept") or [])
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
