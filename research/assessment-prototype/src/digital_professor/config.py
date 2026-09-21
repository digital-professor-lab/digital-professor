"""Environment-backed configuration with no secrets committed to source control."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    openai_model: str
    render_dpi: int
    max_pages: int
    input_cost_per_1m: float | None
    output_cost_per_1m: float | None

    @property
    def api_enabled(self) -> bool:
        return bool(self.openai_api_key)


def load_settings(env_path: str | Path | None = None) -> Settings:
    """Load local settings, searching upward for ``.env`` when no path is given."""
    load_dotenv(dotenv_path=env_path, override=env_path is not None)
    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        render_dpi=int(os.getenv("DP_RENDER_DPI", "180")),
        max_pages=int(os.getenv("DP_MAX_PAGES", "5")),
        input_cost_per_1m=_optional_float("OPENAI_INPUT_COST_PER_1M"),
        output_cost_per_1m=_optional_float("OPENAI_OUTPUT_COST_PER_1M"),
    )


def _optional_float(name: str) -> float | None:
    value = os.getenv(name, "").strip()
    return float(value) if value else None
