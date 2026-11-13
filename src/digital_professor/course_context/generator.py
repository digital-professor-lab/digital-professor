"""Generate a structured CourseContext from syllabus text using an LLM."""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PROMPT_PATH = (
    _REPO_ROOT
    / "research/syllabus-understanding/design-example/syllabus-to-json-prompt.md"
)
_PIPELINE_PATH = str(
    _REPO_ROOT / "research/syllabus-understanding/course-context-pipeline"
)


def _ensure_pipeline_path() -> None:
    if _PIPELINE_PATH not in sys.path:
        sys.path.insert(0, _PIPELINE_PATH)


class CourseContextGenerationError(ValueError):
    pass


class CourseContextGenerator:
    """By-module LLM generation: outline + one call per module -> assembled CourseContext.

    Keeps every individual LLM response small so models with modest output caps
    (e.g. deepseek-chat ~8K tokens) never truncate mid-JSON.
    """

    def __init__(
        self,
        *,
        base_url: str | None,
        model: str,
        api_key: str,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = base_url
        self._model = model
        self._api_key = api_key
        self._timeout = timeout

    def generate(
        self,
        syllabus_text: str,
        prompt_path: Path | None = None,
    ) -> dict[str, Any]:
        _ensure_pipeline_path()

        from course_context_pipeline.config import LLMConfig
        from course_context_pipeline.generate import GenerationError, read_prompt
        from course_context_pipeline.generate_by_module import (
            apply_cross_module_prerequisites,
            assemble,
            generate_cross_module_prerequisites,
            generate_module,
            generate_outline,
        )
        from course_context_pipeline.llm import LLMClient

        prompt = read_prompt(prompt_path or _DEFAULT_PROMPT_PATH)
        llm = LLMClient(
            LLMConfig(
                base_url=self._base_url or "https://api.openai.com/v1",
                model=self._model,
                api_key=self._api_key,
                timeout=self._timeout,
                temperature=0.2,
            )
        )

        _log.info("CourseContext: generating outline…")
        try:
            outline = generate_outline(syllabus_text, prompt, llm)
        except (GenerationError, Exception) as exc:
            raise CourseContextGenerationError(
                f"Outline generation failed: {exc}"
            ) from exc

        course = outline.get("Course") or {}
        modules = outline.get("Module") or []
        if not modules:
            raise CourseContextGenerationError("Outline produced no Module array")
        _log.info("CourseContext: outline done — %d module(s)", len(modules))

        total = len(modules)
        _log.info("CourseContext: generating %d module(s) in parallel…", total)

        def _run_module(idx: int, module: dict) -> tuple[int, dict]:
            _log.info("CourseContext: module %d/%d started — %s", idx, total, module.get("title", module.get("id")))
            res = generate_module(syllabus_text, prompt, course, modules, module, [], llm)
            _log.info("CourseContext: module %d/%d done — %s", idx, total, module.get("title", module.get("id")))
            return idx, res

        results_by_index: dict[int, dict] = {}
        with ThreadPoolExecutor(max_workers=total) as executor:
            futures = {executor.submit(_run_module, i, m): m for i, m in enumerate(modules, 1)}
            for future in as_completed(futures):
                module = futures[future]
                try:
                    idx, res = future.result()
                    results_by_index[idx] = res
                except (GenerationError, Exception) as exc:
                    _log.warning("Module %r failed: %s", module.get("id"), exc, exc_info=True)

        results = [results_by_index[i] for i in range(1, total + 1) if i in results_by_index]

        cc = assemble(outline, results)
        if not cc.get("Concept"):
            raise CourseContextGenerationError("Assembly produced no Concepts")
        _strip_dangling_prerequisites(cc)

        _log.info("CourseContext: adding cross-module prerequisites…")
        try:
            updates = generate_cross_module_prerequisites(cc, prompt, llm)
            n = apply_cross_module_prerequisites(cc, updates)
            _log.info("CourseContext: cross-module prerequisites added for %d concept(s)", n)
        except (GenerationError, Exception) as exc:
            _log.warning("Cross-module prerequisites step failed (skipped): %s", exc)

        _log.info("CourseContext: done — %d concept(s) across %d module(s)", len(cc["Concept"]), len(modules))
        return cc


def _strip_dangling_prerequisites(cc: dict) -> None:
    """Remove prerequisite_ids that don't point to an existing concept.

    With parallel module generation each call has no prior concept IDs, so the
    model guesses cross-module IDs from naming conventions and often gets the
    slug wrong. Strip the bad references; within-module prereqs are unaffected.
    """
    known = {c.get("id") for c in (cc.get("Concept") or []) if c.get("id")}
    for concept in (cc.get("Concept") or []):
        if not isinstance(concept, dict):
            continue
        prereqs = concept.get("prerequisite_ids") or []
        concept["prerequisite_ids"] = [p for p in prereqs if p in known]


def validate_and_flag(cc: dict) -> tuple[str, dict | None]:
    """Validate a CourseContext dict and produce a review report.

    Returns (status, review_report):
      - ("validation_failed", None)   — structural errors; CC should not be used
      - ("review_required", report)   — valid but has AI-inferred fields to check
      - ("validated", report)         — valid with no flagged items
    """
    _ensure_pipeline_path()

    from course_context_pipeline.flag import flag  # noqa: PLC0415
    from course_context_pipeline.validate import error_messages, validate  # noqa: PLC0415

    findings = validate(cc)
    errors = error_messages(findings)
    if errors:
        _log.warning("CourseContext validation failed: %s", "; ".join(errors))
        return "validation_failed", None

    source_sha256 = hashlib.sha256(
        json.dumps(cc, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    review = flag(cc, source_sha256=source_sha256)
    has_items = (
        review["summary"]["check_first"] > 0
        or review["summary"]["global_notes"] > 0
    )
    return ("review_required" if has_items else "validated"), review
