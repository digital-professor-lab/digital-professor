"""Jev as a passage judge: does a textbook passage actually state the rule the tutor is about to cite?

Before the tutor sends a student to a textbook passage, the candidates are scored by Jev (TypeSafe's System
One model, through OpenRouter): one yes/no question per passage, "does this passage state <method> itself?",
answered as a probability. Passages that state the rule come first; a proof, a worked example or an
introduction that only names the topic scores low. Measured on the labelled set in the retrieval tool
(`scripts/eval_evidence_judge.py`, 28 pairs): 25/28 correct, no passage wrongly accepted, against 18/28 and
8 wrongly accepted for the rules.

Only textbook text and the method name are sent. Student messages never are.

Jev is used when ``OPENROUTER_API_KEY`` (or ``TYPESAFE_API_KEY``) is set and ``DP_JEV`` is not ``off``. Any
failure (no key, timeout, bad answer) returns ``None`` and the rules decide, as before. Answers are cached on
disk, so the same passage is never paid for twice.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

COVERED_AT = 0.7          # the retrieval tool's default threshold for "states it"
OFF_TOPIC_BELOW = 0.35    # its "partially covered" threshold: below it a passage is not offered
MAX_PASSAGES = 6          # candidates scored per search
_CACHE = Path(os.getenv("DP_JEV_CACHE", ".cache/jev/jev_answers.jsonl"))
_judge: Any = None
_checked = False


class PassageJudge:
    def __init__(self, client: Any) -> None:
        from retrieval_tool.evidence import JevEvidenceJudge

        self._judge = JevEvidenceJudge(client)
        self.model = getattr(client, "model", "jev")

    def scores(self, topic: str, texts: list[str]) -> tuple[list[float] | None, dict[str, Any]]:
        """One score per text (0..1, "states the rule"), and a record for the run log."""
        need = [{"need_id": "n1", "need_type": "rule",
                 "description": f"The statement of {topic}: the rule or theorem itself, written out "
                                "(not a proof, not only a worked example, not only its name)."}]
        started = time.perf_counter()
        try:
            values = [round(s["n1"], 3) for s in self._judge.score(need, [t[:6000] for t in texts])]
        except Exception as error:          # the rules take over; the turn never fails because of Jev
            log.warning("Jev passage judge failed: %s", error)
            return None, {"status": "failed", "error": type(error).__name__,
                          "ms": round((time.perf_counter() - started) * 1000)}
        return values, {"status": "ok", "model": self.model, "covered_at": COVERED_AT,
                        "ms": round((time.perf_counter() - started) * 1000)}


_client: Any = None
_client_checked = False


def jev_enabled() -> bool:
    return os.getenv("DP_JEV", "on").strip().lower() not in {"off", "0", "false", "no"}


def shared_client() -> Any:
    """One Jev client per process (shared cache), or None when Jev is off or no key is set."""
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True
    if not jev_enabled():
        return None
    provider = ("openrouter" if os.getenv("OPENROUTER_API_KEY")
                else "typesafe" if os.getenv("TYPESAFE_API_KEY") else None)
    if provider is None:
        return None
    try:
        from retrieval_tool.jev_client import JevClient

        _CACHE.parent.mkdir(parents=True, exist_ok=True)
        _client = JevClient(provider, model=os.getenv("JEV_MODEL") or None, cache_path=_CACHE,
                            timeout=10, max_retries=1)
    except Exception as error:
        log.warning("Jev unavailable: %s", error)
        _client = None
    return _client


def default_judge() -> PassageJudge | None:
    """The shared passage judge, or None when Jev is off or not configured."""
    global _judge, _checked
    if _checked:
        return _judge
    _checked = True
    client = shared_client()
    _judge = PassageJudge(client) if client is not None else None
    return _judge


def reset_for_tests() -> None:
    global _judge, _checked, _client, _client_checked
    _judge, _checked, _client, _client_checked = None, False, None, False
