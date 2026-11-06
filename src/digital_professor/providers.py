"""Provider-neutral settings and OpenAI-compatible API boundary."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderConfiguration:
    provider: str
    model: str
    base_url: str | None
    api_key_env: str
    input_cost_per_million: float | None
    output_cost_per_million: float | None

    @classmethod
    def from_environment(cls) -> "ProviderConfiguration":
        return cls(
            provider=os.getenv("DIGITAL_PROFESSOR_PROVIDER", "openai"),
            model=os.getenv("DIGITAL_PROFESSOR_MODEL", "gpt-4.1-mini"),
            base_url=os.getenv("DIGITAL_PROFESSOR_BASE_URL") or None,
            api_key_env=os.getenv("DIGITAL_PROFESSOR_API_KEY_ENV", "OPENAI_API_KEY"),
            input_cost_per_million=_optional_float(
                os.getenv("DIGITAL_PROFESSOR_INPUT_COST_PER_MILLION")
            ),
            output_cost_per_million=_optional_float(
                os.getenv("DIGITAL_PROFESSOR_OUTPUT_COST_PER_MILLION")
            ),
        )

    @property
    def api_key(self) -> str | None:
        return os.getenv(self.api_key_env)


@dataclass(frozen=True, slots=True)
class GenerationResult:
    text: str
    model: str
    latency_ms: int
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None = None


class OpenAICompatibleProvider:
    def __init__(self, config: ProviderConfiguration) -> None:
        self.config = config

    def _client(self):
        from openai import OpenAI

        if not self.config.api_key:
            raise RuntimeError(
                f"No key found in {self.config.api_key_env}; add it to .env and restart the server."
            )
        return OpenAI(api_key=self.config.api_key, base_url=self.config.base_url, timeout=25)

    def test_connection(self) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            models = self._client().models.list()
            ids = [item.id for item in models.data[:20]]
            return {
                "ok": True,
                "message": "Provider authentication succeeded.",
                "model_configured": self.config.model,
                "models": ids,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "pricing_configured": self.config.input_cost_per_million is not None
                and self.config.output_cost_per_million is not None,
            }
        except Exception as error:
            return {
                "ok": False,
                "message": str(error),
                "model_configured": self.config.model,
                "models": [],
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "pricing_configured": self.config.input_cost_per_million is not None
                and self.config.output_cost_per_million is not None,
            }

    def generate(self, *, system: str, messages: list[dict[str, str]]) -> GenerationResult:
        started = time.perf_counter()
        response = self._client().chat.completions.create(
            model=self.config.model,
            messages=[{"role": "system", "content": system}, *messages],
            temperature=0.2,
        )
        usage = response.usage
        input_tokens = getattr(usage, "prompt_tokens", None)
        output_tokens = getattr(usage, "completion_tokens", None)
        return GenerationResult(
            text=response.choices[0].message.content or "",
            model=self.config.model,
            latency_ms=round((time.perf_counter() - started) * 1000),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=_estimate_cost(
                input_tokens,
                output_tokens,
                self.config.input_cost_per_million,
                self.config.output_cost_per_million,
            ),
        )


def _optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        number = float(value)
    except ValueError as error:
        raise ValueError(f"Invalid provider pricing value: {value!r}") from error
    if number < 0:
        raise ValueError("Provider pricing values cannot be negative.")
    return number


def _estimate_cost(
    input_tokens: int | None,
    output_tokens: int | None,
    input_rate: float | None,
    output_rate: float | None,
) -> float | None:
    if None in {input_tokens, output_tokens, input_rate, output_rate}:
        return None
    return round(
        (input_tokens or 0) * (input_rate or 0) / 1_000_000
        + (output_tokens or 0) * (output_rate or 0) / 1_000_000,
        8,
    )
