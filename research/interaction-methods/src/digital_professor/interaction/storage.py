"""Artifact storage abstractions for preserving original student input."""

from __future__ import annotations

from threading import RLock


class ArtifactAlreadyExistsError(RuntimeError):
    """Raised when a caller tries to overwrite an immutable artifact."""


class InMemoryArtifactStore:
    """Small immutable artifact store for tests and the first local demo."""

    def __init__(self) -> None:
        self._artifacts: dict[str, str] = {}
        self._lock = RLock()

    def preserve_text(self, submission_id: str, text: str) -> str:
        """Store exact text once and return its controlled artifact reference."""

        reference = f"artifact://{submission_id}/original.txt"
        with self._lock:
            if reference in self._artifacts:
                raise ArtifactAlreadyExistsError(
                    f"Original artifact already exists and cannot be overwritten: {reference}"
                )
            self._artifacts[reference] = text
        return reference

    def read_text(self, reference: str) -> str:
        """Return the exact preserved text."""

        return self._artifacts[reference]

    def __contains__(self, reference: str) -> bool:
        return reference in self._artifacts

