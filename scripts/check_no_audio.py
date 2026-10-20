#!/usr/bin/env python3
"""Pre-commit hook: refuse audio/video files unless they are tiny test fixtures.

Allowed: ``tests/fixtures/audio/<name>.fixture.<ext>``. Everything else is rejected so that
recordings never reach the repository (CLAUDE.md, MM3_SPECIFICATION §15.4).
"""

from __future__ import annotations

import re
import sys
from pathlib import PurePosixPath

AUDIO_EXTENSIONS = {
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wma", ".aiff",
    ".aif", ".amr", ".mp4", ".mkv", ".mov", ".webm", ".m4b", ".3gp",
}  # fmt: skip
FIXTURE = re.compile(r"^tests/fixtures/audio/[^/]+\.fixture\.[A-Za-z0-9]+$")


def is_blocked(path: str) -> bool:
    p = PurePosixPath(path.replace("\\", "/"))
    return p.suffix.lower() in AUDIO_EXTENSIONS and not FIXTURE.match(p.as_posix())


def main(argv: list[str]) -> int:
    bad = [a for a in argv if is_blocked(a)]
    for path in bad:
        print(f"Blocked audio/video file: {path}", file=sys.stderr)
    if bad:
        print(
            "Audio may only be committed as tests/fixtures/audio/<name>.fixture.<ext>.",
            file=sys.stderr,
        )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
