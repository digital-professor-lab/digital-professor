"""CLI for the Stage A pipeline.

Examples
--------
# Local Ollama (free), full run from the Calc I syllabus:
    python -m course_context_pipeline.cli

# Dev with no LLM — just re-emit a pre-generated CourseContext:
    python -m course_context_pipeline.cli --from-json specs/examples/calc1.course-context.json

# Just show the extracted syllabus + prompt sizes, don't call the model:
    python -m course_context_pipeline.cli --dry-run

# Switch provider/model without touching code:
    python -m course_context_pipeline.cli --base-url https://api.openai.com/v1 \
        --model gpt-4o --api-key-env OPENAI_API_KEY
"""
from __future__ import annotations

import argparse
import sys

import json
import pathlib

from .config import load_config
from .flag import flag, format_report as format_flag, sha256_of
from .generate import read_prompt
from .intake import load_syllabus
from .pipeline import run_stage_a
from .validate import error_findings, format_report as format_validation, validate


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="course-context-stage-a",
                                description="Generate a CourseContext JSON from a syllabus (Stage A).")
    p.add_argument("--config", help="path to a YAML config file")
    p.add_argument("--syllabus", dest="syllabus_path", help="syllabus file (.pdf/.txt/.md)")
    p.add_argument("--prompt", dest="prompt_path", help="syllabus-to-json prompt file")
    p.add_argument("--out", dest="output_path", help="output CourseContext JSON path")
    p.add_argument("--from-json", dest="from_json", help="skip the LLM; re-emit this CourseContext file")
    p.add_argument("--max-attempts", dest="max_attempts", type=int, help="regenerate-on-error attempts")
    p.add_argument("--strategy", choices=["single", "by_module"],
                   help="generation strategy (default: single)")
    p.add_argument("--by-module", dest="strategy", action="store_const", const="by_module",
                   help="shortcut for --strategy by_module: outline + one call per module, "
                        "then assemble (avoids output-length truncation on small-cap models)")
    # LLM overrides (provider-agnostic)
    p.add_argument("--base-url", dest="base_url", help="OpenAI-compatible base URL (Ollama default)")
    p.add_argument("--model", dest="model", help="model name")
    p.add_argument("--api-key-env", dest="api_key_env", help="env var holding the API key")
    p.add_argument("--temperature", dest="temperature", type=float)
    p.add_argument("--max-tokens", dest="max_tokens", type=int)
    p.add_argument("--json-mode", dest="json_mode", action="store_true", default=None,
                   help="request response_format=json_object (provider must support it)")
    p.add_argument("--dry-run", action="store_true", help="load syllabus + prompt, print sizes, don't call the model")
    p.add_argument("--validate-only", action="store_true",
                   help="validate + flag an existing file (requires --from-json); prints the "
                        "report, writes nothing, exits 1 on any error")
    p.add_argument("--quiet", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # load a local .env if present (keeps keys out of the shell history)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    overrides = {k: v for k, v in vars(args).items()
                 if k not in ("config", "dry_run", "quiet", "validate_only") and v is not None}
    cfg = load_config(config_file=args.config, overrides=overrides)

    if args.validate_only:
        return _validate_only(cfg)

    if args.dry_run:
        syllabus = load_syllabus(cfg.syllabus_path)
        prompt = read_prompt(cfg.prompt_path)
        print(f"syllabus : {cfg.syllabus_path}  ({len(syllabus):,} chars)")
        print(f"prompt   : {cfg.prompt_path}  ({len(prompt):,} chars)")
        print(f"provider : {cfg.llm.base_url}  model={cfg.llm.model}")
        print(f"output   : {cfg.output_path}")
        print("\n--- syllabus preview (first 800 chars) ---")
        print(syllabus[:800])
        return 0

    result = run_stage_a(cfg, quiet=args.quiet)
    return 1 if result.errors else 0


def _validate_only(cfg) -> int:
    """Standalone Validator + Flagger on an existing file (no writes)."""
    if not cfg.from_json:
        print("--validate-only requires --from-json <course-context.json>")
        return 2
    path = pathlib.Path(cfg.from_json)
    text = path.read_text(encoding="utf-8")
    cc = json.loads(text)
    findings = validate(cc)
    print(format_validation(findings, cc, path.name))
    errs = error_findings(findings)
    if not errs:
        print()
        print(format_flag(flag(cc, source_sha256=sha256_of(text))))
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
