"""The optional copy of retained audio into the vault (R8)."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from meetingmaster3.config.settings import Settings
from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.note import Note
from meetingmaster3.jobs.vault_audio import copy_audio_to_vault
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.note_writer import render_note
from meetingmaster3.storage.db import Database
from meetingmaster3.storage.repositories import JobRepository


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Settings, Path, object, Path]:
    vault = (tmp_path / "vault").resolve()
    (vault / "Meetings").mkdir(parents=True)
    note_path = vault / "Meetings" / "2026-10-11 - Sync.md"
    note_path.write_text(render_note(Note(meta=MeetingMeta(id=uuid.uuid4(), title="Sync"))))
    jobs = JobRepository(Database.open(":memory:"))
    job = jobs.create(str(uuid.uuid4()), stages=["write"], source_filename="a.opus")
    jobs_root = tmp_path / "jobs"
    folder = jobs_root / job.id
    folder.mkdir(parents=True)
    (folder / "audio.opus").write_bytes(b"OPUS")
    (folder / "written.json").write_text(json.dumps({"note_path": str(note_path)}))
    settings = Settings()
    settings.vault.path = vault
    settings.privacy.copy_audio_to_vault = True
    return settings, jobs_root, job, note_path


def test_copies_audio_and_links_it_from_the_note(
    setup: tuple[Settings, Path, object, Path],
) -> None:
    settings, jobs_root, job, note_path = setup
    relative = copy_audio_to_vault(jobs_root, job, settings)  # type: ignore[arg-type]
    assert relative == "Meetings/attachments/2026-10-11 - Sync.opus"
    assert (settings.vault.path / relative).read_bytes() == b"OPUS"  # type: ignore[operator]
    assert parse_note(note_path.read_text()).note.meta.audio_ref == relative
    assert "mm3-audio" in note_path.read_text()


def test_does_nothing_when_off(setup: tuple[Settings, Path, object, Path]) -> None:
    settings, jobs_root, job, note_path = setup
    settings.privacy.copy_audio_to_vault = False
    before = note_path.read_text()
    assert copy_audio_to_vault(jobs_root, job, settings) is None  # type: ignore[arg-type]
    assert note_path.read_text() == before
    assert not (settings.vault.path / "Meetings" / "attachments").exists()  # type: ignore[operator]


def test_failure_never_raises(setup: tuple[Settings, Path, object, Path]) -> None:
    settings, jobs_root, job, _ = setup
    settings.vault.attachments_subfolder = "../outside"
    assert copy_audio_to_vault(jobs_root, job, settings) is None  # type: ignore[arg-type]
