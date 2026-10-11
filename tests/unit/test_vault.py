from __future__ import annotations

import datetime as dt
import errno
import os
import stat
import uuid
from pathlib import Path

import pytest

from meetingmaster3.domain.note import Section
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.frontmatter import split_frontmatter
from meetingmaster3.vault import io as vault_io
from meetingmaster3.vault.archive import (
    archive_note,
    archive_section,
    note_archive_path,
    section_archive_path,
)
from meetingmaster3.vault.io import atomic_write_text, fingerprint, read_text
from meetingmaster3.vault.naming import allocate_note_paths, note_stem, sanitize_title
from meetingmaster3.vault.paths import (
    confine,
    ensure_folder,
    expand_folder_template,
    output_folder,
    resolve_vault_root,
)

WHEN = dt.datetime(2026, 10, 11, 14, 30, 5)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    return root.resolve()


def code(exc: pytest.ExceptionInfo[MM3Error]) -> str:
    return exc.value.code


# --- naming -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Product Sync", "Product Sync"),
        ('Q3: "Plan" / Review?', "Q3 Plan Review"),
        ("a*b<c>d|e#f^g[h]i\\j", "a b c d e f g h i j"),
        ("  ..hidden.. ", "hidden"),
        ("tab\tand\nnewline\x00", "tab and newline"),
        ("zero\u200bwidth \u202eflip", "zerowidth flip"),
        ("e\u0301", "é"),  # NFC
        ("???", "Untitled meeting"),
        ("", "Untitled meeting"),
    ],
)
def test_sanitize_title(title: str, expected: str) -> None:
    assert sanitize_title(title) == expected


def test_sanitize_title_length_limit_is_utf8_safe() -> None:
    out = sanitize_title("日本" * 200)
    assert len(out.encode()) <= 150
    out.encode().decode("utf-8")  # no broken character
    assert sanitize_title("a" * 10 + " " + "b" * 200, max_bytes=11) == "a" * 10


def test_note_names_and_collisions(vault: Path) -> None:
    assert note_stem(dt.date(2026, 10, 11), "Sync: A/B") == "2026-10-11 - Sync A B"
    p = allocate_note_paths(vault, dt.date(2026, 10, 11), "Product Sync")
    assert p.note.name == "2026-10-11 - Product Sync.md"
    assert p.transcript.name == "2026-10-11 - Product Sync.transcript.md"
    assert p.note_link == "2026-10-11 - Product Sync"
    assert p.transcript_link == "2026-10-11 - Product Sync.transcript"
    p.note.write_text("x")
    p2 = allocate_note_paths(vault, dt.date(2026, 10, 11), "Product Sync")
    assert p2.stem == "2026-10-11 - Product Sync (2)"
    p2.transcript.write_text("only the companion exists")  # still blocks the stem
    assert allocate_note_paths(vault, dt.date(2026, 10, 11), "Product Sync").stem.endswith("(3)")
    with pytest.raises(MM3Error) as exc:
        allocate_note_paths(vault, dt.date(2026, 10, 11), "Product Sync", limit=2)
    assert code(exc) == "vault_name_exhausted"


# --- paths --------------------------------------------------------------------------------


def test_resolve_vault_root(vault: Path, tmp_path: Path) -> None:
    assert resolve_vault_root(str(vault)) == vault
    for bad, expected in [
        (None, "vault_not_configured"),
        ("  ", "vault_not_configured"),
        (tmp_path / "missing", "vault_missing"),
    ]:
        with pytest.raises(MM3Error) as exc:
            resolve_vault_root(bad)  # type: ignore[arg-type]
        assert code(exc) == expected
    f = tmp_path / "file"
    f.write_text("x")
    with pytest.raises(MM3Error) as exc:
        resolve_vault_root(f)
    assert code(exc) == "vault_not_a_directory"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permissions")
def test_unwritable_vault(vault: Path) -> None:
    vault.chmod(0o500)
    try:
        with pytest.raises(MM3Error) as exc:
            resolve_vault_root(vault)
        assert code(exc) == "vault_unwritable"
        with pytest.raises(MM3Error) as exc:
            ensure_folder(vault, "Meetings")
        assert code(exc) == "vault_unwritable"
    finally:
        vault.chmod(0o700)


def test_folder_template() -> None:
    assert expand_folder_template("Meetings/{yyyy}/{mm}/{dd}/", dt.date(2026, 3, 9)) == (
        "Meetings/2026/03/09/"
    )
    with pytest.raises(MM3Error) as exc:
        expand_folder_template("Meetings/{year}/", dt.date(2026, 3, 9))
    assert code(exc) == "vault_folder_template_invalid"


@pytest.mark.parametrize(
    "relative", ["../outside", "a/../../outside", "/etc", "~/x", "a\x00b", "Meetings/../../.."]
)
def test_path_escape_rejected(vault: Path, relative: str) -> None:
    with pytest.raises(MM3Error) as exc:
        confine(vault, relative)
    assert code(exc) == "vault_path_escape"


def test_symlink_escape_rejected(vault: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / "link").symlink_to(outside)
    (vault / "inner").mkdir()
    (vault / "ok-link").symlink_to(vault / "inner")
    with pytest.raises(MM3Error) as exc:
        ensure_folder(vault, "link/Meetings")
    assert code(exc) == "vault_path_escape"
    assert confine(vault, "ok-link/x") == vault / "inner" / "x"
    with pytest.raises(MM3Error):
        atomic_write_text(vault / "link" / "x.md", "x", vault_root=vault)
    assert not (outside / "x.md").exists()


