"""Make product source and the pinned Retrieval V1 component importable in tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
for path in (
    PROJECT_ROOT / "src",
    PROJECT_ROOT / "research/knowledge-retrieval/retrieval-tool",
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Publishing a course builds its retrieval index. Unless a test asks for Retrieval V1 itself, tests use the
# keyword index, so the suite never loads an embedding model or depends on what is installed.
os.environ.setdefault("DP_RETRIEVAL_MODE", "keyword")
# Tests never call Jev (passage judge) over the network; a test that needs it injects a fake.
os.environ["DP_JEV"] = "off"

# Run logs from tests go to a throwaway folder, never into the developer's logs/.
import tempfile  # noqa: E402

os.environ.setdefault("DIGITAL_PROFESSOR_LOG_DIR", tempfile.mkdtemp(prefix="dp-test-logs-"))

# Tests never read the developer's .env and never inherit a configured provider: a real key there would
# send test turns to a paid model and make results depend on the machine.
os.environ["DIGITAL_PROFESSOR_SKIP_DOTENV"] = "1"
for _name in ("DIGITAL_PROFESSOR_PROVIDER", "DIGITAL_PROFESSOR_MODEL", "DIGITAL_PROFESSOR_BASE_URL"):
    os.environ.pop(_name, None)
