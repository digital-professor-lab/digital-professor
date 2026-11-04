"""Test configuration for the repository's src-layout package."""

from __future__ import annotations

import sys
from pathlib import Path


COMPONENT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = COMPONENT_ROOT / "src"
if str(COMPONENT_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPONENT_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

