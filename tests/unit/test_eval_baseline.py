"""The eval regression checker (tests/eval/baseline.py) itself; runs without a model."""

from __future__ import annotations

from typing import Any

from tests.eval.baseline import compare


def run(passed: bool, actions: int) -> dict[str, Any]:
    return {
        "model": "m",
        "results": [
            {
                "meeting": "launch-sync",
                "template": "executive-summary",
                "passed": passed,
                "checks": {"markers_valid": True, "no_invented_owners": passed},
                "found": {"decisions": 2, "actions": actions},
            }
        ],
    }


def test_no_regression_when_equal_or_better() -> None:
    assert compare(run(True, 3), run(True, 3)) == []
    assert compare(run(False, 1), run(True, 3)) == []


def test_failed_check_and_lower_recall_are_regressions() -> None:
    problems = compare(run(True, 3), run(False, 2))
    assert any("now fails no_invented_owners" in p for p in problems)
    assert any("actions found 2 < 3" in p for p in problems)


def test_partial_runs_are_not_regressions() -> None:
    assert compare(run(True, 3), {"model": "m", "results": []}) == []
