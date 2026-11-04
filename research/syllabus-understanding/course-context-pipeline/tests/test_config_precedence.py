"""Reviewer ask: configuration precedence (defaults < YAML < env < CLI)."""
import pytest

from course_context_pipeline import config as config_mod
from course_context_pipeline.config import load_config

needs_yaml = pytest.mark.skipif(config_mod.yaml is None, reason="PyYAML not installed")


def _clear_env(monkeypatch):
    for v in ("COURSE_CONTEXT_MODEL", "OPENAI_MODEL", "COURSE_CONTEXT_BASE_URL",
              "COURSE_CONTEXT_API_KEY_ENV"):
        monkeypatch.delenv(v, raising=False)


def test_defaults(monkeypatch):
    _clear_env(monkeypatch)
    c = load_config()
    assert c.llm.model == "qwen3:8b"
    assert c.strategy == "single"


@needs_yaml
def test_yaml_beats_default(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    f = tmp_path / "cfg.yaml"
    f.write_text("strategy: by_module\nllm:\n  model: from-yaml\n", encoding="utf-8")
    c = load_config(config_file=str(f))
    assert c.llm.model == "from-yaml"
    assert c.strategy == "by_module"


@needs_yaml
def test_env_beats_yaml(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    f = tmp_path / "cfg.yaml"
    f.write_text("llm:\n  model: from-yaml\n", encoding="utf-8")
    monkeypatch.setenv("COURSE_CONTEXT_MODEL", "from-env")
    c = load_config(config_file=str(f))
    assert c.llm.model == "from-env"


@needs_yaml
def test_cli_beats_env(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    f = tmp_path / "cfg.yaml"
    f.write_text("llm:\n  model: from-yaml\n", encoding="utf-8")
    monkeypatch.setenv("COURSE_CONTEXT_MODEL", "from-env")
    c = load_config(config_file=str(f), overrides={"model": "from-cli"})
    assert c.llm.model == "from-cli"


@needs_yaml
def test_cli_strategy_beats_yaml(tmp_path, monkeypatch):
    _clear_env(monkeypatch)
    f = tmp_path / "cfg.yaml"
    f.write_text("strategy: by_module\n", encoding="utf-8")
    c = load_config(config_file=str(f), overrides={"strategy": "single"})
    assert c.strategy == "single"
