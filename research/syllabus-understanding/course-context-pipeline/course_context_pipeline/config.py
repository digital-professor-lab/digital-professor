"""Configuration for the Stage A pipeline.

Everything is configurable — syllabus/prompt/output paths and the LLM
(provider base_url, model, key) — via (in increasing precedence):
defaults  <  config YAML  <  environment variables  <  CLI overrides.

Secrets (API keys) are never stored in the YAML: give the name of an env var
with `api_key_env`, or (for keyless local Ollama) a literal `api_key`.
"""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field, fields
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None


def find_repo_root(start: pathlib.Path | None = None) -> pathlib.Path:
    """Walk up from this file to the directory that contains `.git`."""
    p = (start or pathlib.Path(__file__)).resolve()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return pathlib.Path.cwd()


REPO_ROOT = find_repo_root()
_PIPE_DIR = "research/syllabus-understanding/course-context-pipeline"


@dataclass
class LLMConfig:
    """Any OpenAI-compatible chat endpoint. Default = local Ollama (free)."""
    base_url: str = "http://localhost:11434/v1"   # Ollama's OpenAI-compatible API
    model: str = "qwen3:8b"
    api_key: str = "ollama"                        # literal fallback (Ollama ignores it)
    api_key_env: str | None = None                 # if set, read the key from this env var
    temperature: float = 0.2
    max_tokens: int = 16000
    timeout: float = 900.0
    json_mode: bool = False                        # ask for response_format=json_object when supported
    num_ctx: int | None = 32768                    # Ollama context window (ignored by hosted APIs)

    def resolve_key(self) -> str:
        if self.api_key_env:
            return os.environ.get(self.api_key_env) or self.api_key
        return self.api_key


@dataclass
class Config:
    syllabus_path: pathlib.Path = REPO_ROOT / "research/syllabus-understanding/syllabus-examples/110.106CalculusISyllabus.pdf"
    prompt_path: pathlib.Path = REPO_ROOT / "research/syllabus-understanding/design-example/syllabus-to-json-prompt.md"
    output_path: pathlib.Path = REPO_ROOT / f"{_PIPE_DIR}/output/calc1.course-context.generated.json"
    from_json: pathlib.Path | None = None          # skip the LLM and load this file instead
    max_attempts: int = 2                          # regenerate-on-error loop (Phase 2 plugs in the real validator)
    strategy: str = "single"                       # "single" (one pass) or "by_module" (chunked, per-module)
    llm: LLMConfig = field(default_factory=LLMConfig)


def _resolve_path(value: Any, base: pathlib.Path) -> pathlib.Path | None:
    if value in (None, ""):
        return None
    p = pathlib.Path(value).expanduser()
    return p if p.is_absolute() else (base / p)


def _only_known(cls, data: dict) -> dict:
    known = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in known}


def load_config(config_file: str | os.PathLike | None = None,
                overrides: dict | None = None) -> Config:
    """Build a Config from defaults + YAML + env + CLI overrides."""
    data: dict = {}
    if config_file:
        cf = _resolve_path(config_file, pathlib.Path.cwd())
        if cf and cf.exists():
            if not yaml:
                raise RuntimeError("PyYAML is not installed; cannot read a config file.")
            data = yaml.safe_load(cf.read_text(encoding="utf-8")) or {}

    overrides = {k: v for k, v in (overrides or {}).items() if v is not None}

    # --- LLM block: defaults < yaml.llm < env < cli ---
    llm_data = dict(_only_known(LLMConfig, data.get("llm") or {}))
    _env_into(llm_data, {
        "base_url": "COURSE_CONTEXT_BASE_URL",
        "model": ["COURSE_CONTEXT_MODEL", "OPENAI_MODEL"],
        "api_key_env": "COURSE_CONTEXT_API_KEY_ENV",
    })
    for k in ("base_url", "model", "api_key", "api_key_env", "temperature",
              "max_tokens", "json_mode", "num_ctx"):
        if k in overrides:
            llm_data[k] = overrides[k]
    llm = LLMConfig(**llm_data)

    # --- top-level paths & options ---
    # CLI paths resolve against the current dir; YAML paths against the repo root.
    def pick_path(key, default_abs):
        if key in overrides and overrides[key] is not None:
            return _resolve_path(overrides[key], pathlib.Path.cwd())
        if data.get(key) is not None:
            return _resolve_path(data[key], REPO_ROOT)
        return default_abs

    cfg = Config(
        syllabus_path=pick_path("syllabus_path", Config.syllabus_path),
        prompt_path=pick_path("prompt_path", Config.prompt_path),
        output_path=pick_path("output_path", Config.output_path),
        from_json=pick_path("from_json", None),
        max_attempts=int(overrides.get("max_attempts") or data.get("max_attempts") or Config.max_attempts),
        strategy=(overrides.get("strategy") or data.get("strategy") or Config.strategy),
        llm=llm,
    )
    return cfg


def _env_into(d: dict, mapping: dict[str, str | list[str]]) -> None:
    """Fill d[key] from the first present env var, if d doesn't already set it."""
    for key, env_names in mapping.items():
        if key in d:
            continue
        for name in ([env_names] if isinstance(env_names, str) else env_names):
            val = os.environ.get(name)
            if val:
                d[key] = val
                break
