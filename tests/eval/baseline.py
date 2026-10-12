"""Compare an eval run with the recorded baseline and flag regressions (Phase 15).

    uv run python -m tests.eval.run_eval --model qwen3:8b --json /tmp/results.json
    uv run python -m tests.eval.baseline /tmp/results.json            # exit 1 on a regression
    uv run python -m tests.eval.baseline /tmp/results.json --update   # accept as the new baseline

A regression is a note that passed every check in the baseline and now fails one, or that finds
fewer decisions, actions or questions than before. Notes missing from either side are listed.
Timing is reported, never judged (it depends on the machine and what else is running).
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

BASELINE = Path(__file__).with_name("baseline.json")


def _index(data: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(r["meeting"], r["template"]): r for r in data["results"]}


def compare(baseline: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Human-readable regressions (empty when there are none)."""
    old, new = _index(baseline), _index(current)
    problems: list[str] = []
    for key, before in sorted(old.items()):
        after = new.get(key)
        name = f"{key[0]} / {key[1]}"
        if after is None:
            continue  # partial runs are allowed; listed separately
        if before["passed"] and not after["passed"]:
            failed = [k for k, v in after["checks"].items() if not v]
            problems.append(f"{name}: now fails {', '.join(failed)}")
        for kind, count in before["found"].items():
            if after["found"].get(kind, 0) < count:
                problems.append(f"{name}: {kind} found {after['found'].get(kind, 0)} < {count}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("results", type=Path)
    ap.add_argument("--baseline", type=Path, default=BASELINE)
    ap.add_argument("--update", action="store_true", help="Make these results the baseline.")
    args = ap.parse_args(argv)
    current = json.loads(args.results.read_text(encoding="utf-8"))
    if args.update:
        shutil.copyfile(args.results, args.baseline)
        print(f"Baseline updated ({len(current['results'])} notes, {current['model']}).")
        return 0
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    if baseline["model"] != current["model"]:
        print(f"Note: baseline model {baseline['model']}, this run {current['model']}.")
    missing = sorted(set(_index(baseline)) - set(_index(current)))
    added = sorted(set(_index(current)) - set(_index(baseline)))
    problems = compare(baseline, current)
    now = sum(r["passed"] for r in current["results"])
    before = sum(r["passed"] for r in baseline["results"])
    print(
        f"{now}/{len(current['results'])} notes pass; baseline {before}/{len(baseline['results'])}."
    )
    if missing:
        print(f"Not run this time: {len(missing)} notes.")
    if added:
        print(f"New (not in the baseline): {', '.join(f'{m}/{t}' for m, t in added)}")
    for p in problems:
        print(f"REGRESSION {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
