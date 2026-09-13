"""Optional local speech-to-text baseline."""

from __future__ import annotations

from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path


def faster_whisper_available() -> bool:
    return find_spec("faster_whisper") is not None


@lru_cache(maxsize=3)
def _load_model(model_name: str):
    from faster_whisper import WhisperModel

    return WhisperModel(model_name, device="cpu", compute_type="int8")


def transcribe_with_faster_whisper(path: Path, model_name: str) -> str:
    if not faster_whisper_available():
        raise RuntimeError(
            "The local faster-whisper baseline is not installed. "
            "Install it with `python -m pip install faster-whisper`."
        )
    if model_name not in {"tiny", "base", "small"}:
        raise ValueError("Unsupported local Whisper model.")
    segments, _ = _load_model(model_name).transcribe(str(path), beam_size=5)
    return " ".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
