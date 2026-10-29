"""Provider-agnostic LLM client.

Wraps the OpenAI Python SDK pointed at any OpenAI-compatible endpoint:
  - Ollama (local, free):   base_url=http://localhost:11434/v1, model=qwen3:8b
  - OpenAI:                 base_url=https://api.openai.com/v1, model=gpt-4o
  - OpenRouter / DeepSeek / JHU Gateway: just change base_url + model + key.

Only base_url / model / key change between providers — never the calling code.
"""
from __future__ import annotations

import re

from .config import LLMConfig


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        from openai import OpenAI

        self.cfg = cfg
        self._client = OpenAI(
            base_url=cfg.base_url,
            api_key=cfg.resolve_key() or "not-needed",
            timeout=cfg.timeout,
        )

    def complete(self, system: str, user: str) -> str:
        """One chat completion. Returns the raw assistant text."""
        kwargs: dict = dict(
            model=self.cfg.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.cfg.temperature,
            max_tokens=self.cfg.max_tokens,
        )
        # Ollama-specific knobs ride along in extra_body and are ignored by hosted APIs.
        if self.cfg.num_ctx:
            kwargs["extra_body"] = {"options": {"num_ctx": self.cfg.num_ctx}}
        if self.cfg.json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception:
            # Some providers reject response_format / extra_body; retry without them.
            kwargs.pop("response_format", None)
            kwargs.pop("extra_body", None)
            resp = self._client.chat.completions.create(**kwargs)

        return resp.choices[0].message.content or ""


# ---- robust JSON extraction from model text --------------------------------

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json_text(text: str) -> str:
    """Pull the JSON object out of a model response.

    Handles <think>…</think> preambles (e.g. Qwen3), ```json fences, and chatty
    text around the object, by returning the outermost balanced {...} block.
    """
    t = _THINK.sub("", text).strip()

    m = _FENCE.search(t)
    if m:
        t = m.group(1).strip()

    start = t.find("{")
    if start == -1:
        raise ValueError("No JSON object found in model output.")

    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return t[start:i + 1]
    # unbalanced — return from first brace and let json.loads report the error
    return t[start:]
