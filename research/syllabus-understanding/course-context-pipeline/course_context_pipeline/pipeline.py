"""Stage A orchestration: intake -> generate -> validate -> (regenerate) -> write -> flag.

Steps 3-4 (Validate, Flag) follow course-context.validation-and-flagging.md:
the Validator gates publication (errors block, warnings don't); a clean file is
then passed to the Review Flagger, which writes a human-review worklist.
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field

from .config import Config
from .flag import flag, sha256_of, to_json as flag_to_json
from .generate import generate_course_context, read_prompt
from .generate_by_module import assemble, generate_module, generate_outline
from .intake import load_syllabus
from .llm import LLMClient
from .validate import (Finding, counts, error_messages, format_report,
                       summary_line, validate)


@dataclass
class StageAResult:
    course_context: dict
    output_path: pathlib.Path
    attempts: int
    errors: list[str]                       # validator ERROR lines on the final file
    source: str                             # "llm" or "from_json"
    findings: list[Finding] = field(default_factory=list)
    review_path: pathlib.Path | None = None


def _log(msg: str, quiet: bool) -> None:
    if not quiet:
        print(msg, flush=True)


def run_stage_a(cfg: Config, quiet: bool = False) -> StageAResult:
    # --- Path A: skip the LLM, load a pre-generated file (free dev / validate-only) ---
    if cfg.from_json:
        _log(f"[intake] loading pre-generated CourseContext: {cfg.from_json}", quiet)
        cc = json.loads(pathlib.Path(cfg.from_json).read_text(encoding="utf-8"))
        findings = validate(cc)
        return _finalize(cfg, cc, findings, attempts=0, source="from_json", quiet=quiet)

    # --- Path B: generate from the syllabus ---
    _log(f"[intake] reading syllabus: {cfg.syllabus_path}", quiet)
    syllabus = load_syllabus(cfg.syllabus_path)
    _log(f"[intake] {len(syllabus):,} chars extracted", quiet)

    prompt = read_prompt(cfg.prompt_path)
    llm = LLMClient(cfg.llm)
    _log(f"[generate] provider={cfg.llm.base_url} model={cfg.llm.model} strategy={cfg.strategy}", quiet)

    if cfg.strategy == "by_module":
        cc, attempts, findings = _gen_by_module(cfg, syllabus, prompt, llm, quiet)
    else:
        cc, attempts, findings = _gen_single(cfg, syllabus, prompt, llm, quiet)

    if not cc:
        _log("[done] no parseable CourseContext produced (see the .raw.txt dump)", quiet)
        return StageAResult({}, cfg.output_path, attempts, ["no parseable output"], "llm")
    return _finalize(cfg, cc, findings, attempts=attempts, source="llm", quiet=quiet)


# --- steps 3-4: validate, write, flag ---------------------------------------

def _finalize(cfg: Config, cc: dict, findings: list[Finding], attempts: int,
              source: str, quiet: bool) -> StageAResult:
    """Validate report + write the file + (if clean) run the Flagger."""
    errors = error_messages(findings)

    # validator report (one line per finding + summary)
    for fd in findings:
        _log(f"[validate] {fd.line()}", quiet)
    _log(f"[validate] {summary_line(findings, cc, cfg.output_path.name)}", quiet)

    text = json.dumps(cc, indent=2, ensure_ascii=False) + "\n"
    out = _write_text(text, cfg.output_path)
    _log(f"[done] wrote {out}", quiet)

    review_path = None
    if errors:
        # WF-4: only a zero-error file is flagged.
        _log(f"[flag] skipped — {len(errors)} validation error(s) must be fixed first", quiet)
    else:
        report = flag(cc, source_sha256=sha256_of(text))
        review_path = cfg.output_path.parent / (cfg.output_path.stem + ".review.json")
        _write_text(flag_to_json(report), review_path)
        s = report["summary"]
        _log(f"[flag] review worklist: check_first={s['check_first']} "
             f"worth_checking={s['worth_checking']} global_notes={s['global_notes']} -> {review_path}", quiet)

    return StageAResult(cc, out, attempts, errors, source, findings, review_path)


# --- generation strategies ---------------------------------------------------

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
    """One LLM call for the whole file, regenerated while the Validator reports errors."""
    cc: dict = {}
    findings: list[Finding] = []
    attempt = 0
    for attempt in range(1, cfg.max_attempts + 1):
        _log(f"[generate] attempt {attempt}/{cfg.max_attempts} …", quiet)
        try:
            cc = generate_course_context(syllabus, prompt, llm)
        except ValueError as e:
            _save_raw(cfg, e, "", quiet)
            findings = [Finding("GEN", "error", "<file>", str(e))]
            continue
        findings = validate(cc)
        if not error_messages(findings):
            break                                  # WF-1: zero errors -> publishable
        _log(f"[generate] {len(error_messages(findings))} validation error(s); regenerating", quiet)
    return cc, attempt, findings


def _gen_by_module(cfg: Config, syllabus: str, prompt: str, llm: LLMClient, quiet: bool):
    """Outline first, then one call per module, assembled into one CourseContext.

    Keeps every response small so a model with a modest output cap (e.g.
    deepseek-chat ~8K tokens) never truncates. Concept ids are fed forward so
    later modules can reference earlier concepts as prerequisites.
    """
    outline = _attempt(lambda: generate_outline(syllabus, prompt, llm), "outline", cfg, quiet)
    if not outline:
        return {}, 1, [Finding("GEN", "error", "outline", "outline generation failed to parse")]
    course = outline.get("Course") or {}
    modules = outline.get("Module") or []
    if not modules:
        return {}, 1, [Finding("GEN", "error", "outline", "outline produced no Module array")]
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
    findings = validate(cc)
    return cc, calls, findings


def _write_text(text: str, path: pathlib.Path) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
