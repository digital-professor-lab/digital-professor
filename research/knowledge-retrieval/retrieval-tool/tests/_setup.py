"""Shared test helpers. Tests that need the Week 3 index files skip when they are not found."""

import sys
from pathlib import Path

WEEK8 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEEK8))

from retrieval_tool.tool_schema import TurnContext  # noqa: E402


def ctx(**overrides):
    values = dict(course_id="calc1", session_id="sess-1", turn_id="turn-1", question_id="q-chain-1",
                  correlation_id="corr-1", action_type="explain", retrieval_snapshot_id="snap.calc1.dev-ai-breakdown.1")
    values.update(overrides)
    return TurnContext(**values)


def index_root():
    from retrieval_tool import retrieval_root
    try:
        return retrieval_root()
    except FileNotFoundError:
        return None
