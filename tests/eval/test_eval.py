"""Live generation eval against a local model (Phase 09). Not run in CI.

    MM3_EVAL_MODEL=qwen3:8b uv run pytest tests/eval -s

Every note of every built-in template must pass the checker for the three synthetic meetings,
and a long meeting (at least 3x the context window) must complete through map-reduce.
"""

from __future__ import annotations

import os

import pytest

from tests.eval.run_eval import main

MODEL = os.environ.get("MM3_EVAL_MODEL", "")
pytestmark = [
    pytest.mark.network,
    pytest.mark.slow,
    pytest.mark.skipif(not MODEL, reason="set MM3_EVAL_MODEL (e.g. qwen3:8b) to run the eval"),
]


async def test_eval_all_templates_pass() -> None:
    assert await main(["--model", MODEL]) == 0


async def test_long_meeting_completes_through_map_reduce() -> None:
    assert await main(["--model", MODEL, "--long"]) == 0