def test_output_folder_created(vault: Path) -> None:
    folder = output_folder(vault, "Meetings/{yyyy}/", dt.date(2026, 10, 11))
    assert folder == vault / "Meetings" / "2026" and folder.is_dir()
    assert confine(vault, "Meetings/../Meetings") == vault / "Meetings"
    (vault / "blocker").write_text("x")
    with pytest.raises(MM3Error) as exc:
        ensure_folder(vault, "blocker")
    assert code(exc) == "vault_folder_blocked"


# --- io -----------------------------------------------------------------------------------


def _temps(folder: Path) -> list[Path]:
    return [p for p in folder.iterdir() if p.name.endswith(vault_io.TEMP_SUFFIX)]


def test_atomic_write_never_overwrites_by_default(vault: Path) -> None:
    target = vault / "n.md"
    atomic_write_text(target, "one\r\nCRLF kept\n", vault_root=vault)
    assert read_text(target) == "one\r\nCRLF kept\n"
    assert stat.S_IMODE(target.stat().st_mode) == vault_io.NEW_FILE_MODE
    with pytest.raises(MM3Error) as exc:
        atomic_write_text(target, "two")
    assert code(exc) == "vault_file_exists"
    assert read_text(target) == "one\r\nCRLF kept\n"
    target.chmod(0o600)
    atomic_write_text(target, "two", overwrite=True)
    assert read_text(target) == "two"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600  # existing mode kept
    assert _temps(vault) == []


def test_atomic_write_cleans_up_on_failure(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object) -> None:
        raise OSError(errno.EIO, "disk on fire")

    monkeypatch.setattr(vault_io.os, "fsync", boom)
    with pytest.raises(OSError):
        atomic_write_text(vault / "n.md", "x")
    assert not (vault / "n.md").exists()
    assert _temps(vault) == []


def test_atomic_write_race_and_no_hardlink_fallback(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def racing_link(src: str, dst: str) -> None:
        Path(dst).write_text("someone else")
        raise FileExistsError(dst)

    monkeypatch.setattr(vault_io.os, "link", racing_link)
    with pytest.raises(MM3Error) as exc:
        atomic_write_text(vault / "race.md", "mine")
    assert code(exc) == "vault_file_exists"
    assert read_text(vault / "race.md") == "someone else"

    def no_links(src: str, dst: str) -> None:
        raise OSError(errno.EPERM, "no hard links here")

    monkeypatch.setattr(vault_io.os, "link", no_links)
    atomic_write_text(vault / "exfat.md", "ok")
    assert read_text(vault / "exfat.md") == "ok"
    assert _temps(vault) == []

    def io_error(src: str, dst: str) -> None:
        raise OSError(errno.EIO, "boom")

    monkeypatch.setattr(vault_io.os, "link", io_error)
    with pytest.raises(OSError):
        atomic_write_text(vault / "eio.md", "x")
    assert _temps(vault) == []


def test_fingerprint_changes_with_content(vault: Path) -> None:
    p = atomic_write_text(vault / "f.md", "a")
    a = fingerprint(p)
    atomic_write_text(p, "b", overwrite=True)
    assert fingerprint(p).sha256 != a.sha256


# --- archive ------------------------------------------------------------------------------


def test_archive_paths(vault: Path) -> None:
    stem = "2026-10-11 - Product Sync"
    assert section_archive_path(vault, stem, "summary", WHEN).relative_to(vault) == Path(
        "Archive/2026-10-11 - Product Sync.summary.20261011-1430.md"
    )
    assert note_archive_path(vault, stem, WHEN).name == f"{stem}.20261011-1430.md"


def test_archive_section_and_collision(vault: Path) -> None:
    folder = ensure_folder(vault, "Meetings/2026")
    note = folder / "2026-10-11 - Product Sync.md"
    section = Section(id="summary", title="Summary", body_markdown="Old text.")
    first = archive_section(vault, note, section, meeting_id=uuid.UUID(int=5), when=WHEN)
    second = archive_section(vault, note, section, meeting_id=uuid.UUID(int=5), when=WHEN)
    assert first.parent == folder / "Archive"
    assert first.name == "2026-10-11 - Product Sync.summary.20261011-1430.md"
    assert second.name == "2026-10-11 - Product Sync.summary.20261011-1430 (2).md"
    text = read_text(first)
    fm, body = split_frontmatter(text)
    assert fm is not None and fm.data["mm3-archived-section"] == "summary"
    assert fm.data["mm3-archived-from"] == "[[2026-10-11 - Product Sync]]"
    assert "mm3-id" not in fm.data  # archives must not look like live notes
    assert body == "## Summary\n\nOld text.\n"
    assert archive_section(vault, note, section, meeting_id=uuid.UUID(int=5)).exists()


def test_archive_note_keeps_every_other_byte(vault: Path) -> None:
    folder = ensure_folder(vault, "Meetings")
    note = folder / "2026-10-11 - X.md"
    original = "---\r\ntitle: X  # c\r\nmm3-id: 1\r\n---\r\n# X\r\nbody\r\n"
    atomic_write_text(note, original)
    archived = read_text(archive_note(vault, note, when=WHEN))
    assert archived.startswith(
        "---\r\ntitle: X  # c\r\nmm3-id: 1\r\nmm3-archived: 2026-10-11T14:30:05\r\n"
    )
    assert archived.endswith("---\r\n# X\r\nbody\r\n")
    assert read_text(note) == original
    plain = folder / "2026-10-11 - Plain.md"
    atomic_write_text(plain, "\ufeffno frontmatter\n")
    out = read_text(archive_note(vault, plain, when=WHEN))
    assert out.startswith("\ufeff---\nmm3-archived: ") and out.endswith("---\nno frontmatter\n")
    assert archive_note(vault, plain).exists()
