"""Artifact storage abstractions for preserving original student input."""

from __future__ import annotations

from threading import RLock


class ArtifactAlreadyExistsError(RuntimeError):
    """Raised when a caller tries to overwrite an immutable artifact."""


class InMemoryArtifactStore:
    """Small immutable artifact store for tests and the first local demo."""

    def __init__(self) -> None:
        self._artifacts: dict[str, str | bytes] = {}
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

        value = self._artifacts[reference]
        if not isinstance(value, str):
            raise TypeError(f"Artifact is binary: {reference}")
        return value

    def preserve_binary(self, submission_id: str, data: bytes, *, filename: str) -> str:
        """Store exact uploaded bytes without permitting later replacement."""

        safe_name = filename.replace("/", "_").replace("\\", "_") or "original.bin"
        reference = f"artifact://{submission_id}/{safe_name}"
        with self._lock:
            if reference in self._artifacts:
                raise ArtifactAlreadyExistsError(
                    f"Original artifact already exists and cannot be overwritten: {reference}"
                )
            self._artifacts[reference] = bytes(data)
        return reference

    def read_binary(self, reference: str) -> bytes:
        value = self._artifacts[reference]
        if not isinstance(value, bytes):
            raise TypeError(f"Artifact is text: {reference}")
        return value

    def preserve_diagnostic_text(self, reference: str, text: str) -> str:
        """Store optional raw provider output under an explicit reference."""

        with self._lock:
            if reference in self._artifacts:
                raise ArtifactAlreadyExistsError(reference)
            self._artifacts[reference] = text
        return reference

    def __contains__(self, reference: str) -> bool:
        return reference in self._artifacts

