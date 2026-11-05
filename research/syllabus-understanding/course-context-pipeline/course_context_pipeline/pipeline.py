"""Stage A orchestration: intake -> generate -> (basic check / regenerate) -> write.

Validate (full) and Flag are Phase 2; the regenerate-on-error loop and the
hook points are already here so they drop straight in.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

from .config import Config
from .generate import generate_course_context, read_prompt
from .generate_by_module import assemble, generate_module, generate_outline
from .intake import load_syllabus
from .llm import LLMClient
from .validate_basic import basic_errors, counts


@dataclass
class StageAResult:
    course_context: dict
    output_path: pathlib.Path
    attempts: int
    errors: list[str]           # structural errors still present on the final attempt
    source: str                 # "llm" or "from_json"


def _log(msg: str, quiet: bool) -> None:
    if not quiet:
        print(msg, flush=True)


def run_stage_a(cfg: Config, quiet: bool = False) -> StageAResult:
    # --- Path A: skip the LLM, load a pre-generated file (free dev / Phase 2-3) ---
    if cfg.from_json:
        _log(f"[intake] loading pre-generated CourseContext: {cfg.from_json}", quiet)
        cc = json.loads(pathlib.Path(cfg.from_json).read_text(encoding="utf-8"))
        errors = basic_errors(cc)
        out = _write(cc, cfg.output_path)
        _log(f"[done] wrote {out}  records={counts(cc)}  structural_errors={len(errors)}", quiet)
        return StageAResult(cc, out, attempts=0, errors=errors, source="from_json")

    # --- Path B: generate from the syllabus ---
    _log(f"[intake] reading syllabus: {cfg.syllabus_path}", quiet)
    syllabus = load_syllabus(cfg.syllabus_path)
    _log(f"[intake] {len(syllabus):,} chars extracted", quiet)

    prompt = read_prompt(cfg.prompt_path)
    llm = LLMClient(cfg.llm)
    _log(f"[generate] provider={cfg.llm.base_url} model={cfg.llm.model} strategy={cfg.strategy}", quiet)

    if cfg.strategy == "by_module":
        cc, attempts, errors = _gen_by_module(cfg, syllabus, prompt, llm, quiet)
    else:
        cc, attempts, errors = _gen_single(cfg, syllabus, prompt, llm, quiet)

    if cc:
        out = _write(cc, cfg.output_path)
        _log(f"[done] wrote {out}", quiet)
    else:
        out = cfg.output_path
        _log("[done] no parseable CourseContext produced (see the .raw.txt dump)", quiet)
    if errors:
        _log(f"[warn] final output has {len(errors)} issue(s): {errors}", quiet)
    return StageAResult(cc, out, attempts=attempts, errors=errors, source="llm")


def _save_raw(cfg: Config, err: Exception, label: str, quiet: bool) -> None:
    """Dump the raw (unparseable) model output next to the output path."""
    raw = getattr(err, "raw", "")
    if not raw:
        return
    suffix = f".{label}.raw.txt" if label else ".raw.txt"
    raw_path = cfg.output_path.parent / (cfg.output_path.stem + suffix)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(raw, encoding="utf-8")
    _log(f"[generate] parse failed ({len(raw):,} chars); raw saved to {raw_path}", quiet)


def _attempt(fn, label: str, cfg: Config, quiet: bool):
    """Call fn() with up to max_attempts retries on a parse failure.

    Returns the parsed dict, or None if every attempt failed (raw is dumped).
    """
    for attempt in range(1, cfg.max_attempts + 1):
        try:
            return fn()
        except ValueError as e:          # GenerationError (unparseable output)
            _save_raw(cfg, e, label, quiet)
            _log(f"[generate] {label} attempt {attempt}/{cfg.max_attempts} failed: {e}", quiet)
    return None


def _gen_single(cfg: Config, syllabus: str, prompt: str, llm: LLMClient, quiet: bool):
    """One LLM call for the whole file, retried on parse/structure failure."""
    cc: dict = {}
    errors: list[str] = ["no attempt made"]
    attempt = 0
    for attempt in range(1, cfg.max_attempts + 1):
        _log(f"[generate] attempt {attempt}/{cfg.max_attempts} …", quiet)
        try:
            cc = generate_course_context(syllabus, prompt, llm)
        except ValueError as e:
            errors = [str(e)]
            _save_raw(cfg, e, "", quiet)
            continue
        errors = basic_errors(cc)          # Phase 2: swap for the full validator
        if not errors:
            _log(f"[validate] basic structural check passed  records={counts(cc)}", quiet)
            break
        _log(f"[validate] {len(errors)} structural issue(s); regenerating", quiet)
    return cc, attempt, errors


def _gen_by_module(cfg: Config, syllabus: str, prompt: str, llm: LLMClient, quiet: bool):
    """Outline first, then one call per module, assembled into one CourseContext.

    Keeps every response small so a model with a modest output cap (e.g.
    deepseek-chat ~8K tokens) never truncates. Concept ids are fed forward so
    later modules can reference earlier concepts as prerequisites.
    """
    outline = _attempt(lambda: generate_outline(syllabus, prompt, llm), "outline", cfg, quiet)
    if not outline:
        return {}, 1, ["outline generation failed to parse"]
    course = outline.get("Course") or {}
    modules = outline.get("Module") or []
    if not modules:
        return {}, 1, ["outline produced no Module array"]
    _log(f"[generate] outline: course={course.get('id')!r}  modules={len(modules)}", quiet)

    results: list[dict] = []
    prior_ids: list[str] = []
    calls = 1
    for i, m in enumerate(modules, 1):
        _log(f"[generate] module {i}/{len(modules)}: {m.get('title')} …", quiet)
        res = _attempt(
            lambda m=m: generate_module(syllabus, prompt, course, modules, m, prior_ids, llm),
            f"module-{i:02d}", cfg, quiet,
        )
        calls += 1
        if not res:
            _log(f"[generate] module {i} failed after {cfg.max_attempts} attempts; skipping", quiet)
            continue
        results.append(res)
        prior_ids.extend(c.get("id") for c in (res.get("Concept") or []) if c.get("id"))

    cc = assemble(outline, results)
    errors = basic_errors(cc)
    if errors:
        _log(f"[validate] {len(errors)} structural issue(s) after assembly: {errors}", quiet)
    else:
        _log(f"[validate] basic structural check passed  records={counts(cc)}", quiet)
    return cc, calls, errors


def _write(cc: dict, path: pathlib.Path) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
