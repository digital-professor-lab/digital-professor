"""Minimal structural sanity check for Stage A (Phase 1 placeholder).

This is intentionally tiny — just enough to drive the regenerate-on-error loop.
The full conformance validator (V-01..V-10) from
course-context.validation-and-flagging.md is Phase 2 and will replace this.
"""
from __future__ import annotations

ARRAYS = ["Module", "Concept", "LearningObjective", "Source"]


def basic_errors(cc: object) -> list[str]:
    """Return a list of structural problems (empty list = looks OK)."""
    errors: list[str] = []
    if not isinstance(cc, dict):
        return ["top level is not a JSON object"]

    if "course_context_schema_version" not in cc:
        errors.append("missing top-level key: course_context_schema_version")
    if not isinstance(cc.get("Course"), dict):
        errors.append("missing or non-object top-level key: Course")

    for k in ARRAYS:
        if not isinstance(cc.get(k), list):
            errors.append(f"missing or non-array top-level key: {k}")

    if isinstance(cc.get("Module"), list) and not cc["Module"]:
        errors.append("at least one Module is required")
    if isinstance(cc.get("Concept"), list) and not cc["Concept"]:
        errors.append("at least one Concept is required")

    return errors


def counts(cc: dict) -> dict[str, int]:
    return {k: len(cc.get(k, []) or []) for k in ARRAYS} | {
        "assumptions": len(cc.get("assumptions", []) or [])
    }
