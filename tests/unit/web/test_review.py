"""The review workspace routes (Phase 11), JS-free, against the fake pipeline and fixtures."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

import pytest
from fastapi.testclient import TestClient

from meetingmaster3.app import create_app
from meetingmaster3.config.settings import BackendConfig, Settings
from meetingmaster3.jobs.files import audio_files, job_dir
from meetingmaster3.markdown.editing import edits_of, split_document
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.sections import scan_sections
from meetingmaster3.review.store import text_sha
from meetingmaster3.vault.io import read_text
from tests.unit.jobs.helpers import make_tone, requires_ffmpeg
from tests.unit.jobs.test_jobs_api import upload, wait

FIXTURES = Path(__file__).parents[2] / "fixtures" / "notes"
NOTE = "2026-10-11 - Product Sync.md"
COMPANION = "2026-10-11 - Product Sync.transcript.md"
FIXTURE_ID = "3f2b8c1e-7d4a-4e9b-a6c2-5b1d0e8f9a71"
SPEAKERS = {"SPEAKER_00": {"name": "Alice"}, "SPEAKER_01": {"name": "Bob"}}
JSON = {"Accept": "application/json"}


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    return root.resolve()


@pytest.fixture
def ui(vault: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    settings = Settings()
    settings.vault.path = vault
    settings.llm.backends["openrouter"] = BackendConfig(kind="openrouter", api_key="sk-test")
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        client.get("/healthz")
        client.headers["X-CSRF-Token"] = client.cookies["mm3_csrf"]
        yield client


@pytest.fixture
def fixture_note(vault: Path) -> Path:
    folder = vault / "Meetings" / "2026"
    folder.mkdir(parents=True)
    for name in (NOTE, COMPANION):
        shutil.copyfile(FIXTURES / name, folder / name)
    return folder / NOTE


@pytest.fixture(scope="module")
def tone(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_tone(tmp_path_factory.mktemp("audio") / "2026-10-11 Product Sync.m4a", 20.0)


class Workspace:
    """What the browser knows about an open note."""

    def __init__(self, client: TestClient, url: str) -> None:
        self.client = client
        page = client.get(url)
        assert page.status_code == 200, page.text
        self.html = page.text
        self.mm3_id = url.split("/meetings/")[1].split("?")[0]
        data = re.search(
            r'<script type="application/json" id="review-data">(.*?)</script>', page.text, re.S
        )
        assert data
        self.data = json.loads(data.group(1))
        self.path: str = self.data["path"]
        self.sha: str = self.data["base_sha"]

    def post(self, action: str, **body: Any) -> Any:
        return self.client.post(
            f"/ui/review/{self.mm3_id}/{action}", json={"path": self.path, **body}, headers=JSON
        )


def open_url(client: TestClient, rel: str) -> str:
    r = client.get(f"/open/note?path={quote(rel)}", follow_redirects=False)
    assert r.status_code == 303, r.text
    return str(r.headers["location"])


def processed(client: TestClient, tone: Path, vault: Path, **options: Any) -> tuple[str, Path]:
    job = upload(client, tone, options).json()
    wait(client, job["id"], "waiting_for_input")
    assert client.post(f"/api/jobs/{job['id']}/speakers", json=SPEAKERS).status_code == 200
    wait(client, job["id"], "written")
    page = client.get(f"/jobs/{job['id']}").text
    link = re.search(r'href="(/meetings/[^"]+)"', page)
    assert link, page
    url = link.group(1).replace("&amp;", "&")
    rel = parse_qs(urlparse(url).query)["path"][0]
    return url, vault / rel


def edits_with(text: str, **sections: str) -> dict[str, Any]:
    e = edits_of(split_document(text))
    return {
        "texts": list(e.texts),
        "sections": {**e.sections, **sections},
        "frontmatter": e.frontmatter,
    }


# -- open and render -------------------------------------------------------------------------------


@requires_ffmpeg
def test_completion_and_recent_links_open_the_workspace(
    ui: TestClient, tone: Path, vault: Path
) -> None:
    url, note = processed(ui, tone, vault)
    assert url.startswith("/meetings/") and "path=Meetings/" in url
    ws = Workspace(ui, url)
    assert ws.data["can_regenerate"] and not ws.data["readonly"] and ws.data["draft"] is None
    assert 'id="audio"' in ws.html and "/api/jobs/" in ws.html
    assert ws.html.count('class="seg"') == 5 and "Alice" in ws.html
    assert ws.html.count('data-kind="section"') == len(parse_note(read_text(note)).note.sections)
    assert ws.sha == text_sha(read_text(note))
    recent = ui.get("/meetings").text
    assert "/open/note?path=Meetings%2F2026%2F" in recent
    assert ui.get("/open").status_code == 200


def test_fixture_note_opens_without_audio(ui: TestClient, fixture_note: Path, vault: Path) -> None:
    url = open_url(ui, f"Meetings/2026/{NOTE}")
    assert url.startswith(f"/meetings/{FIXTURE_ID}?path=")
    ws = Workspace(ui, url)
    assert 'id="audio"' not in ws.html and "No recording is linked" in ws.html
    assert "Alice Chen" in ws.html and 'id="transcript"' in ws.html
    # The marker lines are shown but are not editable text.
    assert "&lt;!-- mm3:section:summary --&gt;</code>" in ws.html
    textareas = re.findall(r"<textarea[^>]*>(.*?)</textarea>", ws.html, re.S)
    assert textareas and not any("mm3:section" in t for t in textareas)
    # Reopening by id alone works through the Recent list.
    assert ui.get(f"/meetings/{FIXTURE_ID}").status_code == 200


def test_workspace_not_found_and_bad_ids(ui: TestClient, fixture_note: Path) -> None:
    assert ui.get("/meetings/not-a-uuid", headers=JSON).json()["code"] == "E_NOTE_NOT_FOUND"
    r = ui.get("/meetings/00000000-0000-4000-8000-000000000000", headers=JSON)
    assert r.status_code == 404
    r = ui.get(f"/meetings/{FIXTURE_ID}?path=../../etc/passwd", headers=JSON)
    assert r.json()["code"] == "vault_path_escape"


def test_open_note_routes_by_kind(ui: TestClient, fixture_note: Path, vault: Path) -> None:
    plain = vault / "plain.md"
    plain.write_text("# Plain\n", encoding="utf-8")
    r = ui.get("/open/note?path=plain.md", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/preview?path=")
    assert "not a MeetingMaster3 note" in ui.get(r.headers["location"]).text
    r = ui.get(f"/open/note?path={quote('Meetings/2026/' + COMPANION)}", follow_redirects=False)
    assert r.headers["location"].startswith("/preview?path=")
    archived = vault / "Meetings" / "2026" / "old.md"
    archived.write_text(f"---\nmm3-id: {FIXTURE_ID}\nmm3-archived: 2026-10-11\n---\n", "utf-8")
    assert ui.get("/open/note?path=Meetings/2026/old.md", headers=JSON).status_code == 409
    assert ui.get("/open/note?path=../x.md", headers=JSON).json()["code"] == "vault_path_escape"


def test_picker_lists_notes_and_cannot_escape(ui: TestClient, fixture_note: Path) -> None:
    root = ui.get("/ui/open/browse").text
    assert "Meetings" in root
    listing = ui.get("/ui/open/browse?dir=Meetings/2026").text
    assert (
        "Product Sync" in listing and "transcript" not in listing.lower().split("product sync")[-1]
    )
    for bad in ("..", "/etc", "Meetings/../../.."):
        r = ui.get(f"/ui/open/browse?dir={quote(bad)}", headers=JSON)
        assert r.json()["code"] == "vault_path_escape", bad


def test_note_without_markers_is_read_only(ui: TestClient, vault: Path) -> None:
    (vault / "bare.md").write_text(
        f"---\nmm3-id: {FIXTURE_ID}\ntitle: Bare\n---\n# Bare\n\nJust text [01:05].\n", "utf-8"
    )
    ws = Workspace(ui, open_url(ui, "bare.md"))
    assert ws.data["readonly"] and 'id="editor"' not in ws.html
    assert "no MeetingMaster3 section markers" in ws.html
    assert 'class="ts-link" data-t="65"' in ws.html


# -- save ------------------------------------------------------------------------------------------


def test_save_changes_only_the_edited_section(ui: TestClient, fixture_note: Path) -> None:
    ws = Workspace(ui, open_url(ui, f"Meetings/2026/{NOTE}"))
    before = read_text(fixture_note)
    r = ws.post(
        "save",
        base_sha=ws.sha,
        edits=edits_with(before, decisions="## Decisions Made\n\n- Edited by hand.\n"),
    )
    assert r.status_code == 200, r.text
    after = read_text(fixture_note)
    assert r.json()["sha"] == text_sha(after) and r.json()["written"]
    old, new = scan_sections(before).get("decisions"), scan_sections(after).get("decisions")
    assert old and new
    assert after[: new.inner_start] == before[: old.inner_start]
    assert after[new.inner_end :] == before[old.inner_end :]
    assert after[new.inner_start : new.inner_end] == "## Decisions Made\n\n- Edited by hand.\n"


def test_save_detects_external_modification(ui: TestClient, fixture_note: Path) -> None:
    ws = Workspace(ui, open_url(ui, f"Meetings/2026/{NOTE}"))
    before = read_text(fixture_note)
    fixture_note.write_text(before + "\nAdded in Obsidian.\n", encoding="utf-8")
    edits = edits_with(before, summary="## Summary\n\nMine.\n")
    r = ws.post("save", base_sha=ws.sha, edits=edits)
    assert r.status_code == 409 and r.json()["code"] == "E_NOTE_CHANGED"
    conflict = r.json()["conflict"]
    assert "Added in Obsidian." in conflict["html"] and "Mine." in conflict["html"]
    assert read_text(fixture_note).endswith("Added in Obsidian.\n")  # nothing written
    r = ws.post("save", base_sha=ws.sha, edits=edits, force_sha=conflict["theirs_sha"])
    assert r.status_code == 200 and "Mine." in read_text(fixture_note)
    assert "Added in Obsidian." not in read_text(fixture_note)


def test_save_marker_rules(ui: TestClient, fixture_note: Path) -> None:
    ws = Workspace(ui, open_url(ui, f"Meetings/2026/{NOTE}"))
    text = read_text(fixture_note)
    bad = edits_with(text, summary="## Summary\n\n<!-- /mm3:section:summary -->\n")
    assert ws.post("save", base_sha=ws.sha, edits=bad).json()["code"] == "E_MARKER_EDIT"
    edits = edits_with(text)
    edits["texts"][-1] += "<!-- mm3:section:extra -->\n"
    r = ws.post("save", base_sha=ws.sha, edits=edits)
    assert r.status_code == 409 and r.json()["details"]["confirm"] is True
    assert read_text(fixture_note) == text
    r = ws.post("save", base_sha=ws.sha, edits=edits, allow_marker_changes=True)
    assert r.status_code == 200 and read_text(fixture_note).endswith("<!-- mm3:section:extra -->\n")


def test_draft_autosave_restore_and_discard(ui: TestClient, fixture_note: Path) -> None:
    url = open_url(ui, f"Meetings/2026/{NOTE}")
    ws = Workspace(ui, url)
    text = read_text(fixture_note)
    edits = edits_with(text, summary="## Summary\n\nDraft text.\n")
    assert ws.post("draft", base_sha=ws.sha, edits=edits).status_code == 200
    again = Workspace(ui, url)
    draft = again.data["draft"]
    assert draft["usable"] and not draft["stale"] and "Draft text." in draft["sections"]["summary"]
    assert "Restore my edits" in again.html
    assert ui.delete(f"/ui/review/{ws.mm3_id}/draft", headers=JSON).status_code == 200
    assert Workspace(ui, url).data["draft"] is None
    r = ws.post("render", base_sha=ws.sha, edits=edits)
    assert "Draft text." in r.json()["html"] and "<script" not in r.json()["html"]


# -- regeneration ----------------------------------------------------------------------------------


@requires_ffmpeg
def test_regenerate_accept_with_archive_then_save(ui: TestClient, tone: Path, vault: Path) -> None:
    url, note = processed(ui, tone, vault)
    ws = Workspace(ui, url)
    before = read_text(note)
    doc = split_document(before)
    summary = doc.section("summary")
    assert summary is not None
    edited_inner = summary.inner.replace("Simulated summary", "Hand-edited summary")
    r = ws.post(
        "regenerate",
        base_sha=ws.sha,
        section_id="summary",
        inner=edited_inner,
        instructions="Shorter.",
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["new_inner"].startswith("## Summary Succinct\n\n") and 'class="diff"' in out["html"]
    assert "Hand-edited summary" in out["html"]  # diffed against the editor's version
    assert read_text(note) == before  # a preview writes nothing

    a = ws.post("archive-section", section_id="summary", inner=edited_inner)
    archive = vault / a.json()["archive"]
    assert archive.parent == note.parent / "Archive"
    assert re.fullmatch(r"2026-10-11 - Product Sync\.summary\.\d{8}-\d{4}\.md", archive.name)
    archived = read_text(archive)
    assert "mm3-archived-section: summary" in archived and "Hand-edited summary" in archived

    r = ws.post("save", base_sha=ws.sha, edits=edits_with(before, summary=out["new_inner"]))
    assert r.status_code == 200
    after = read_text(note)
    old, new = scan_sections(before).get("summary"), scan_sections(after).get("summary")
    assert old and new
    assert after[: new.inner_start] == before[: old.inner_start]  # byte-identical outside
    assert after[new.inner_end :] == before[old.inner_end :]
    assert after[new.inner_start : new.inner_end] == out["new_inner"]


def test_regenerate_errors_and_consent(ui: TestClient, fixture_note: Path) -> None:
    ws = Workspace(ui, open_url(ui, f"Meetings/2026/{NOTE}"))
    r = ws.post(
        "regenerate", base_sha=ws.sha, section_id="summary", backend="openrouter", model="x/y"
    )
    assert r.status_code == 403 and r.json()["code"] == "E_CONSENT_REQUIRED"
    r = ws.post(
        "regenerate",
        base_sha=ws.sha,
        section_id="summary",
        backend="openrouter",
        model="x/y",
        cloud_consent=True,
    )
    assert r.status_code == 200 and r.json()["backend"] == "openrouter"
    assert (
        ws.post("regenerate", base_sha="0" * 64, section_id="summary").json()["code"]
        == "E_BASE_GONE"
    )
    r = ws.post("regenerate", base_sha=ws.sha, section_id="nope", inner="x")
    assert r.status_code == 409 and r.json()["code"] == "section_markers_invalid"


def test_damaged_markers_offer_append_as_new_section(ui: TestClient, fixture_note: Path) -> None:
    text = read_text(fixture_note)
    damaged = text.replace("<!-- /mm3:section:decisions -->\n", "", 1)
    fixture_note.write_text(damaged, encoding="utf-8")
    ws = Workspace(ui, open_url(ui, f"Meetings/2026/{NOTE}"))
    assert (
        "Some section markers are damaged" in ws.html and 'data-section-id="decisions"' in ws.html
    )
    assert "decisions" not in [s.id for s in split_document(damaged).sections]
    # R11: regenerating the damaged section in place is refused...
    r = ws.post("regenerate", base_sha=ws.sha, section_id="decisions", inner="## X\n")
    assert r.status_code == 409 and r.json()["code"] == "section_markers_invalid"
    # ...appending a fresh copy works, and the damaged text is left where it was.
    r = ws.post("regenerate", base_sha=ws.sha, section_id="decisions", append=True)
    assert r.status_code == 200 and r.json()["new_inner"].startswith("## Decisions Made\n")
    r = ws.post(
        "append-section", base_sha=ws.sha, section_id="decisions", inner=r.json()["new_inner"]
    )
    assert r.status_code == 200 and r.json()["section_id"] == "decisions-2"
    after = read_text(fixture_note)
    assert after.startswith(damaged[: damaged.index("<!-- mm3:section:ai-recommendations -->")])
    assert [s.id for s in scan_sections(after).sections][-2:] == [
        "decisions-2",
        "ai-recommendations",
    ]


def test_missing_companion_is_note_only_and_can_be_relinked(
    ui: TestClient, fixture_note: Path, vault: Path
) -> None:
    folder = fixture_note.parent
    elsewhere = vault / "Elsewhere"
    elsewhere.mkdir()
    shutil.move(folder / COMPANION, elsewhere / "moved.transcript.md")
    ws = Workspace(ui, open_url(ui, f"Meetings/2026/{NOTE}"))
    assert not ws.data["can_regenerate"] and "Transcript not found" in ws.html
    assert 'class="regen-btn" data-section-id="summary" data-title="Summary" disabled' in ws.html
    r = ws.post("regenerate", base_sha=ws.sha, section_id="summary")
    assert r.status_code == 409 and r.json()["code"] == "E_TRANSCRIPT_MISSING"

    found = ui.get(f"/ui/review/{FIXTURE_ID}/locate?path={quote(ws.path)}").text
    assert "Elsewhere/moved.transcript.md" in found and "move it into" in found
    shutil.move(elsewhere / "moved.transcript.md", folder / "Renamed transcript.md")
    found = ui.get(f"/ui/review/{FIXTURE_ID}/locate?path={quote(ws.path)}").text
    assert "Link this transcript" in found
    bad = ws.post("link-transcript", base_sha=ws.sha, transcript="../outside.md")
    assert bad.json()["code"] == "vault_path_escape"
    r = ws.post(
        "link-transcript", base_sha=ws.sha, transcript="Meetings/2026/Renamed transcript.md"
    )
    assert r.status_code == 200, r.text
    assert parse_note(read_text(fixture_note)).note.meta.transcript_ref == "Renamed transcript"
    readable = fixture_note.with_name(fixture_note.stem + " (Transcript).md")
    assert "mm3-transcript: '[[Renamed transcript]]'" in read_text(readable) or (
        'mm3-transcript: "[[Renamed transcript]]"' in read_text(readable)
    )
    assert f"[[{readable.stem}|Read the transcript]]" in read_text(fixture_note)
    assert Workspace(ui, open_url(ui, f"Meetings/2026/{NOTE}")).data["can_regenerate"]


# -- switch template and rename speakers ----------------------------------------------------------


def test_switch_template_archives_and_preserves_user_text(
    ui: TestClient, fixture_note: Path
) -> None:
    text = read_text(fixture_note).replace(
        "<!-- mm3:section:decisions -->", "My own paragraph.\n\n<!-- mm3:section:decisions -->"
    )
    link = "- **Transcript:** [[2026-10-11 - Product Sync (Transcript)|Read the transcript]]\n"
    text = text.replace("- **Participants:**", link + "- **Participants:**", 1)
    fixture_note.write_text(text, encoding="utf-8")
    ws = Workspace(ui, open_url(ui, f"Meetings/2026/{NOTE}"))
    r = ws.post("switch/preview", base_sha=ws.sha, template="action-focused")
    assert r.status_code == 200, r.text
    assert "Preserved notes" in r.json()["html"] and read_text(fixture_note) == text
    r = ws.post("switch/apply", token=r.json()["token"])
    assert r.status_code == 200, r.text
    archive = fixture_note.parent / r.json()["archive"].split("Meetings/2026/")[1]
    assert archive.parent.name == "Archive" and "mm3-archived:" in read_text(archive)
    assert "My own paragraph." in read_text(archive)
    new = parse_note(read_text(fixture_note))
    assert new.note.meta.template_id == "action-focused" and new.ok
    assert read_text(fixture_note).endswith("## Preserved notes\n\nMy own paragraph.\n")
    assert read_text(fixture_note).count(link) == 1  # the readable link survives the switch
    assert ws.post("switch/apply", token=r.json().get("token", "0" * 32)).status_code in (409, 422)


def test_switch_apply_refuses_if_the_note_changed(ui: TestClient, fixture_note: Path) -> None:
    ws = Workspace(ui, open_url(ui, f"Meetings/2026/{NOTE}"))
    token = ws.post("switch/preview", base_sha=ws.sha, template="decision-log").json()["token"]
    fixture_note.write_text(read_text(fixture_note) + "\nlater edit\n", encoding="utf-8")
    r = ws.post("switch/apply", token=token)
    assert r.status_code == 409 and r.json()["code"] == "E_NOTE_CHANGED"
    assert not (fixture_note.parent / "Archive").exists()


@requires_ffmpeg
def test_rename_speakers_updates_note_companion_and_job(
    ui: TestClient, tone: Path, vault: Path
) -> None:
    url, note = processed(ui, tone, vault, participants=["Dana"])
    ws = Workspace(ui, url)
    companion = note.with_name(note.name.replace(".md", ".transcript.md"))
    user_text = read_text(note).replace(
        "\n<!-- mm3:section:", "\nAlice said hi outside.\n\n<!-- mm3:section:", 1
    )
    note.write_text(user_text, encoding="utf-8")
    ws = Workspace(ui, url)
    r = ws.post(
        "speakers/preview", base_sha=ws.sha, names={"SPEAKER_00": "Alicia", "SPEAKER_01": "Bob"}
    )
    assert r.status_code == 200 and "Alicia" in r.json()["html"]
    assert read_text(note) == user_text
    r = ws.post(
        "speakers/apply",
        base_sha=ws.sha,
        names={"SPEAKER_00": "Alicia", "SPEAKER_01": "Bob"},
        companion_sha=r.json()["companion_sha"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["job_updated"] and r.json()["changes"][0]["new"] == "Alicia"
    meta = parse_note(read_text(note)).note.meta
    assert meta.speakers.names == {"SPEAKER_00": "Alicia", "SPEAKER_01": "Bob"}
    assert meta.participants == ["Alicia", "Bob", "Dana"]
    assert "Alice said hi outside." in read_text(note)
    assert "Alicia:**" in read_text(companion) and "] Alice:**" not in read_text(companion)
    readable = note.with_name(note.stem + " (Transcript).md")
    assert ">Alicia</mark>" in read_text(readable) and ">Alice</mark>" not in read_text(readable)
    stale = ws.post("speakers/apply", base_sha=ws.sha, names={"SPEAKER_00": "X"})
    assert stale.status_code == 409


@requires_ffmpeg
def test_reprocess_and_missing_audio(ui: TestClient, tone: Path, vault: Path) -> None:
    url, _note = processed(ui, tone, vault)
    ws = Workspace(ui, url)
    runner = ui.app.state.runner  # type: ignore[attr-defined]
    job_id = re.search(r"/api/jobs/([0-9a-f-]+)/audio", ws.html)
    assert job_id
    old = runner.jobs.get(job_id.group(1))
    runner.jobs.update(old.id, settings={**old.settings, "cloud_consent_for": "cloud"})
    r = ws.post("reprocess")
    assert r.status_code == 200 and r.json()["url"].startswith("/jobs/")
    new_id = r.json()["job_id"]
    wait(ui, new_id, "waiting_for_input")
    new = runner.jobs.get(new_id)
    assert new.settings.get("cloud_consent_for") is None  # consent is per job (S6)
    # The copied recording is one retention knows about (R8), so it is compressed and pruned.
    assert new.audio_path in [p.name for p in audio_files(job_dir(runner.jobs_root, new_id))]
    runner.audio_file(job_id.group(1)).unlink()
    again = Workspace(ui, url)
    assert 'id="audio"' not in again.html and 'id="no-audio"' in again.html
    assert again.html.count('class="seg"') == 5  # the transcript stays usable


# -- security --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "action"),
    [
        ("post", "save"),
        ("post", "draft"),
        ("delete", "draft"),
        ("post", "render"),
        ("post", "regenerate"),
        ("post", "archive-section"),
        ("post", "append-section"),
        ("post", "switch/preview"),
        ("post", "switch/apply"),
        ("post", "speakers/preview"),
        ("post", "speakers/apply"),
        ("post", "link-transcript"),
        ("post", "reprocess"),
        ("post", "keep"),
    ],
)
def test_every_action_needs_csrf(ui: TestClient, method: str, action: str) -> None:
    token = ui.headers.pop("X-CSRF-Token")
    try:
        r = getattr(ui, method)(f"/ui/review/{FIXTURE_ID}/{action}")
    finally:
        ui.headers["X-CSRF-Token"] = token
    assert r.status_code == 403


def test_actions_cannot_target_files_outside_the_vault(ui: TestClient, fixture_note: Path) -> None:
    for path in ("../outside.md", "/etc/passwd", f"Meetings/2026/{COMPANION}"):
        r = ui.post(
            f"/ui/review/{FIXTURE_ID}/archive-section",
            json={"path": path, "section_id": "summary", "inner": "x"},
            headers=JSON,
        )
        assert r.status_code in (400, 404), (path, r.text)


def test_workspace_embeds_feedback_and_downloads(ui: TestClient, fixture_note: Path) -> None:
    ws = Workspace(ui, open_url(ui, f"Meetings/2026/{NOTE}"))
    sections = len(split_document(read_text(fixture_note)).sections)
    assert ws.html.count('hx-post="/ui/feedback"') == sections + 1
    assert "How good is this note?" in ws.html and "How good is this section?" in ws.html
    form = {
        "mm3_id": FIXTURE_ID,
        "kind": "thumbs",
        "template_id": "executive-summary",
        "backend": "ollama",
        "model": "qwen3:8b",
        "section_id": "summary",
        "value": "1",
        "comment": "",
    }
    r = ui.post("/ui/feedback", data=form, headers={"HX-Request": "true"})
    assert r.status_code == 200, r.text
    again = Workspace(ui, open_url(ui, f"Meetings/2026/{NOTE}"))
    assert 'aria-label="Good" aria-pressed="true"' in again.html
    link = re.search(r'href="(/api/export/meeting\?note=[^"]+kind=note)"', again.html)
    assert link
    download = ui.get(link.group(1).replace("&amp;", "&"))
    assert download.status_code == 200 and download.text == read_text(fixture_note)


# -- Preview first, and the recording-retention line (R26) -----------------------------------------


def test_note_opens_rendered_with_the_editor_hidden(ui: TestClient, fixture_note: Path) -> None:
    ws = Workspace(ui, open_url(ui, f"Meetings/2026/{NOTE}"))
    assert re.search(r'<div id="editor" class="editor" hidden>', ws.html)
    preview = re.search(r'<div id="preview" class="note">(.*?)</div>\s*</section>', ws.html, re.S)
    assert preview and "<h" in preview.group(1) and "mm3:section" not in preview.group(1)
    assert 'id="btn-preview" aria-pressed="true"' in ws.html
    assert 'id="btn-edit" aria-pressed="false"' in ws.html
    assert 'data-kind="section"' in ws.html  # the editor is still in the page, just hidden


def test_read_only_note_shows_the_preview_without_a_mode_switch(
    ui: TestClient, vault: Path
) -> None:
    (vault / "bare.md").write_text(
        f"---\nmm3-id: {FIXTURE_ID}\ntitle: Bare\n---\n# Bare\n\nJust text.\n", "utf-8"
    )
    ws = Workspace(ui, open_url(ui, "bare.md"))
    assert '<article class="note">' in ws.html and "Just text." in ws.html
    assert "btn-edit" not in ws.html and 'id="editor"' not in ws.html


def _runner(ui: TestClient) -> Any:
    return ui.app.state.runner  # type: ignore[attr-defined]


@requires_ffmpeg
def test_retention_line_and_keep_forever_roundtrip(ui: TestClient, tone: Path, vault: Path) -> None:
    url, _note = processed(ui, tone, vault)
    ws = Workspace(ui, url)
    assert 'id="retention"' in ws.html
    assert "Recording deleted in 90 days (" in ws.html and "Keep forever</button>" in ws.html
    assert 'href="/settings/privacy"' in ws.html
    job_id = re.search(r"/api/jobs/([0-9a-f-]+)/audio", ws.html)
    assert job_id
    jid = job_id.group(1)

    r = ws.post("keep", keep=True)
    assert r.status_code == 200 and r.json()["pinned"] is True
    assert "Recording kept forever." in r.json()["html"] and "Allow deletion" in r.json()["html"]
    assert _runner(ui).jobs.get(jid).audio_pinned
    api = ui.get(f"/api/jobs/{jid}").json()["audio"]
    assert api["pinned"] is True and api["retention"]["kind"] == "kept_pinned"
    assert "Recording kept forever." in Workspace(ui, url).html  # survives a reload
    assert _runner(ui).prune() == []  # and the pruner agrees

    r = ws.post("keep", keep=False)
    assert r.status_code == 200 and "deleted in 90 days" in r.json()["html"]
    assert 'data-undo-text=""' in r.json()["html"]
    assert ui.get(f"/api/jobs/{jid}").json()["audio"]["retention"]["days_left"] == 90


@requires_ffmpeg
def test_pin_api_returns_the_retention_status(ui: TestClient, tone: Path, vault: Path) -> None:
    url, _note = processed(ui, tone, vault)
    ws = Workspace(ui, url)
    job_id = re.search(r"/api/jobs/([0-9a-f-]+)/audio", ws.html)
    assert job_id
    r = ui.post(f"/api/jobs/{job_id.group(1)}/pin")
    assert r.status_code == 200 and r.json()["audio"]["retention"]["kind"] == "kept_pinned"
    r = ui.post(f"/api/jobs/{job_id.group(1)}/unpin")
    assert r.json()["audio"]["pinned"] is False


@requires_ffmpeg
def test_line_follows_a_changed_retention_setting(ui: TestClient, tone: Path, vault: Path) -> None:
    url, _note = processed(ui, tone, vault)
    runner = _runner(ui)
    runner.settings.privacy.audio_retention = "forever"
    html = Workspace(ui, url).html
    assert "retention setting keeps recordings forever" in html
    assert "Keep this one even if the setting changes" in html
    runner.settings.privacy.audio_retention = "delete_after_write"
    assert "at the next check" in Workspace(ui, url).html


@requires_ffmpeg
def test_keep_refuses_pruned_audio_and_unlinked_notes(
    ui: TestClient, tone: Path, vault: Path, fixture_note: Path
) -> None:
    url, _note = processed(ui, tone, vault)
    ws = Workspace(ui, url)
    runner = _runner(ui)
    jid = re.search(r"/api/jobs/([0-9a-f-]+)/audio", ws.html).group(1)  # type: ignore[union-attr]
    runner.audio_file(jid).unlink()
    runner.jobs.update(jid, audio_path=None, audio_pruned_at=runner.jobs.get(jid).updated_at)
    r = ws.post("keep", keep=True)
    assert r.status_code == 410 and r.json()["code"] == "E_AUDIO_EXPIRED"
    again = Workspace(ui, url)
    assert 'id="retention"' not in again.html and 'id="no-audio"' in again.html
    # A note with no linked job has nothing to keep.
    other = Workspace(ui, open_url(ui, f"Meetings/2026/{NOTE}"))
    assert other.post("keep", keep=True).status_code == 404


def test_privacy_hint_names_the_real_place(ui: TestClient) -> None:
    page = ui.get("/settings/privacy").text
    assert "Keep a recording forever from its review page" in page
    assert "Pin or unpin" not in page
