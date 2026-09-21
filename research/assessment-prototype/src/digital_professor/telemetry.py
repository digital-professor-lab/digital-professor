"""Metadata-only interaction telemetry for prototype evaluation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any


class MetricsStore:
    def __init__(self, path: Path):
        self.path = path
        self._events: list[dict[str, Any]] = []
        self._lock = Lock()

    def record(self, event: dict[str, Any]) -> dict[str, Any]:
        row = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
        with self._lock:
            self._events.append(row)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        return row

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)


def correction_metrics(before: str, after: str) -> dict[str, float | int]:
    """Measure edits after recognition using character-level Levenshtein distance."""
    left, right = before.strip(), after.strip()
    previous = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current = [i]
        for j, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (left_char != right_char),
                )
            )
        previous = current
    edits = previous[-1]
    return {
        "correction_edit_distance": edits,
        "correction_rate": edits / max(len(left), 1),
    }
