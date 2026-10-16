from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from meetingmaster3.cli import app
from meetingmaster3.storage.db import Database
from meetingmaster3.storage.repositories import RecentMeetingsRepository
from meetingmaster3.vault.relink import apply_clear_matches, plan_relink


def note(path: Path, mm3_id: str, *, extra: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'---\nmm3-id: "{mm3_id}"\ntitle: T\ndate: 2026-10-01\n{extra}---\n# T\n', "utf-8"
    )
    return path


def repo_for(tmp_path: Path) -> RecentMeetingsRepository:
    return RecentMeetingsRepository(Database.open(tmp_path / "t.db"))


def test_moved_note_is_found_by_id_with_its_transcript(tmp_path: Path) -> None:
    old = tmp_path / "old" / "2026-10-01 - Standup.md"  # no longer exists
    root = tmp_path / "vault"
    new = note(root / "Meetings" / "2026" / "2026-10-01 - Standup.md", "id-1")
    tr = note(
        root / "Meetings" / "2026" / "2026-10-01 - Standup.transcript.md",
        "id-1",
        extra='mm3-note: "[[x]]"\n',
    )
    note(
        root / "Meetings" / "2026" / "2026-10-01 - Standup.20261002-0900.md",
        "id-1",
        extra="mm3-archived: 2026-10-02\n",
    )  # an archived copy is never a target
    note(
        root / "Meetings" / "2026" / "2026-10-01 - Standup (Transcript).md",
        "id-1",
        extra="mm3-kind: readable-transcript\n",
    )
    repo = repo_for(tmp_path)
    repo.touch(
        str(old),
        mm3_id="id-1",
        title="Standup",
        job_id="job-1",
        transcript_path=str(old.with_suffix(".transcript.md")),
    )

    matches = plan_relink(root, repo.recent())
    assert [m.status for m in matches] == ["found"]
    assert apply_clear_matches(repo, matches) == 1

    (entry,) = repo.recent()
    assert entry.note_path == str(new) and entry.transcript_path == str(tr)
    assert entry.job_id == "job-1" and entry.title == "Standup"  # history is kept
    assert plan_relink(root, repo.recent()) == []  # nothing left to do


def test_ambiguous_and_missing_entries_are_left_alone(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    note(root / "A" / "One.md", "dup")
    note(root / "B" / "Two.md", "dup")  # two live notes, neither has the old name
    repo = repo_for(tmp_path)
    repo.touch(str(tmp_path / "old" / "Gone.md"), mm3_id="dup")
    repo.touch(str(tmp_path / "old" / "Nowhere.md"), mm3_id="absent")

    matches = plan_relink(root, repo.recent())
    assert sorted(m.status for m in matches) == ["ambiguous", "none"]
    assert apply_clear_matches(repo, matches) == 0
    assert repo.count() == 2


def test_duplicate_prefers_the_note_that_kept_its_file_name(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    kept = note(root / "A" / "Same.md", "dup")
    note(root / "B" / "Other.md", "dup")
    repo = repo_for(tmp_path)
    repo.touch(str(tmp_path / "old" / "Same.md"), mm3_id="dup")
    (m,) = plan_relink(root, repo.recent())
    assert m.status == "found" and m.candidates[0].note == kept


def test_relinking_onto_an_entry_that_already_exists_merges_them(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    new = note(root / "Same.md", "id-1")
    repo = repo_for(tmp_path)
    repo.touch(str(tmp_path / "old" / "Same.md"), mm3_id="id-1", job_id="job-1")
    repo.touch(str(new), mm3_id="id-1")  # opened again from its new place
    apply_clear_matches(repo, plan_relink(root, repo.recent()))
    (entry,) = repo.recent()
    assert entry.note_path == str(new) and entry.job_id == "job-1"


def test_a_note_outside_the_vault_is_an_orphan_even_if_the_file_exists(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    outside = note(tmp_path / "elsewhere" / "Old.md", "id-9")
    repo = repo_for(tmp_path)
    repo.touch(str(outside), mm3_id="id-9")
    (m,) = plan_relink(root, repo.recent())
    assert m.status == "none"


def test_cli_relink_dry_run_then_apply(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    for name in ("config", "data", "cache"):
        monkeypatch.setenv(f"XDG_{name.upper()}_HOME", str(tmp_path / name))
    root = tmp_path / "vault"
    new = note(root / "N.md", "id-1")
    paths_db = tmp_path / "data" / "meetingmaster3" / "mm3.db"
    paths_db.parent.mkdir(parents=True)
    repo = RecentMeetingsRepository(Database.open(paths_db))
    repo.touch(str(tmp_path / "old" / "N.md"), mm3_id="id-1")
    repo.db.close()

    runner = CliRunner()
    dry = runner.invoke(app, ["notes", "relink", "--dry-run", "--vault", str(root)])
    assert dry.exit_code == 0 and "link" in dry.output and "Dry run" in dry.output
    assert RecentMeetingsRepository(Database.open(paths_db)).recent()[0].note_path != str(new)
    done = runner.invoke(app, ["notes", "relink", "--vault", str(root)])
    assert done.exit_code == 0 and "Re-linked 1 of 1" in done.output
    assert RecentMeetingsRepository(Database.open(paths_db)).recent()[0].note_path == str(new)
