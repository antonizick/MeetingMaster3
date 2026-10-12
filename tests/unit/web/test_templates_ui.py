"""The template library screen."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meetingmaster3.templates.loader import builtin_dir

FILE = "executive-summary.md"


def templates_dir(vault: Path) -> Path:
    return vault / "MeetingMaster3" / "templates"


def test_library_lists_builtins_with_badges(ui: TestClient) -> None:
    text = ui.get("/templates").text
    assert "Executive Summary" in text and "built-in" in text and "Technical Deep-Dive" in text
    assert "obsidian://open" in text and "Reset to default" in text


def test_filter_by_search_and_tag(ui: TestClient) -> None:
    only = ui.get("/templates/list", params={"q": "decision log"}).text
    assert "Decision Log" in only and "Technical Deep-Dive" not in only
    tagged = ui.get("/templates/list", params={"tag": "leadership"}).text
    assert "Executive Summary" in tagged and "Decision Log" not in tagged
    assert "No templates match" in ui.get("/templates/list", params={"q": "zzzz"}).text


def test_favourite_star_is_persisted_in_the_vault_file(ui: TestClient, vault: Path) -> None:
    r = ui.post(f"/templates/{FILE}/favorite", data={"favorite": "1"})
    assert "★" in r.text and "Remove Executive Summary from favourites" in r.text
    assert "favorite: true" in (templates_dir(vault) / FILE).read_text()
    ui.post(f"/templates/{FILE}/favorite", data={"favorite": "0"})
    assert "favorite: false" in (templates_dir(vault) / FILE).read_text()


def test_duplicate_create_and_delete(ui: TestClient, vault: Path) -> None:
    r = ui.post(f"/templates/{FILE}/duplicate")
    assert "Executive Summary (copy)" in r.text
    assert (templates_dir(vault) / "Executive Summary (copy).md").is_file()

    created = ui.post("/templates/new", data={"name": "Team Retro"})
    assert created.headers["HX-Redirect"] == "/templates/Team Retro.md/edit"
    assert "Team Retro" in ui.get("/templates").text

    gone = ui.post("/templates/Team Retro.md/delete")
    assert "Team Retro" not in gone.text
    assert any((templates_dir(vault) / "Archive").glob("Team Retro.*.md"))
    assert ui.post(f"/templates/{FILE}/delete").status_code == 409


def test_reset_builtin(ui: TestClient, vault: Path) -> None:
    path = templates_dir(vault) / FILE
    path.write_text(path.read_text().replace("Executive Summary", "Mine", 1))
    assert "Mine" in ui.get("/templates").text
    ui.post(f"/templates/{FILE}/reset")
    assert path.read_text() == (builtin_dir() / FILE).read_text()
    assert any((templates_dir(vault) / "Archive").glob("executive-summary.*.md"))


def test_edit_save_shows_line_numbered_errors(ui: TestClient, vault: Path) -> None:
    page = ui.get(f"/templates/{FILE}/edit").text
    assert "<textarea" in page and "Executive Summary" in page
    path = templates_dir(vault) / FILE
    original = path.read_text()
    bad = original.replace("kind: narrative", "kind: poetry", 1)
    r = ui.post(f"/templates/{FILE}/edit", data={"text": bad})
    assert "Not saved." in r.text and "Line " in r.text
    assert "kind: poetry" in r.text  # the editor keeps what the user typed
    assert path.read_text() == original
    good = original.replace("A short, high-level brief", "A short brief")
    ok = ui.post(f"/templates/{FILE}/edit", data={"text": good})
    assert "✓ Saved." in ok.text and path.read_text() == good


def test_preview_shows_sections_and_prompts(ui: TestClient) -> None:
    text = ui.get(f"/templates/{FILE}/preview").text
    assert "Decisions Made" in text and "Instructions to the model" in text
    assert "mm3:prompt" not in text  # prompt text only, no markers


def test_invalid_template_card_explains_the_problem(ui: TestClient, vault: Path) -> None:
    (templates_dir(vault) / "bad.md").write_text("---\nmm3-template: 1\nid: x\n---\n")
    text = ui.get("/templates").text
    assert "bad.md" in text and "cannot be used until it is fixed" in text


def test_edits_in_obsidian_show_on_refresh(ui: TestClient, vault: Path) -> None:
    path = templates_dir(vault) / FILE
    path.write_text(path.read_text().replace("name: Executive Summary", "name: Boardroom Brief"))
    assert "Boardroom Brief" in ui.get("/templates").text


@pytest.mark.parametrize("bad", ["../x.md", "x.txt"])
def test_bad_file_names_are_404(ui: TestClient, bad: str) -> None:
    assert ui.get(f"/templates/{bad}/edit").status_code in (404, 405)
