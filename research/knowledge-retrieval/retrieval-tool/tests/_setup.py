"""Shared test helpers.

Core tests use the local fixture backend and need only the packages in `pip install -e ".[test]"`.
Tests that need the Week 3 checkout live in test_week3_integration.py.
"""

import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE))

from retrieval_tool import recommend_grounding, run_turn  # noqa: E402
from retrieval_tool.tool_schema import TurnContext  # noqa: E402


def ctx(**overrides):
    values = dict(course_id="calc1", session_id="sess-1", turn_id="turn-1", question_id="q-chain-1",
                  correlation_id="corr-1", action_type="explain", retrieval_snapshot_id="snap.calc1.dev-ai-breakdown.1")
    values.update(overrides)
    return TurnContext(**values)


def engine_turn(llm, service, turn, **kwargs):
    """Plays the Engine's part: apply the agreed policy to the turn's action, then run the turn."""
    return run_turn(llm, service, turn, decision=recommend_grounding(turn.action_type), **kwargs)


def week3_root():
    from retrieval_tool import retrieval_root
    try:
        return retrieval_root()
    except FileNotFoundError:
        return None
