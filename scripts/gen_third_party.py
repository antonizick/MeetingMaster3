#!/usr/bin/env python3
"""Regenerate the runtime-dependency table in THIRD_PARTY_NOTICES.md from the lockfile.

Run from the repo root with the project environment: ``uv run python scripts/gen_third_party.py``.
Only the block between the GENERATED markers is rewritten.
"""

from __future__ import annotations

import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

START = "<!-- GENERATED:runtime-deps:start -->"
END = "<!-- GENERATED:runtime-deps:end -->"
# Packages only installed on other platforms, so their metadata is not available here.
OVERRIDES = {"colorama": "BSD-3-Clause (Windows only)"}
TARGET = Path(__file__).parents[1] / "THIRD_PARTY_NOTICES.md"


def locked_runtime_packages() -> dict[str, str]:
    out = subprocess.run(
        ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    pkgs: dict[str, str] = {}
    for line in out.splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;]+)", line)
        if m:
            pkgs[m.group(1)] = m.group(2)
    return pkgs


def license_of(name: str) -> str:
    if name in OVERRIDES:
        return OVERRIDES[name]
    try:
        md = metadata.metadata(name)
    except metadata.PackageNotFoundError:
        return "unknown (not installed)"
    expr = md.get("License-Expression")
    if expr:
        return expr
    classifiers = [c.split("::")[-1].strip() for c in md.get_all("Classifier", [])
                   if c.startswith("License ::")]  # fmt: skip
    if classifiers:
        return "; ".join(classifiers)
    lic = (md.get("License") or "").strip().splitlines()
    return lic[0][:60] if lic else "unknown"


def render(pkgs: dict[str, str]) -> str:
    rows = ["| Package | Version | License |", "|---|---|---|"]
    for name in sorted(pkgs, key=str.lower):
        rows.append(f"| {name} | {pkgs[name]} | {license_of(name)} |")
    return "\n".join(rows)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if START not in text or END not in text:
        print(f"Markers missing in {TARGET}", file=sys.stderr)
        return 1
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    block = f"{START}\n{render(locked_runtime_packages())}\n{END}"
    TARGET.write_text(head + block + tail, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
