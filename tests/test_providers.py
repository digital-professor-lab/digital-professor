"""Provider profiles: Claude through the OpenAI-compatible endpoint, per-provider endpoints."""

from __future__ import annotations

from digital_professor.providers import (OpenAICompatibleProvider, ProviderConfiguration, configuration_for_provider,
                                         fixed_temperature, provider_catalog)


def test_claude_profile_uses_its_own_key_and_endpoint() -> None:
    catalog = {item["id"]: item for item in provider_catalog()}
    assert catalog["anthropic"]["api_key_env"] == "ANTHROPIC_API_KEY"
    assert catalog["anthropic"]["default_base_url"] == "https://api.anthropic.com/v1/"


def test_a_provider_endpoint_can_be_overridden_per_provider(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://deepseek.example.internal/v1")
    config = configuration_for_provider(provider="deepseek", model="deepseek-chat")
    assert config.base_url == "https://deepseek.example.internal/v1"
    assert configuration_for_provider(provider="openrouter", model="m").base_url == "https://openrouter.ai/api/v1"


def test_no_temperature_is_sent_to_claude_models() -> None:
    sent: list[dict] = []

    class Completions:
        def create(self, **kwargs):
            sent.append(kwargs)
            message = type("M", (), {"content": "ok"})()
            usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()
            return type("R", (), {"choices": [type("C", (), {"message": message})()], "usage": usage})()

    client = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})()
    for model in ("claude-sonnet-5-5", "deepseek-chat"):
        provider = OpenAICompatibleProvider(ProviderConfiguration("x", model, None, "X_KEY", None, None))
        provider._client = lambda: client          # type: ignore[method-assign]
        provider.generate(system="s", messages=[{"role": "user", "content": "hi"}])
    assert "temperature" not in sent[0] and sent[1]["temperature"] == 0.2
    assert fixed_temperature("anthropic/claude-opus-5.5") and not fixed_temperature("deepseek-chat")
