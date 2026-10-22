"""The committed search corpus (``tests/fixtures/search_vault/``) matches its generator."""

from __future__ import annotations

import os

from meetingmaster3.vault.io import read_text
from tests.search_corpus import FOLDER, files


def test_search_vault_files_match_the_generator() -> None:
    expected = files()
    if os.environ.get("MM3_UPDATE_GOLDEN") == "1":
        for rel, text in expected.items():
            path = FOLDER / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="")
        (FOLDER / ".obsidian").mkdir(exist_ok=True)
        (FOLDER / ".obsidian" / ".gitkeep").touch()
    found = {p.relative_to(FOLDER).as_posix() for p in FOLDER.rglob("*.md")}
    assert found == set(expected)
    for rel, text in expected.items():
        assert read_text(FOLDER / rel) == text, rel
