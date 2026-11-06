"""Make product source and the pinned Retrieval V1 component importable in tests."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
for path in (
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "research/knowledge-retrieval/retrieval-tool",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
