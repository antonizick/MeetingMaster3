"""Bringing older notes up to date (Phase 15a, R25): planner, applier, CLI and the web card."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from meetingmaster3.config.settings import BackendConfig, Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.base import GenerateRequest
from meetingmaster3.llm.fake import FakeLLMBackend
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.sections import scan_sections
from meetingmaster3.review import upgrade
from meetingmaster3.review.upgrade import apply_note, plan_note, plan_vault, scan_notes
from meetingmaster3.templates.loader import load_library
from meetingmaster3.vault.io import read_text

FIXTURES = Path(__file__).parents[1] / "fixtures" / "notes"
NOTE = "2026-10-11 - Product Sync.md"
COMPANION = "2026-10-11 - Product Sync.transcript.md"
FIXTURE_ID = "3f2b8c1e-7d4a-4e9b-a6c2-5b1d0e8f9a71"
DETAILED = "The meeting set the launch.\n\nAlice and Bob discussed the flag.\n\nAnalytics is open."


def respond(req: GenerateRequest) -> str:
    return DETAILED if "Summary Detailed" in req.messages[0].content else "Short."


@pytest.fixture
def note(vault: Path) -> Path:
    folder = vault / "Meetings" / "2026"
    folder.mkdir(parents=True)
    for name in (NOTE, COMPANION):
        shutil.copyfile(FIXTURES / name, folder / name)
    return folder / NOTE


@pytest.fixture
def settings(vault: Path) -> Settings:
    s = Settings()
    s.vault.path = vault
    return s


async def apply(vault: Path, note: Path, settings: Settings, **kw: Any) -> upgrade.NoteResult:
    plan = plan_note(vault, note, load_library(), settings)
    backend = kw.pop("backend", FakeLLMBackend(responder=respond))
    return await apply_note(
        vault, plan, library=load_library(), settings=settings, backend=backend,
        backend_name="ollama", model="fake-model", **kw,
    )  # fmt: skip


def test_plan_writes_nothing(vault: Path, note: Path, settings: Settings) -> None:
    before = {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    plan = plan_vault(vault, load_library(), settings)
    assert [n.rel for n in plan.notes] == [f"Meetings/2026/{NOTE}"]
    n = plan.notes[0]
    assert n.add_sections == ("summary-detailed",) and n.rename_heading and n.write_readable
    assert n.needed and n.needs_model and n.mm3_id == FIXTURE_ID
    assert plan.counts()["todo"] == 1 and plan.estimate_seconds() > 0
    assert {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()} == before


async def test_apply_adds_renames_links_archives_and_is_idempotent(
    vault: Path, note: Path, settings: Settings
) -> None:
    original = read_text(note)
    result = await apply(vault, note, settings)
    assert result.status == "updated" and result.added == ["Summary Detailed"]
    text = read_text(note)
    parsed = parse_note(text)
    ids = [s.id for s in parsed.note.sections]
    assert ids[:2] == ["summary", "summary-detailed"] and scan_sections(text).ok
    assert parsed.note.section("summary").title == "Summary Succinct"  # type: ignore[union-attr]
    assert parsed.note.section("summary-detailed").body_markdown == DETAILED  # type: ignore[union-attr]
    # every other byte of the note is kept
    assert text.replace("## Summary Succinct", "## Summary").count("\n") > original.count("\n")
    assert original.split("<!-- mm3:section:decisions -->")[1] in text
    # readable transcript written and linked from the header
    readable = note.with_name("2026-10-11 - Product Sync (Transcript).md")
    assert readable.is_file() and result.readable == f"Meetings/2026/{readable.name}"
    assert f"- **Transcript:** [[{readable.stem}|Read the transcript]]\n" in text
    # the previous version is archived
    assert result.archive is not None
    archived = read_text(vault / result.archive)
    assert "mm3-archived:" in archived and "## Summary\n" in archived
    # a second run changes nothing
    again = await apply(vault, note, settings)
    assert again.status == "unchanged" and read_text(note) == text
    assert plan_note(vault, note, load_library(), settings).needed is False


async def test_user_renamed_heading_is_kept(vault: Path, note: Path, settings: Settings) -> None:
    note.write_text(read_text(note).replace("## Summary\n", "## TL;DR\n"), encoding="utf-8")
    plan = plan_note(vault, note, load_library(), settings)
    assert not plan.rename_heading
    await apply(vault, note, settings)
    assert "## TL;DR\n" in read_text(note) and "## Summary Succinct" not in read_text(note)


async def test_edit_during_the_run_is_never_overwritten(
    vault: Path, note: Path, settings: Settings
) -> None:
    def edit_while_generating(req: GenerateRequest) -> str:
        note.write_text(read_text(note) + "\nTyped in Obsidian.\n", encoding="utf-8")
        return respond(req)

    result = await apply(
        vault, note, settings, backend=FakeLLMBackend(responder=edit_while_generating)
    )
    assert result.status == "skipped" and "changed while" in result.message
    assert read_text(note).endswith("Typed in Obsidian.\n")
    assert "summary-detailed" not in read_text(note)
    assert not (note.parent / "Archive").exists()


async def test_missing_companion_is_skipped(vault: Path, note: Path, settings: Settings) -> None:
    (note.parent / COMPANION).unlink()
    plan = plan_note(vault, note, load_library(), settings)
    assert plan.skip is not None and "companion transcript" in plan.skip
    result = await apply(vault, note, settings)
    assert result.status == "skipped"


async def test_cloud_backend_needs_consent(vault: Path, note: Path, settings: Settings) -> None:
    cloud = FakeLLMBackend(id="openrouter", is_local=False, responder=respond)
    with pytest.raises(MM3Error) as err:
        await apply(vault, note, settings, backend=cloud)
    assert err.value.code == "E_CONSENT_REQUIRED" and cloud.calls == []
    assert "summary-detailed" not in read_text(note)
    result = await apply(vault, note, settings, backend=cloud, cloud_consent=True)
    assert result.status == "updated"


async def test_readable_only_when_enabled(vault: Path, note: Path, settings: Settings) -> None:
    settings.generation.readable_transcript = False
    plan = plan_note(vault, note, load_library(), settings)
    assert not plan.write_readable
    await apply(vault, note, settings)
    assert not note.with_name("2026-10-11 - Product Sync (Transcript).md").exists()


async def test_templates_that_gained_both_summaries(
    vault: Path, note: Path, settings: Settings
) -> None:
    text = read_text(note).replace(
        "mm3-template: executive-summary", "mm3-template: just-the-facts"
    )
    text = re.sub(
        r"<!-- mm3:section:summary -->.*?<!-- /mm3:section:summary -->\n\n", "", text, flags=re.S
    )
    note.write_text(text, encoding="utf-8")
    plan = plan_note(vault, note, load_library(), settings)
    assert plan.add_sections == ("summary", "summary-detailed") and not plan.rename_heading
    await apply(vault, note, settings)
    ids = [s.id for s in parse_note(read_text(note)).note.sections]
    assert ids[:3] == ["summary", "summary-detailed", "decisions"]


def test_scan_skips_archives_transcripts_and_other_files(vault: Path, note: Path) -> None:
    (vault / "Plain.md").write_text("# not MM3\n")
    archive = note.parent / "Archive"
    archive.mkdir()
    (archive / "old.md").write_text(read_text(note).replace("---\n", "---\nmm3-archived: x\n", 1))
    hidden = vault / ".trash"
    hidden.mkdir()
    shutil.copyfile(note, hidden / NOTE)
    assert scan_notes(vault) == [note]


def test_cli_dry_run_and_apply(vault: Path, note: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from meetingmaster3 import cli

    settings = Settings()
    settings.vault.path = vault
    settings.llm.backends["ollama"] = BackendConfig(kind="ollama", default_model="fake-model")
    settings.save()  # the isolated XDG config of the test
    fake = FakeLLMBackend(id="ollama", responder=respond)
    monkeypatch.setattr(
        "meetingmaster3.llm.registry.BackendRegistry.get", lambda self, n=None: fake
    )
    runner = CliRunner()
    before = read_text(note)
    out = runner.invoke(cli.app, ["notes", "upgrade", "--dry-run", "--vault", str(vault)])
    assert out.exit_code == 0, out.output
    assert "1 to update" in out.output and "Dry run: nothing was written." in out.output
    assert read_text(note) == before
    out = runner.invoke(cli.app, ["notes", "upgrade", "--vault", str(vault)])
    assert out.exit_code == 0, out.output
    assert "updated" in out.output and "summary-detailed" in read_text(note)
    out = runner.invoke(cli.app, ["notes", "upgrade", "--vault", str(vault)])
    assert "0 to update" in out.output


# -- web card ------------------------------------------------------------------------------------


@pytest.fixture
def fake_llm(ui: TestClient, monkeypatch: pytest.MonkeyPatch) -> FakeLLMBackend:
    """A scripted model through the app's registry (the real path, not MM3_FAKE_PIPELINE)."""
    monkeypatch.delenv("MM3_FAKE_PIPELINE")
    fake = FakeLLMBackend(id="ollama", responder=respond)
    registry = ui.app.state.llm_registry  # type: ignore[attr-defined]
    monkeypatch.setattr(registry, "get", lambda name=None: fake)
    ui.app.state.settings.llm.backends["ollama"] = BackendConfig(  # type: ignore[attr-defined]
        kind="ollama", default_model="fake-model"
    )
    return fake


