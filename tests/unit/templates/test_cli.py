"""``mm3 process`` and ``mm3 templates`` (headless entry points)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from meetingmaster3.cli import app
from meetingmaster3.errors import MM3Error
from meetingmaster3.headless import ProcessRequest, answer_for, build_options, parse_speakers
from tests.unit.jobs.helpers import make_tone, requires_ffmpeg

cli = CliRunner()


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    return root.resolve()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")


def test_templates_list() -> None:
    r = cli.invoke(app, ["templates", "list"])
    assert r.exit_code == 0, r.output
    assert "* ok      executive-summary" in r.output
    assert r.output.count(" ok ") == 5


def test_templates_validate(tmp_path: Path) -> None:
    good = cli.invoke(app, ["templates", "validate"])
    assert good.exit_code == 0 and good.output.count("ok") == 5
    bad = tmp_path / "bad.md"
    bad.write_text("---\nmm3-template: 1\nid: Bad Id\n---\n", encoding="utf-8")
    r = cli.invoke(app, ["templates", "validate", str(bad)])
    assert r.exit_code == 1
    assert "INVALID" in r.output and "bad.md:3:" in r.output and "[schema_error]" in r.output


def test_templates_install(vault: Path) -> None:
    r = cli.invoke(app, ["templates", "install", "--vault", str(vault)])
    assert r.exit_code == 0, r.output
    assert r.output.count("installed") == 5
    again = cli.invoke(app, ["templates", "install", "--vault", str(vault)])
    assert again.output.count("unchanged") == 5
    missing = cli.invoke(app, ["templates", "install", "--vault", str(vault / "nope")])
    assert missing.exit_code == 1 and "does not exist" in missing.output


@requires_ffmpeg
def test_process_writes_note(tmp_path: Path, vault: Path, fake: None) -> None:
    audio = make_tone(tmp_path / "2026-10-09 Launch Review.wav", 2.0)
    r = cli.invoke(
        app,
        [
            "process", str(audio), "--vault", str(vault), "--template", "action-focused",
            "--speakers", "SPEAKER_00=Alice,SPEAKER_01=Bob", "--time", "09:15",
            "--tags", "launch, product", "--location", "Zoom",
        ],
    )  # fmt: skip
    assert r.exit_code == 0, r.output
    assert "await_speaker_confirmation: waiting" in r.output and "write: completed" in r.output
    note = vault / "Meetings" / "2026" / "2026-10-09 - Launch Review.md"
    assert f"Note:       {note}" in r.output
    text = note.read_text("utf-8")
    assert "mm3-template: action-focused" in text and "tags: [meeting, launch, product]" in text
    assert "- **Date & Time:** 2026-10-09 09:15" in text
    assert "participants: [Alice, Bob]" in text
    assert (vault / "Meetings" / "2026" / "2026-10-09 - Launch Review.transcript.md").is_file()


@requires_ffmpeg
def test_process_without_speakers_and_no_tty_fails_clearly(
    tmp_path: Path, vault: Path, fake: None
) -> None:
    audio = make_tone(tmp_path / "meeting.wav", 1.0)
    r = cli.invoke(app, ["process", str(audio), "--vault", str(vault)])
    assert r.exit_code == 1
    assert "no terminal to ask" in r.output and "--speakers" in r.output
    assert not list(vault.rglob("*.transcript.md"))


def test_process_needs_a_vault_before_starting(tmp_path: Path) -> None:
    audio = tmp_path / "x.wav"
    audio.write_bytes(b"RIFF")
    r = cli.invoke(app, ["process", str(audio)])
    assert r.exit_code == 1 and "No Obsidian vault is configured" in r.output


def test_process_rejects_bad_date(tmp_path: Path, vault: Path) -> None:
    audio = tmp_path / "x.wav"
    audio.write_bytes(b"RIFF")
    r = cli.invoke(app, ["process", str(audio), "--vault", str(vault), "--date", "11/10/2026"])
    assert r.exit_code == 1 and "Invalid date or time" in r.output


def test_parse_speakers() -> None:
    assert parse_speakers("SPEAKER_00=Alice Chen, SPEAKER_01 = Bob") == {
        "SPEAKER_00": "Alice Chen",
        "SPEAKER_01": "Bob",
    }
    assert parse_speakers("") == {}
    with pytest.raises(MM3Error):
        parse_speakers("SPEAKER_00")


def test_build_options_uses_the_file_name(tmp_path: Path) -> None:
    opts = build_options(tmp_path / "2026-10-11 1430 Product Sync.m4a", title=None, date=None)
    assert opts.title == "Product Sync" and str(opts.meeting_date) == "2026-10-11"
    assert opts.meeting_time is not None and opts.meeting_time.hour == 14
    explicit = build_options(tmp_path / "x.wav", title="Other", date=None, tags=[])
    assert explicit.title == "Other" and explicit.tags == []


def test_answer_for() -> None:
    req = ProcessRequest(Path("x"), build_options(Path("x.wav"), title="t", date=None), None)
    with pytest.raises(MM3Error) as err:
        answer_for("cloud_consent", {}, req, None)
    assert "--cloud-consent" in err.value.hint
    req.cloud_consent = True
    assert answer_for("cloud_consent", {}, req, None) == {"consent": True}
    req.speakers = {"SPEAKER_00": "A"}
    assert answer_for("speaker_confirmation", {}, req, None) == {"speakers": {"SPEAKER_00": "A"}}
    assert answer_for("language", {}, req, lambda k, p: {"action": "abort"}) == {"action": "abort"}
