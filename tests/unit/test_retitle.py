"""Renaming and re-dating a meeting: plan, apply, journal and recovery (Phase 15d, R28)."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.note_writer import with_transcript_link
from meetingmaster3.markdown.transcript_format import parse_transcript
from meetingmaster3.review import retitle
from meetingmaster3.review.retitle import (
    JOURNAL,
    MANIFEST,
    apply_retitle,
    backups_root,
    plan_retitle,
    recover_renames,
)
from meetingmaster3.storage.db import Database
from meetingmaster3.storage.repositories import JobRepository, RecentMeetingsRepository
from meetingmaster3.vault.archive import archive_note, archive_section
from meetingmaster3.vault.io import read_text
from meetingmaster3.vault.readable import find_readable, write_readable

FIXTURES = Path(__file__).parents[1] / "fixtures" / "notes"
STEM = "2026-10-11 - Product Sync"
MM3_ID = "3f2b8c1e-7d4a-4e9b-a6c2-5b1d0e8f9a71"
FOLDER = "Meetings/{yyyy}/"
JOB = "job-1"


@dataclass
class Meeting:
    root: Path
    data: Path
    jobs: Path
    db: Database
    note: Path

    @property
    def folder(self) -> Path:
        return self.note.parent

    def plan(self, **kw: object) -> retitle.RetitlePlan:
        return plan_retitle(self.root, self.note, output_subfolder=FOLDER, **kw)  # type: ignore[arg-type]

    def apply(self, plan: retitle.RetitlePlan, **kw: object) -> retitle.RetitleResult:
        return apply_retitle(plan, data_dir=self.data, db=self.db, jobs_root=self.jobs, **kw)  # type: ignore[arg-type]

    def snapshot(self) -> dict[str, bytes]:
        return {
            p.relative_to(self.root).as_posix(): p.read_bytes()
            for p in sorted(self.root.rglob("*"))
            if p.is_file() and ".obsidian" not in p.parts
        }


def place(root: Path, folder: str, *, companion: bool = True) -> Path:
    target = root / folder
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / f"{STEM}.md", target / f"{STEM}.md")
    if companion:
        shutil.copyfile(FIXTURES / f"{STEM}.transcript.md", target / f"{STEM}.transcript.md")
    return target / f"{STEM}.md"


@pytest.fixture
def meeting(tmp_path: Path) -> Meeting:
    return build_meeting(tmp_path)


def build_meeting(tmp_path: Path) -> Meeting:
    root = (tmp_path / "vault").resolve()
    (root / ".obsidian").mkdir(parents=True)
    note = place(root, "Meetings/2026")
    companion = note.with_name(f"{STEM}.transcript.md")
    note.write_text(with_transcript_link(read_text(note), f"{STEM} (Transcript)"), "utf-8")
    write_readable(root, note, parse_transcript(read_text(companion)).doc, transcript=companion)
    data, jobs = tmp_path / "data", tmp_path / "data" / "jobs"
    (jobs / JOB).mkdir(parents=True)
    db = Database.open(tmp_path / "data" / "mm3.db")
    JobRepository(db).create(
        JOB,
        stages=["write"],
        title="Product Sync",
        meeting_date=dt.date(2026, 10, 11),
        settings={"title": "Product Sync", "meeting_date": "2026-10-11", "meeting_time": None},
    )
    RecentMeetingsRepository(db).touch(
        str(note),
        transcript_path=str(companion),
        mm3_id=MM3_ID,
        title="Product Sync",
        date=dt.date(2026, 10, 11),
        job_id=JOB,
    )
    (jobs / JOB / "written.json").write_text(
        json.dumps({"mm3_id": MM3_ID, "note_path": str(note), "title": "Product Sync"})
    )
    return Meeting(root, data, jobs, db, note)


def names(m: Meeting) -> set[str]:
    return set(m.snapshot())


def sections(text: str) -> list[tuple[str, str, str]]:
    return [(s.id, s.title, s.body_markdown) for s in parse_note(text).note.sections]


# -- the plan --------------------------------------------------------------------------------------


def test_title_only_renames_every_file_in_place(meeting: Meeting) -> None:
    before = meeting.snapshot()
    plan = meeting.plan(title="Product Sync: Launch")
    assert meeting.snapshot() == before  # planning writes nothing
    assert plan.new_stem == "2026-10-11 - Product Sync Launch"
    assert {f.role for f in plan.files} == {"note", "companion", "readable"}
    assert plan.old_folder == plan.new_folder == "Meetings/2026"
    meeting.apply(plan)
    new = meeting.folder / "2026-10-11 - Product Sync Launch.md"
    text = read_text(new)
    meta = parse_note(text).note.meta
    assert meta.title == "Product Sync: Launch" and str(meta.id) == MM3_ID
    assert meta.date == dt.datetime(2026, 10, 11, 14, 0)
    assert "\n# Product Sync: Launch\n" in text
    assert meta.transcript_ref == "2026-10-11 - Product Sync Launch.transcript"
    assert sections(text) == sections(before[f"Meetings/2026/{STEM}.md"].decode())
    comp = read_text(meeting.folder / "2026-10-11 - Product Sync Launch.transcript.md")
    assert "# Transcript: Product Sync: Launch" in comp
    assert parse_transcript(comp).doc.note_ref == "2026-10-11 - Product Sync Launch"
    old_comp = before[f"Meetings/2026/{STEM}.transcript.md"].decode()
    assert (
        comp.split("<!-- mm3:transcript-data")[1] == old_comp.split("<!-- mm3:transcript-data")[1]
    )
    assert find_readable(new, MM3_ID) == new.with_name(
        "2026-10-11 - Product Sync Launch (Transcript).md"
    )
    assert not names(meeting) & {f"Meetings/2026/{STEM}{s}" for s in (".md", ".transcript.md")}
    assert f"Meetings/2026/{STEM} (Transcript).md" not in names(meeting)


def test_date_only_keeps_the_time_and_updates_the_header(meeting: Meeting) -> None:
    plan = meeting.plan(date=dt.date(2026, 10, 1))
    assert plan.new_stem == "2026-10-01 - Product Sync" and plan.new_folder == "Meetings/2026"
    meeting.apply(plan)
    text = read_text(meeting.folder / "2026-10-01 - Product Sync.md")
    assert "date: 2026-10-01T14:00:00\n" in text
    assert "- **Date & Time:** 2026-10-01 14:00\n" in text
    assert "title: Product Sync\n" in text


def test_time_can_be_set_and_cleared(meeting: Meeting) -> None:
    plan = meeting.plan(time=dt.time(9, 30))
    assert plan.new_stem == STEM and not any(f.moved for f in plan.files)
    meeting.apply(plan)
    assert "- **Date & Time:** 2026-10-11 09:30\n" in read_text(meeting.note)
    meeting.apply(meeting.plan(time=None))
    assert "- **Date & Time:** 2026-10-11\n" in read_text(meeting.note)
    assert "date: 2026-10-11T00:00:00\n" in read_text(meeting.note)


def test_a_date_in_another_year_moves_the_files_and_archives(meeting: Meeting) -> None:
    archived = archive_note(meeting.root, meeting.note, when=dt.datetime(2026, 10, 12, 9, 21))
    parsed = parse_note(read_text(meeting.note))
    section = archive_section(
        meeting.root,
        meeting.note,
        parsed.note.sections[0],
        meeting_id=parsed.note.meta.id,
        when=dt.datetime(2026, 10, 13, 8, 0),
    )
    plan = meeting.plan(date=dt.date(2025, 12, 30))
    assert plan.new_folder == "Meetings/2025"
    assert sorted(f.role for f in plan.files) == [
        "archive",
        "archive",
        "companion",
        "note",
        "readable",
    ]
    meeting.apply(plan)
    new_folder = meeting.root / "Meetings/2025"
    assert (new_folder / "2025-12-30 - Product Sync.md").is_file()
    assert (new_folder / "2025-12-30 - Product Sync.transcript.md").is_file()
    assert (new_folder / "2025-12-30 - Product Sync (Transcript).md").is_file()
    a1 = new_folder / "Archive" / "2025-12-30 - Product Sync.20261012-0921.md"
    a2 = new_folder / "Archive" / f"2025-12-30 - Product Sync.{section.name.split('.', 1)[1]}"
    assert a1.is_file() and a2.is_file()
    assert not archived.exists() and not section.exists()
    a_text = read_text(a1)
    assert 'mm3-archived-from: "[[2025-12-30 - Product Sync]]"' in a_text
    assert 'mm3-transcript: "[[2025-12-30 - Product Sync.transcript]]"' in a_text
    assert "\n# Product Sync\n" in a_text and "- **Date & Time:** 2026-10-11 14:00" in a_text
    assert not list((meeting.root / "Meetings/2026").glob("*.md"))


def test_a_note_moved_by_the_user_stays_in_its_folder(meeting: Meeting) -> None:
    moved = place(meeting.root, "Projects/Alpha", companion=False)
    meeting.note.unlink()
    shutil.move(meeting.folder / f"{STEM}.transcript.md", moved.parent)
    meeting.note = moved
    plan = meeting.plan(date=dt.date(2025, 1, 2))
    assert plan.new_folder == "Projects/Alpha"
    assert any("not in the folder for its date" in w for w in plan.warnings)


def test_without_a_companion_only_the_note_is_renamed(tmp_path: Path, meeting: Meeting) -> None:
    for p in meeting.folder.glob(f"{STEM}*transcript*"):
        p.unlink()
    for p in meeting.folder.glob(f"{STEM} (Transcript)*"):
        p.unlink()
    plan = meeting.plan(title="Solo")
    assert [f.role for f in plan.files] == ["note"]
    assert any("no companion transcript" in w for w in plan.warnings)
    meeting.apply(plan)
    text = read_text(meeting.folder / "2026-10-11 - Solo.md")
    assert (
        'mm3-transcript: "[[2026-10-11 - Product Sync.transcript]]"' in text
    )  # nothing to point at


def test_a_readable_transcript_at_a_numbered_name(meeting: Meeting) -> None:
    readable = meeting.folder / f"{STEM} (Transcript).md"
    readable.rename(meeting.folder / f"{STEM} (Transcript 2).md")
    (meeting.folder / f"{STEM} (Transcript).md").write_text("someone else's file")
    meeting.note.write_text(
        read_text(meeting.note).replace(" (Transcript)|", " (Transcript 2)|"), encoding="utf-8"
    )
    plan = meeting.plan(title="Renamed")
    (r,) = [f for f in plan.files if f.role == "readable"]
    assert r.old_rel.endswith("(Transcript 2).md") and r.new_rel.endswith("Renamed (Transcript).md")
    meeting.apply(plan)
    assert (meeting.folder / f"{STEM} (Transcript).md").read_text() == "someone else's file"
    note = meeting.folder / "2026-10-11 - Renamed.md"
    assert find_readable(note, MM3_ID) == note.with_name("2026-10-11 - Renamed (Transcript).md")
    assert "[[2026-10-11 - Renamed (Transcript)|Read the transcript]]" in read_text(note)


def test_the_vault_audio_copy_is_renamed(meeting: Meeting) -> None:
    audio = meeting.root / "Meetings/attachments" / f"{STEM}.opus"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"OggS fake audio")
    text = read_text(meeting.note).replace(
        "mm3-model: qwen3:8b\n",
        f'mm3-model: qwen3:8b\nmm3-audio: "[[Meetings/attachments/{STEM}.opus]]"\n',
    )
    meeting.note.write_text(text, encoding="utf-8")
    plan = meeting.plan(title="With Audio")
    assert any(f.role == "audio" for f in plan.files)
    meeting.apply(plan)
    new_audio = audio.with_name("2026-10-11 - With Audio.opus")
    assert new_audio.read_bytes() == b"OggS fake audio" and not audio.exists()
    meta = parse_note(read_text(meeting.folder / "2026-10-11 - With Audio.md")).note.meta
    assert meta.audio_ref == "Meetings/attachments/2026-10-11 - With Audio.opus"


def test_a_collision_is_refused(meeting: Meeting) -> None:
    (meeting.folder / "2026-10-11 - Taken.transcript.md").write_text("not ours")
    plan = meeting.plan(title="Taken")
    assert plan.blocked and "already exists" in plan.blocked[0]
    before = meeting.snapshot()
    with pytest.raises(MM3Error) as exc:
        meeting.apply(plan)
    assert exc.value.code == "E_RETITLE_TARGET_EXISTS"
    assert meeting.snapshot() == before


def test_a_case_only_rename_works(meeting: Meeting) -> None:
    plan = meeting.plan(title="product sync")
    assert plan.new_stem == "2026-10-11 - product sync" and not plan.blocked
    meeting.apply(plan)
    assert {n.split("/")[-1] for n in names(meeting)} >= {
        "2026-10-11 - product sync.md",
        "2026-10-11 - product sync.transcript.md",
    }
    assert not (meeting.folder / f"{STEM}.md").exists()


def test_nothing_to_change_and_invalid_input(meeting: Meeting) -> None:
    plan = meeting.plan(title="Product Sync")
    assert plan.empty
    with pytest.raises(MM3Error) as exc:
        meeting.apply(plan)
    assert exc.value.code == "E_RETITLE_NOTHING"
    for bad in ("   ", "x" * 201):
        with pytest.raises(MM3Error) as exc:
            meeting.plan(title=bad)
        assert exc.value.code == "E_RETITLE_INVALID"


def test_prose_mentions_are_pointed_out_not_rewritten(meeting: Meeting) -> None:
    text = read_text(meeting.note).replace(
        "The team agreed", "Product Sync on 10-11 (2026-10-11): the team agreed"
    )
    meeting.note.write_text(text, encoding="utf-8")
    plan = meeting.plan(title="Launch Review", date=dt.date(2026, 10, 12))
    joined = " ".join(plan.warnings)
    assert "mention of 'Product Sync'" in joined and "'10-11'" in joined
    meeting.apply(plan)
    assert "Product Sync on 10-11 (2026-10-11)" in read_text(
        meeting.folder / "2026-10-12 - Launch Review.md"
    )


def test_edited_heading_and_date_line_are_left_alone(meeting: Meeting) -> None:
    text = (
        read_text(meeting.note)
        .replace("# Product Sync\n", "# My own heading\n")
        .replace("- **Date & Time:** 2026-10-11 14:00", "- **Date & Time:** Saturday afternoon")
    )
    meeting.note.write_text(text, encoding="utf-8")
    plan = meeting.plan(title="New", date=dt.date(2026, 10, 12))
    assert len([w for w in plan.warnings if "left as is" in w]) == 2
    meeting.apply(plan)
    new = read_text(meeting.folder / "2026-10-12 - New.md")
    assert "# My own heading\n" in new and "Saturday afternoon" in new


def test_bytes_outside_the_changed_lines_are_kept(meeting: Meeting) -> None:
    text = read_text(meeting.note)
    text = text.replace(
        "tags: [meeting, product]\n", "tags: [meeting, product]  # keep me\ncustom-key: {a: 1}\n"
    )
    text = "﻿" + text.replace("\n", "\r\n")
    meeting.note.write_bytes(text.encode("utf-8"))
    meeting.apply(meeting.plan(title="Bytes Kept", date=dt.date(2026, 10, 12)))
    new = (meeting.folder / "2026-10-12 - Bytes Kept.md").read_bytes().decode("utf-8")
    assert new.startswith("﻿---\r\n")
    old_lines, new_lines = text.split("\r\n"), new.split("\r\n")
    assert len(old_lines) == len(new_lines)
    changed = [(a, b) for a, b in zip(old_lines, new_lines, strict=True) if a != b]
    assert [a.split(":")[0] for a, _ in changed] == [
        "title",
        "date",
        "mm3-transcript",
        "# Product Sync",
        "- **Date & Time",
        "- **Transcript",
    ][: len(changed)]
    assert "tags: [meeting, product]  # keep me" in new and "custom-key: {a: 1}" in new
    assert parse_note(new).note.extra_properties["custom-key"] == {"a": 1}


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.text(min_size=1, max_size=60).filter(lambda s: s.strip()))
def test_any_title_gives_a_safe_name_and_reads_back(meeting: Meeting, title: str) -> None:
    plan = meeting.plan(title=title)
    if plan.empty or plan.blocked:
        return
    note = next(f for f in plan.files if f.role == "note")
    assert "/" not in note.new_rel.removeprefix("Meetings/2026/")
    assert parse_note(note.new_text or "").note.meta.title == " ".join(title.split())


# -- apply: database, changes during the preview -----------------------------------------------


def test_the_database_and_written_json_follow(meeting: Meeting) -> None:
    result = meeting.apply(meeting.plan(title="Launch Review", date=dt.date(2025, 3, 4)))
    new_note = meeting.root / "Meetings/2025/2025-03-04 - Launch Review.md"
    recents = RecentMeetingsRepository(meeting.db)
    (entry,) = recents.for_meeting(MM3_ID)
    assert entry.note_path == str(new_note) and entry.title == "Launch Review"
    assert entry.date == dt.date(2025, 3, 4) and entry.job_id == JOB
    assert entry.transcript_path == str(
        new_note.with_name("2025-03-04 - Launch Review.transcript.md")
    )
    job = JobRepository(meeting.db).get(JOB)
    assert job.title == "Launch Review" and job.meeting_date == dt.date(2025, 3, 4)
    assert job.settings["title"] == "Launch Review" and job.settings["meeting_date"] == "2025-03-04"
    written = json.loads((meeting.jobs / JOB / "written.json").read_text())
    assert written["note_path"] == str(new_note) and written["title"] == "Launch Review"
    assert written["note_relative"] == "Meetings/2025/2025-03-04 - Launch Review.md"
    backup = Path(result.backup)
    manifest = json.loads((backup / MANIFEST).read_text())
    assert manifest["outcome"] == "completed" and not (backup / JOURNAL).exists()
    assert manifest["db_before"]["title"] == "Product Sync"
    assert (backup / "files" / f"Meetings/2026/{STEM}.md").is_file()
    assert oct(backup.stat().st_mode & 0o777) == "0o700"


def test_backlinks_are_backed_up_and_rewritten(meeting: Meeting) -> None:
    daily = meeting.root / "Daily.md"
    daily.write_text(f"- [[{STEM}|sync]] and [[{STEM} (Transcript)]]\n")
    plan = meeting.plan(title="Launch")
    assert plan.link_count == 2 and len(plan.links) == 1
    result = meeting.apply(plan)
    assert daily.read_text() == (
        "- [[2026-10-11 - Launch|sync]] and [[2026-10-11 - Launch (Transcript)]]\n"
    )
    assert (Path(result.backup) / "files" / "Daily.md").read_text().startswith(f"- [[{STEM}|")


def test_a_change_after_the_preview_stops_the_rename(meeting: Meeting) -> None:
    daily = meeting.root / "Daily.md"
    daily.write_text(f"[[{STEM}]]\n")
    plan = meeting.plan(title="Launch")
    daily.write_text(f"[[{STEM}]] edited in Obsidian\n")
    before = meeting.snapshot()
    with pytest.raises(MM3Error) as exc:
        meeting.apply(plan)
    assert exc.value.code == "E_NOTE_CHANGED" and meeting.snapshot() == before
    fresh = meeting.plan(title="Launch")
    with pytest.raises(MM3Error) as exc:
        meeting.apply(fresh, expected_digest=plan.digest)
    assert exc.value.code == "E_NOTE_CHANGED"


def test_an_error_while_writing_is_rolled_back_at_once(meeting: Meeting) -> None:
    before = meeting.snapshot()
    plan = meeting.plan(title="Launch", date=dt.date(2025, 5, 5))

    def boom(step: str) -> None:
        if step.startswith("wrote") and "transcript.md" in step:
            raise OSError("disk full")

    with pytest.raises(OSError):
        meeting.apply(plan, step=boom)
    assert meeting.snapshot() == before
    assert RecentMeetingsRepository(meeting.db).for_meeting(MM3_ID)[0].note_path == str(
        meeting.note
    )
    (backup,) = backups_root(meeting.data).iterdir()
    assert json.loads((backup / MANIFEST).read_text())["outcome"] == "rolled back"


# -- journal: a crash after every step -------------------------------------------------------


class Crash(BaseException):
    """The process dies: nothing after this runs (no rollback)."""


def _fresh(base: Path) -> Meeting:
    base.mkdir(parents=True)
    return build_meeting(base)


STEPS = [
    "journal",
    "wrote note",
    "wrote companion",
    "wrote readable",
    "wrote Daily.md",
    "database",
    "committed",
    "removed note",
    "removed companion",
    "removed readable",
]


@pytest.mark.parametrize("crash_at", range(len(STEPS)), ids=STEPS)
def test_recovery_after_a_crash_at_every_step(tmp_path: Path, crash_at: int) -> None:
    m = _fresh(tmp_path / "run")
    (m.root / "Daily.md").write_text(f"[[{STEM}]]\n")
    before = m.snapshot()
    plan = m.plan(title="Launch", date=dt.date(2025, 5, 5))
    seen: list[str] = []

    def die(step: str) -> None:
        seen.append(step)
        if len(seen) - 1 == crash_at:
            raise Crash

    with pytest.raises(Crash):
        m.apply(plan, step=die)
    assert len(seen) == crash_at + 1
    if crash_at == len(STEPS) - 1:
        assert len(seen) == len(STEPS)  # every step of the rename was exercised
    (r,) = recover_renames(m.data, m.db, m.jobs)
    committed = "committed" in seen
    assert r.outcome == ("completed" if committed else "rolled back")
    entry = RecentMeetingsRepository(m.db).for_meeting(MM3_ID)[0]
    if committed:
        new = m.root / "Meetings/2025/2025-05-05 - Launch.md"
        assert new.is_file() and not m.note.exists() and entry.note_path == str(new)
        assert (m.root / "Daily.md").read_text() == "[[2025-05-05 - Launch]]\n"
        assert not list((m.root / "Meetings/2026").glob("*.md"))
    else:
        assert m.snapshot() == before and entry.note_path == str(m.note)
        assert JobRepository(m.db).get(JOB).title == "Product Sync"
    assert recover_renames(m.data, m.db, m.jobs) == []  # a second run is a no-op
    assert not list(backups_root(m.data).glob(f"*/{JOURNAL}"))
