#!/usr/bin/env python3
"""Regenerate the dependency tables in THIRD_PARTY_NOTICES.md from the lockfile.

Run from the repo root with every extra installed (licences are read from package metadata):

    uv run --extra ml --extra bedrock python scripts/gen_third_party.py
    uv run --extra ml --extra bedrock python scripts/gen_third_party.py --check   # CI-style check

Only the blocks between the GENERATED markers are rewritten. ``--check`` fails when the file is out
of date or when a licence is copyleft (GPL/AGPL/LGPL/SSPL), unknown, or proprietary outside the
documented NVIDIA CUDA wheels; such a dependency needs the owner's decision (Phase 15 audit).
"""

from __future__ import annotations

import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

START = "<!-- GENERATED:runtime-deps:start -->"
END = "<!-- GENERATED:runtime-deps:end -->"
EXTRAS_START = "<!-- GENERATED:extras-deps:start -->"
EXTRAS_END = "<!-- GENERATED:extras-deps:end -->"
EXTRAS = ("ml", "bedrock")
# Packages whose metadata declares no licence (verified from their LICENSE files in Phase 15) or
# that are only installed on other platforms.
OVERRIDES = {
    "colorama": "BSD-3-Clause (Windows only)",
    "tzdata": "Apache-2.0 (Windows only)",
    "pyannote-audio": "MIT",
    "pyannote-core": "MIT",
    "pyannote-database": "MIT",
    "pyannote-metrics": "MIT",
    "pyannote-pipeline": "MIT",
    "pyannoteai-sdk": "MIT",
    "torchcodec": "BSD-3-Clause",
}
#: Accepted non-open-source licences: NVIDIA's CUDA/cuDNN wheels that PyTorch depends on (GPU
#: only, installed from PyPI under NVIDIA's terms; see THIRD_PARTY_NOTICES).
ACCEPTED_PROPRIETARY = re.compile(r"^nvidia-")
PROBLEM = re.compile(r"\b(A?GPL|LGPL|SSPL|BUSL|unknown|proprietary|Other)\b", re.IGNORECASE)
TARGET = Path(__file__).parents[1] / "THIRD_PARTY_NOTICES.md"


def locked_runtime_packages(*extras: str) -> dict[str, str]:
    cmd = ["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--no-hashes"]
    for extra in extras:
        cmd += ["--extra", extra]
    out = subprocess.run(  # noqa: S603 - fixed command
        cmd,
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


def policy_problems(pkgs: dict[str, str]) -> list[str]:
    """Dependencies whose licence needs a decision (copyleft, unknown, unexpected proprietary)."""
    out = []
    for name in sorted(pkgs, key=str.lower):
        lic = license_of(name)
        if PROBLEM.search(lic) and not ACCEPTED_PROPRIETARY.match(name):
            out.append(f"{name} {pkgs[name]}: {lic}")
    return out


def _replace(text: str, start: str, end: str, body: str) -> str:
    if start not in text or end not in text:
        raise SystemExit(f"Markers {start} / {end} missing in {TARGET}")
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    return f"{head}{start}\n{body}\n{end}{tail}"


def main(argv: list[str] | None = None) -> int:
    check = "--check" in (argv if argv is not None else sys.argv[1:])
    core = locked_runtime_packages()
    everything = locked_runtime_packages(*EXTRAS)
    extras_only = {k: v for k, v in everything.items() if k not in core}
    text = TARGET.read_text(encoding="utf-8")
    new = _replace(text, START, END, render(core))
    new = _replace(new, EXTRAS_START, EXTRAS_END, render(extras_only))
    problems = policy_problems(everything)
    for p in problems:
        print(f"LICENCE NEEDS A DECISION: {p}", file=sys.stderr)
    if check:
        if new != text:
            print(f"{TARGET.name} is out of date: run scripts/gen_third_party.py", file=sys.stderr)
            return 1
        return 1 if problems else 0
    TARGET.write_text(new, encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
