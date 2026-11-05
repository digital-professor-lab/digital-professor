"""Small, dependency-free client for TypeSafe's Jev System One API.

Copied from the Week 5 experiment (`jev_retrieval/client.py`) so that this package does not depend on a
local folder. Requests, retries, the mock and the cache keys are unchanged; only the file locations differ.

All three access routes expose the same request shape (POST <base>/v1/systemone):
the official TypeSafe console, OpenRouter and Vercel AI Gateway. Only the base
URL, key variable and model name differ.

Every response is cached on disk, keyed by provider, model, state and questions,
so experiments can be re-run and re-scored without paying again and the exact
raw answers stay available for review.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


CACHE = Path(__file__).resolve().parents[1] / "cache"
PRICE_PER_MTOK_INPUT = 0.042  # USD; output tokens are free

# The OpenRouter and Vercel paths come from third-party setup guides (Sept 2026);
# the smoke test in this folder checks them before any experiment runs.
PROVIDERS: dict[str, dict[str, str]] = {
    "typesafe": {"base_url": "https://api.typesafe.ai", "key_env": "TYPESAFE_API_KEY",
                 "model": "jev-latest"},
    "openrouter": {"base_url": "https://openrouter.ai/api", "key_env": "OPENROUTER_API_KEY",
                   "model": "typesafe/jev-1.13"},
    "vercel": {"base_url": "https://ai-gateway.vercel.sh/typesafe", "key_env": "AI_GATEWAY_API_KEY",
               "model": "typesafe-ai/jev"},
    "mock": {"base_url": "", "key_env": "", "model": "mock-heuristic"},
}
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


class JevError(RuntimeError):
    pass


def env_file() -> Path:
    """The private .env file: JEV_ENV_FILE, or `.env` in the local Week 5 folder (WEEK5_JEV)."""
    if os.environ.get("JEV_ENV_FILE"):
        return Path(os.environ["JEV_ENV_FILE"])
    package = Path(__file__).resolve().parents[1]
    return Path(os.environ.get("WEEK5_JEV", package.parent / "week5 jev")) / ".env"


def read_local_env(path: Path | None = None) -> dict[str, str]:
    """Read KEY=VALUE lines from the private .env file. Keys in the environment take precedence."""
    path = path or env_file()
    if not path.exists():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def confirm_spend(client: "JevClient", jobs: list, assume_yes: bool = False) -> bool:
    """Show how many *new* (uncached) calls a run would make and ask before spending."""
    new = [job for job in jobs if not client.is_cached(*job)]
    tokens = sum(len(canonical(list(job))) for job in new) // 4
    print(f"{len(jobs)} Jev calls needed: {len(jobs) - len(new)} already cached (free), {len(new)} new "
          f"(about {tokens:,} input tokens, ~${tokens / 1e6 * PRICE_PER_MTOK_INPUT:.4f}).")
    if not new or client.provider == "mock" or assume_yes:
        return True
    try:
        return input("继续调用 Jev? Continue? [y/N] ").strip().lower() in {"y", "yes"}
    except EOFError:
        return False


def resolve_provider(name: str | None = None) -> str:
    local = read_local_env()
    name = name or os.environ.get("JEV_PROVIDER") or local.get("JEV_PROVIDER")
    if not name:
        for candidate in ("typesafe", "openrouter", "vercel"):
            if os.environ.get(PROVIDERS[candidate]["key_env"]) or local.get(PROVIDERS[candidate]["key_env"]):
                return candidate
        raise JevError("No Jev key found. Set OPENROUTER_API_KEY or TYPESAFE_API_KEY, or JEV_ENV_FILE (see README).")
    if name not in PROVIDERS:
        raise JevError(f"Unknown provider {name!r}; choose one of {sorted(PROVIDERS)}")
    return name


def canonical(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass
class Usage:
    calls: int = 0
    cached_calls: int = 0
    input_tokens: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, input_tokens: int, cached: bool) -> None:
        with self.lock:
            self.calls += 1
            self.cached_calls += int(cached)
            self.input_tokens += input_tokens

    @property
    def cost_usd(self) -> float:
        return self.input_tokens / 1e6 * PRICE_PER_MTOK_INPUT

    def to_dict(self) -> dict[str, Any]:
        return {"calls": self.calls, "cached_calls": self.cached_calls,
                "input_tokens": self.input_tokens,
                "cost_usd_including_cached": round(self.cost_usd, 5)}


class JevClient:
    """Thread-safe Jev client with a JSONL response cache.

    `ask(state, questions)` returns the raw `answers` mapping from the API,
    e.g. {"relevant": {"type": "noul", "noul": 0.93}}.
    """

    def __init__(self, provider: str | None = None, *, model: str | None = None,
                 cache_path: Path | None = None, timeout: float = 60.0, max_retries: int = 5,
                 workers: int = 8, cache_only: bool = False) -> None:
        self.provider = resolve_provider(provider)
        spec = PROVIDERS[self.provider]
        local = read_local_env()
        self.model = model or os.environ.get("JEV_MODEL") or local.get("JEV_MODEL") or spec["model"]
        self.base_url = spec["base_url"]
        self.api_key = ""
        if self.provider != "mock":
            self.api_key = os.environ.get(spec["key_env"]) or local.get(spec["key_env"], "")
            if not self.api_key and not cache_only:
                raise JevError(f"{spec['key_env']} is not set (environment or JEV_ENV_FILE).")
        self.timeout, self.max_retries, self.workers = timeout, max_retries, workers
        self.cache_only = cache_only
        self.cache_path = cache_path or CACHE / f"{self.provider}.jsonl"
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.usage = Usage()
        self.models_seen: set[str] = set()
        if self.cache_path.exists():
            for line in self.cache_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._cache[row["key"]] = row

    # -- public -------------------------------------------------------------
    def _key(self, state: Any, questions: dict[str, dict[str, Any]]) -> str:
        return hashlib.sha256(canonical([self.provider, self.model, state, questions]).encode()).hexdigest()

    def is_cached(self, state: Any, questions: dict[str, dict[str, Any]]) -> bool:
        with self._lock:
            return self._key(state, questions) in self._cache

    def ask(self, state: Any, questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        key = self._key(state, questions)
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            self.usage.add(hit.get("input_tokens", 0), cached=True)
            self.models_seen.add(hit.get("model", self.model))
            return hit["answers"]
        if self.cache_only:
            raise JevError("Response not in cache and cache_only=True")
        if self.provider == "mock":
            body = mock_response(state, questions)
        else:
            body = self._post({"state": state, "model": self.model, "questions": questions})
        answers = body.get("answers") or {}
        missing = set(questions) - set(answers)
        if missing:
            raise JevError(f"Response lacks answers for {sorted(missing)}: {str(body)[:300]}")
        tokens = int((body.get("usage") or {}).get("input_tokens") or 0)
        row = {"key": key, "provider": self.provider, "model": body.get("model", self.model),
               "requested_model": self.model, "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "input_tokens": tokens, "state": state, "questions": questions, "answers": answers}
        with self._lock:
            self._cache[key] = row
            with self.cache_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.usage.add(tokens, cached=False)
        self.models_seen.add(row["model"])
        return answers

    def ask_many(self, jobs: list[tuple[Any, dict[str, dict[str, Any]]]],
                 progress: Callable[[int, int], None] | None = None) -> list[dict[str, Any]]:
        results: list[dict[str, Any] | None] = [None] * len(jobs)
        done = 0

        def run(index: int) -> None:
            nonlocal done
            results[index] = self.ask(*jobs[index])
            with self._lock:
                done += 1
                if progress:
                    progress(done, len(jobs))

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            list(pool.map(run, range(len(jobs))))
        return results  # type: ignore[return-value]

    def list_models(self) -> Any:
        if self.provider == "mock":
            return {"data": [{"id": self.model}]}
        return self._request("GET", "/v1/models", None)

    # -- transport ----------------------------------------------------------
    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/systemone", payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None) -> Any:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", "replace")[:500]
                last = JevError(f"HTTP {error.code} from {self.provider}: {detail}")
                if error.code not in RETRYABLE_STATUS:
                    raise last from None
                retry_after = error.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                last = JevError(f"Network error reaching {self.provider}: {error}")
                delay = 2 ** attempt
            if attempt < self.max_retries:
                time.sleep(min(delay, 30) + random.random() * 0.25)
        raise last or JevError("Request failed")


# -- offline mock -------------------------------------------------------------
_WORD = re.compile(r"[a-z][a-z0-9]+")
_STOP = {"the", "and", "for", "with", "this", "that", "what", "which", "does", "how", "are", "is",
         "of", "in", "to", "a", "an", "course", "student", "question", "passage", "about", "from"}


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


def mock_response(state: Any, questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Deterministic word-overlap stand-in used ONLY to test the plumbing.

    Its numbers mean nothing about Jev's quality.
    """
    flat = canonical(state)
    if isinstance(state, dict) and len(state) >= 2:
        values = list(state.values())
        left, right = _words(canonical(values[0])), _words(canonical(values[1:]))
        overlap = len(left & right) / max(1, len(left))
    else:
        overlap = 0.0
    seed = int(hashlib.sha256(flat.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    answers: dict[str, Any] = {}
    for name, question in questions.items():
        p = max(0.01, min(0.99, 0.15 + 0.8 * overlap + 0.1 * (seed - 0.5)))
        if question["type"] == "noul":
            answers[name] = {"type": "noul", "noul": round(p, 4)}
        elif question["type"] == "choice":
            options = list(question["criteria"])
            weights = [p ** (i + 1) if i == 0 else (1 - p) / max(1, len(options) - 1) for i in range(len(options))]
            total = sum(weights)
            probs = {o: round(w / total, 4) for o, w in zip(options, weights)}
            top = max(probs, key=probs.get)
            answers[name] = {"type": "choice", "choice": top, "probabilities": probs,
                             "confidence": round(abs(2 * max(probs.values()) - 1), 4)}
        else:
            levels = question["criteria"]
            answers[name] = {"type": "score", "score": round(p * (len(levels) - 1), 4), "confidence": 0.5}
    return {"model": "mock-heuristic", "answers": answers,
            "usage": {"input_tokens": len(flat) // 4, "output_tokens": 0}}
