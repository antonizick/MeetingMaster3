"""Title & date on the review page, and ``mm3 meetings rename`` (Phase 15d)."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from meetingmaster3.app import create_app
from meetingmaster3.cli import app as cli
from meetingmaster3.config.paths import resolve_paths
from meetingmaster3.config.settings import Settings
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.review.retitle import apply_retitle, plan_retitle
from meetingmaster3.review.store import ReviewStore, text_sha
from meetingmaster3.storage.db import Database
from meetingmaster3.storage.repositories import RecentMeetingsRepository
from meetingmaster3.vault.io import read_text
from tests.unit.web import test_review as review_tests
from tests.unit.web.test_review import (
    COMPANION,
    FIXTURE_ID,
    FIXTURES,
    JSON,
    NOTE,
    Workspace,
    edits_with,
    open_url,
)

ui = review_tests.ui
vault = review_tests.vault
fixture_note = review_tests.fixture_note

NEW_NOTE = "Meetings/2025/2025-12-30 - Launch Review.md"


def retitle(ws: Workspace, action: str, **body: Any) -> Any:
    fields = {"base_sha": ws.sha, "title": "Launch Review", "date": "2025-12-30", "time": ""}
    return ws.post(f"retitle/{action}", **{**fields, **body})


def test_preview_then_apply_moves_the_meeting_and_reopens_it(
    ui: TestClient, fixture_note: Path, vault: Path
) -> None:
    (vault / "Daily.md").write_text("Notes from [[2026-10-11 - Product Sync|the sync]].\n")
    ws = Workspace(ui, open_url(ui, "Meetings/2026/" + NOTE))
    assert 'id="btn-retitle"' in ws.html and 'id="dlg-retitle"' in ws.html
    r = retitle(ws, "preview")
    assert r.status_code == 200, r.text
    out = r.json()
    assert not out["blocked"] and not out["empty"]
    assert (
        "2025-12-30 - Launch Review.md" in out["html"] and "1 link in 1 other note" in out["html"]
    )
    assert read_text(fixture_note)  # the preview wrote nothing
    r = retitle(ws, "apply", digest=out["digest"])
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["note"] == NEW_NOTE and done["links"] == 1 and Path(done["backup"]).is_dir()
    assert parse_qs(urlparse(done["url"]).query)["path"] == [NEW_NOTE]
    assert not fixture_note.exists()
    assert (
        vault / "Daily.md"
    ).read_text() == "Notes from [[2025-12-30 - Launch Review|the sync]].\n"

    page = ui.get(done["url"])
    assert page.status_code == 200 and "<h1>Launch Review</h1>" in page.text
    again = Workspace(ui, done["url"])
    assert again.path == NEW_NOTE
    store = ReviewStore(ui.app.state.paths.data_dir, FIXTURE_ID)  # type: ignore[attr-defined]
    assert store.base(again.sha) == read_text(vault / NEW_NOTE)
    meetings = ui.get("/meetings").text
    assert "Launch Review" in meetings and "2025-12-30" in meetings
    (entry,) = RecentMeetingsRepository(ui.app.state.db).for_meeting(FIXTURE_ID)  # type: ignore[attr-defined]
    assert entry.note_path == str(vault / NEW_NOTE) and entry.date == dt.date(2025, 12, 30)


def test_apply_needs_a_fresh_preview(ui: TestClient, fixture_note: Path, vault: Path) -> None:
    ws = Workspace(ui, open_url(ui, "Meetings/2026/" + NOTE))
    r = retitle(ws, "apply")
    assert r.status_code == 422
    (vault / "Daily.md").write_text("[[2026-10-11 - Product Sync]]\n")
    digest = retitle(ws, "preview").json()["digest"]
    (vault / "Daily.md").write_text("[[2026-10-11 - Product Sync]] edited elsewhere\n")
    r = retitle(ws, "apply", digest=digest)
    assert r.status_code == 409 and r.json()["code"] == "E_NOTE_CHANGED"
    fixture_note.write_text(read_text(fixture_note) + "\nmore\n", encoding="utf-8")
    r = retitle(ws, "preview")
    assert r.status_code == 409 and r.json()["code"] == "E_NOTE_CHANGED"
    assert fixture_note.exists()


def test_a_collision_cannot_be_applied(ui: TestClient, fixture_note: Path, vault: Path) -> None:
    (vault / "Meetings/2025").mkdir(parents=True)
    (vault / NEW_NOTE).write_text("another note")
    ws = Workspace(ui, open_url(ui, "Meetings/2026/" + NOTE))
    out = retitle(ws, "preview").json()
    assert out["blocked"] and "already exists" in out["html"] and "retitle-apply" not in out["html"]
    r = retitle(ws, "apply", digest=out["digest"])
    assert r.status_code == 409 and r.json()["code"] == "E_RETITLE_TARGET_EXISTS"
    assert (vault / NEW_NOTE).read_text() == "another note"


def test_unsaved_draft_refuses_and_inputs_are_checked(ui: TestClient, fixture_note: Path) -> None:
    ws = Workspace(ui, open_url(ui, "Meetings/2026/" + NOTE))
    bad = retitle(ws, "preview", time="25:99")
    assert bad.status_code == 422
    assert retitle(ws, "preview", title=" ").status_code == 422
    assert retitle(ws, "preview", date="2026-13-01").status_code == 422
    digest = retitle(ws, "preview").json()["digest"]
    assert (
        ws.post("draft", base_sha=ws.sha, edits=edits_with(read_text(fixture_note))).status_code
        == 200
    )
    r = retitle(ws, "apply", digest=digest)
    assert r.status_code == 409 and r.json()["code"] == "E_UNSAVED_EDITS"


def test_read_only_and_note_only_notes_can_be_renamed(
    ui: TestClient, fixture_note: Path, vault: Path
) -> None:
    (fixture_note.parent / COMPANION).unlink()
    text = read_text(fixture_note)
    plain = "\n".join(ln for ln in text.split("\n") if "<!-- " not in ln)
    fixture_note.write_text(plain, encoding="utf-8")
    ws = Workspace(ui, open_url(ui, "Meetings/2026/" + NOTE))
    assert ws.data["readonly"] and 'id="btn-retitle"' in ws.html
    assert "only the note and its archives are renamed" in ws.html
    out = retitle(ws, "preview").json()
    assert "no companion transcript" in out["html"]
    assert retitle(ws, "apply", digest=out["digest"]).status_code == 200
    assert parse_note(read_text(vault / NEW_NOTE)).note.meta.title == "Launch Review"


@pytest.mark.parametrize("action", ["retitle/preview", "retitle/apply"])
def test_retitle_routes_need_csrf(ui: TestClient, action: str) -> None:
    token = ui.headers.pop("X-CSRF-Token")
    try:
        r = ui.post(f"/ui/review/{FIXTURE_ID}/{action}", json={}, headers=JSON)
    finally:
        ui.headers["X-CSRF-Token"] = token
    assert r.status_code == 403


def test_preview_escapes_the_title(ui: TestClient, fixture_note: Path) -> None:
    ws = Workspace(ui, open_url(ui, "Meetings/2026/" + NOTE))
    html = retitle(ws, "preview", title="<img src=x onerror=alert(1)>").json()["html"]
    assert "<img" not in html and "&lt;img" in html


def _meeting_in(root: Path) -> Path:
    folder = root / "Meetings" / "2026"
    folder.mkdir(parents=True)
    for name in (NOTE, COMPANION):
        shutil.copyfile(FIXTURES / name, folder / name)
    return folder / NOTE


def test_an_interrupted_rename_is_recovered_at_start_up(tmp_path: Path) -> None:
    root = (tmp_path / "vault").resolve()
    note = _meeting_in(root)
    paths = resolve_paths()
    paths.ensure()
    db = Database.open(paths.database)
    plan = plan_retitle(root, note, title="Recovered", output_subfolder="Meetings/{yyyy}/")

    class Crash(BaseException):
        pass

    def die(step: str) -> None:
        if step == "committed":
            raise Crash

    with pytest.raises(Crash):
        apply_retitle(plan, data_dir=paths.data_dir, db=db, jobs_root=paths.jobs_dir, step=die)
    db.close()
    settings = Settings()
    settings.vault.path = root
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        page = client.get("/meetings").text
    assert "was completed" in page and "Recovered" in page
    assert (note.parent / "2026-10-11 - Recovered.md").is_file() and not note.exists()


# -- CLI -------------------------------------------------------------------------------------------

runner = CliRunner()


def test_cli_dry_run_then_apply(tmp_path: Path) -> None:
    root = (tmp_path / "vault").resolve()
    note = _meeting_in(root)
    (root / "Daily.md").write_text("[[2026-10-11 - Product Sync]]\n")
    args = ["meetings", "rename", "Meetings/2026/" + NOTE, "--vault", str(root)]
    r = runner.invoke(cli, [*args, "--title", "CLI Title", "--date", "2025-01-02", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "'Product Sync' -> 'CLI Title'" in r.output and "Dry run" in r.output
    assert "Meetings/2025/2025-01-02 - CLI Title.md" in r.output and "links: 1 in 1" in r.output
    assert note.exists()
    r = runner.invoke(cli, [*args, "--title", "CLI Title", "--date", "2025-01-02", "--yes"])
    assert r.exit_code == 0, r.output
    assert "Renamed: Meetings/2025/2025-01-02 - CLI Title.md" in r.output
    assert not note.exists() and (root / "Daily.md").read_text() == "[[2025-01-02 - CLI Title]]\n"


def test_cli_finds_a_meeting_by_id_and_refuses_bad_input(tmp_path: Path) -> None:
    root = (tmp_path / "vault").resolve()
    _meeting_in(root)
    r = runner.invoke(
        cli, ["meetings", "rename", FIXTURE_ID, "--vault", str(root), "--time", "08:15", "-y"]
    )
    assert r.exit_code == 0, r.output
    text = read_text(root / "Meetings/2026" / NOTE)
    assert "- **Date & Time:** 2026-10-11 08:15" in text and text_sha(text)
    assert (
        runner.invoke(cli, ["meetings", "rename", FIXTURE_ID, "--vault", str(root)]).exit_code == 1
    )
    bad = runner.invoke(
        cli, ["meetings", "rename", FIXTURE_ID, "--vault", str(root), "--date", "x"]
    )
    assert bad.exit_code == 1 and "Not a date" in bad.output