def test_card_preview_run_and_results(ui: TestClient, note: Path, fake_llm: FakeLLMBackend) -> None:
    assert 'hx-get="/ui/notes/upgrade"' in ui.get("/meetings").text
    card = ui.get("/ui/notes/upgrade").text
    assert "Update older notes" in card and "Summary Detailed" in card
    assert "ollama · fake-model" in card and "Estimated time" in card
    before = read_text(note)
    preview = ui.post("/ui/notes/upgrade/preview", data={"path": f"Meetings/2026/{NOTE}"})
    assert preview.status_code == 200 and "Alice and Bob discussed the flag." in preview.text
    assert "Nothing has been written" in preview.text and read_text(note) == before

    started = ui.post("/ui/notes/upgrade/start")
    assert started.status_code == 200
    for _ in range(100):
        status = ui.get("/ui/notes/upgrade/status").text
        if "Done." in status:
            break
    assert "Done." in status and "1 of 1 notes updated" in status
    assert "/open/note?path=Meetings%2F2026%2F" in status and "Archive" in status
    assert "summary-detailed" in read_text(note)
    card = ui.get("/ui/notes/upgrade").text
    assert "Done." in card and "Update 1 note" not in card


def test_card_is_hidden_when_everything_is_up_to_date(ui: TestClient) -> None:
    assert ui.get("/ui/notes/upgrade").text.strip() == ""


def test_cloud_default_must_ask(
    ui: TestClient, note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cloud = FakeLLMBackend(id="openrouter", is_local=False, responder=respond)
    registry = ui.app.state.llm_registry  # type: ignore[attr-defined]
    monkeypatch.setattr(registry, "get", lambda name=None: cloud)
    s = ui.app.state.settings  # type: ignore[attr-defined]
    s.llm.backends["openrouter"] = BackendConfig(
        kind="openrouter", api_key="sk-test", default_model="m"
    )
    s.llm.default_backend = "openrouter"
    card = ui.get("/ui/notes/upgrade").text
    assert 'name="cloud_consent"' in card and "a cloud service" in card
    refused = ui.post("/ui/notes/upgrade/start", headers={"Accept": "application/json"})
    assert refused.status_code == 409 and cloud.calls == []


def test_upgrade_routes_need_csrf(ui: TestClient, note: Path) -> None:
    del ui.headers["X-CSRF-Token"]
    for path in ("/ui/notes/upgrade/start", "/ui/notes/upgrade/cancel"):
        assert ui.post(path).status_code == 403
