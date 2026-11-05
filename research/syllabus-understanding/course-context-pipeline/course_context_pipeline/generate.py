"""Step 2 of Stage A — generate: syllabus text -> CourseContext JSON (one LLM pass).

Reuses the existing syllabus-to-json prompt (design-example/syllabus-to-json-prompt.md)
as the system instruction, per course-context.md §2.2.
"""
from __future__ import annotations

import json
import pathlib

from .llm import LLMClient, extract_json_text


class GenerationError(ValueError):
    """Raised when a generation pass can't be parsed. Carries the raw text."""
    def __init__(self, message: str, raw: str = "", json_text: str = ""):
        super().__init__(message)
        self.raw = raw
        self.json_text = json_text


def read_prompt(path: str | pathlib.Path) -> str:
    p = pathlib.Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Prompt not found: {p}")
    return p.read_text(encoding="utf-8")


def complete_json(llm: LLMClient, system: str, user: str) -> dict:
    """Run one LLM call and parse its reply as a single JSON object.

    Shared by the single-pass generator and the per-module generator.
    Raises GenerationError (carrying the raw model output) if it can't be parsed.
    """
    raw = llm.complete(system=system, user=user)
    try:
        json_text = extract_json_text(raw)
    except ValueError as e:
        raise GenerationError(f"No JSON object in model output: {e}", raw=raw) from e

    # strict=False tolerates raw control characters in strings (common with LLMs
    # emitting math / multi-line text). Structural validity is checked next.
    try:
        return json.loads(json_text, strict=False)
    except json.JSONDecodeError as e:
        raise GenerationError(f"Model output was not valid JSON: {e}",
                              raw=raw, json_text=json_text) from e


def generate_course_context(syllabus_text: str, prompt_text: str, llm: LLMClient) -> dict:
    """One generation pass (whole file at once). Returns the parsed CourseContext dict.

    Raises GenerationError (carrying the raw model output) if it can't be parsed.
    """
    user = (
        "Here is the course syllabus. Read it fully, then output ONLY the JSON "
        "object described above — no prose before or after.\n\n"
        "=== SYLLABUS START ===\n"
        f"{syllabus_text}\n"
        "=== SYLLABUS END ==="
    )
    return complete_json(llm, prompt_text, user)
