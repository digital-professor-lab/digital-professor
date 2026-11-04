"""Minimal chat-model adapters with tool calling. No third-party dependencies.

* `OpenAICompatibleLLM` – any OpenAI-style /chat/completions endpoint with `tools` (DeepSeek, Gemini's
  OpenAI-compatible endpoint, Kimi, OpenAI). Keys come from the environment only; never hard-code them.
* `ScriptedLLM` – replays scripted turns; used by tests and by the offline demo.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

# Model names are defaults only; override with <PROVIDER>_MODEL. Check them against the provider's
# current model list before running (Week 1 prices and model names are historical).
PROVIDERS = {
    "deepseek": {"base_url": "https://api.deepseek.com", "key_env": "DEEPSEEK_API_KEY",
                 "model_env": "DEEPSEEK_MODEL", "model": "deepseek-chat"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key_env": "GEMINI_API_KEY",
               "model_env": "GEMINI_MODEL", "model": "gemini-3.6-flash"},
    "kimi": {"base_url": "https://api.moonshot.ai/v1", "key_env": "MOONSHOT_API_KEY",
             "model_env": "KIMI_MODEL", "model": "kimi-k2.6"},
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY",
               "model_env": "OPENAI_MODEL", "model": ""},
}


class LLMError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, tool_choice_unsupported: bool = False):
        super().__init__(message)
        self.status, self.tool_choice_unsupported = status, tool_choice_unsupported


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Any            # parsed JSON (dict) or the raw string if parsing failed


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    raw: Any = None


class OpenAICompatibleLLM:
    def __init__(self, provider: str = "deepseek", *, model: str | None = None, timeout: float = 60.0,
                 temperature: float = 0.2) -> None:
        if provider not in PROVIDERS:
            raise LLMError(f"unknown provider {provider}; choose {', '.join(PROVIDERS)}")
        spec = PROVIDERS[provider]
        self.provider, self.base_url = provider, os.environ.get(f"{provider.upper()}_BASE_URL", spec["base_url"])
        self.api_key = os.environ.get(spec["key_env"], "")
        if not self.api_key:
            raise LLMError(f"{spec['key_env']} is not set in the environment")
        self.model = model or os.environ.get(spec["model_env"]) or spec["model"]
        if not self.model:
            raise LLMError(f"set {spec['model_env']} to choose a model")
        self.timeout, self.temperature = timeout, temperature

    def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None,
             tool_choice: str | None = None) -> LLMResponse:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": self.temperature}
        if tools:
            body["tools"] = tools
            if tool_choice:
                body["tool_choice"] = tool_choice
        request = urllib.request.Request(f"{self.base_url.rstrip('/')}/chat/completions",
                                         data=json.dumps(body).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": f"Bearer {self.api_key}"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")[:500]
                if error.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                unsupported = error.code == 400 and "tool_choice" in detail
                raise LLMError(f"{self.provider} HTTP {error.code}: {detail}", status=error.code,
                               tool_choice_unsupported=unsupported) from error
            except urllib.error.URLError as error:
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                raise LLMError(f"{self.provider} unreachable: {error}") from error
        message = data["choices"][0]["message"]
        calls = []
        for call in message.get("tool_calls") or []:
            raw = call["function"].get("arguments") or "{}"
            try:
                parsed: Any = json.loads(raw)
            except json.JSONDecodeError:
                parsed = raw
            calls.append(ToolCall(call.get("id") or f"call_{len(calls)}", call["function"]["name"], parsed))
        return LLMResponse(message.get("content"), calls, data.get("usage") or {}, data)


class ScriptedLLM:
    """Replays a list of steps. A step is an LLMResponse or a function(messages, tools, tool_choice) -> LLMResponse."""

    def __init__(self, steps: list[LLMResponse | Callable[..., LLMResponse]], *, honors_required: bool = True) -> None:
        self.steps = list(steps)
        self.calls: list[dict[str, Any]] = []
        self.honors_required = honors_required

    def chat(self, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None,
             tool_choice: str | None = None) -> LLMResponse:
        if tool_choice == "required" and not self.honors_required:
            raise LLMError("HTTP 400: tool_choice 'required' is not supported", status=400, tool_choice_unsupported=True)
        self.calls.append({"messages": json.loads(json.dumps(messages)), "tools": tools, "tool_choice": tool_choice})
        if not self.steps:
            raise LLMError("ScriptedLLM has no more steps")
        step = self.steps.pop(0)
        return step(messages, tools, tool_choice) if callable(step) else step


def tool_call(arguments: dict[str, Any], name: str = "search_course_materials", call_id: str = "call_1") -> LLMResponse:
    return LLMResponse(None, [ToolCall(call_id, name, arguments)])


def answer(text: str) -> LLMResponse:
    return LLMResponse(text)
