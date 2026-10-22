"""The Search page and the Search & Ask settings tab (Phase 15i)."""

from __future__ import annotations

import datetime as dt
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from meetingmaster3.app import create_app
from meetingmaster3.config.settings import Settings
from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.note import Section
from meetingmaster3.markdown.note_writer import build_note, render_note
from tests.search_corpus import MEETINGS_DIR, by_key


def _wait_indexed(client: TestClient, meetings: int, timeout: float = 15.0) -> dict[str, Any]:
    service = client.app.state.search  # type: ignore[attr-defined]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = service.status()
        if not st["running"] and st["meetings"] >= meetings and st["vectors_complete"]:
            return st  # type: ignore[no-any-return]
        time.sleep(0.05)
    raise AssertionError(f"index not ready: {service.status()}")


@pytest.fixture
def sui(corpus_vault: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    monkeypatch.delenv("MM3_SEARCH__ENABLED")
    monkeypatch.setattr("meetingmaster3.search.service.DEBOUNCE_S", 0.01)
    settings = Settings()
    settings.vault.path = corpus_vault
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        client.get("/healthz")
        client.headers["X-CSRF-Token"] = client.cookies["mm3_csrf"]
        _wait_indexed(client, 7)
        yield client


def test_search_is_in_the_navigation(sui: TestClient) -> None:
    page = sui.get("/search")
    assert page.status_code == 200
    assert '<a href="/search" aria-current="page">Search</a>' in page.text
    assert "7 meetings indexed" in page.text
    assert 'role="search"' in page.text


def test_results_are_grouped_linked_and_highlighted(sui: TestClient) -> None:
    page = sui.get("/search", params={"q": "costs exceeded the forecast"})
    assert page.status_code == 200
    vendor = by_key("vendor")
    assert "Vendor Contract Sync" in page.text
    assert "meaning + words" in page.text
    assert "<mark>" in page.text
    note = f"{MEETINGS_DIR}/{vendor.stem}.md".replace("/", "%2F").replace(" ", "%20")
    assert f'href="/meetings/{vendor.id}?path={note}#t=0"' in page.text  # the transcript moment
    assert f'href="/meetings/{vendor.id}?path={note}"' in page.text  # the meeting itself


def test_snippets_are_escaped(sui: TestClient, corpus_vault: Path) -> None:
    meta = MeetingMeta(id=uuid.uuid4(), title="Injected", date=dt.datetime(2026, 9, 30, 9, 0))
    body = 'We said <script>alert("pwned")</script> and <img src=x onerror=alert(1)> zebra.'
    text = render_note(
        build_note(meta, [Section(id="summary", title="Summary", body_markdown=body)])
    )
    (corpus_vault / "Injected.md").write_text(text, encoding="utf-8")
    sui.post("/settings/search/update")
    _wait_indexed(sui, 8)
    page = sui.get("/search", params={"q": "zebra"})
    assert "Injected" in page.text
    assert "<script>alert" not in page.text and "<img src=x" not in page.text
    assert "&lt;script&gt;" in page.text


@pytest.mark.parametrize(
    "q", ['"', "NEAR(budget", "budget*", "-budget", "title:budget", "((", "a\x00b", "x" * 600]
)
def test_fts_syntax_never_gives_an_error_page(sui: TestClient, q: str) -> None:
    page = sui.get("/search", params={"q": q})
    assert page.status_code == 200
    assert "Something went wrong" not in page.text


def test_filters_and_bad_dates(sui: TestClient) -> None:
    page = sui.get("/search", params={"q": "budget costs spending", "person": "Tom"})
    assert "Platform Weekly" in page.text and "Q3 Finance Review" not in page.text
    bad = sui.get("/search", params={"q": "budget", "from": "yesterday"})
    assert bad.status_code == 200 and "is not a date" in bad.text


def test_results_are_paged(sui: TestClient, corpus_vault: Path) -> None:
    for i in range(12):
        meta = MeetingMeta(
            id=uuid.uuid4(), title=f"Zebra sync {i}", date=dt.datetime(2026, 8, 1 + i)
        )
        section = Section(
            id="summary", title="Summary", body_markdown=f"The zebra project, part {i}."
        )
        (corpus_vault / f"Zebra {i}.md").write_text(
            render_note(build_note(meta, [section])), "utf-8"
        )
    sui.post("/settings/search/update")
    _wait_indexed(sui, 19)
    first = sui.get("/search", params={"q": "zebra project"})
    assert "12</strong> meetings found" in first.text
    assert 'rel="next" href="/search?q=zebra+project&amp;results_page=2"' in first.text
    second = sui.get("/search", params={"q": "zebra project", "results_page": "2"})
    assert "Page 2 of 2" in second.text


def test_settings_tab_shows_the_index(sui: TestClient) -> None:
    page = sui.get("/settings/search")
    assert page.status_code == 200
    assert "Meeting index" in page.text and "Update index" in page.text
    assert "7 (7 notes, 7 transcripts)" in page.text
    assert '<option value="auto" selected>auto</option>' in page.text


def test_settings_buttons_need_csrf(sui: TestClient) -> None:
    token = sui.headers.pop("X-CSRF-Token")
    assert sui.post("/settings/search/update").status_code == 403
    assert sui.post("/settings/search/delete").status_code == 403
    sui.headers["X-CSRF-Token"] = token
    assert sui.post("/settings/search/update").status_code == 200


def test_delete_then_update_again(sui: TestClient) -> None:
    db = sui.app.state.paths.search_database  # type: ignore[attr-defined]
    response = sui.post("/settings/search/delete")
    assert response.status_code == 200 and "indexing is off" in response.text
    assert not db.exists()
    config = yaml.safe_load(sui.app.state.paths.config_file.read_text())  # type: ignore[attr-defined]
    assert config["search"]["enabled"] is False
    assert "Search is switched off" in sui.get("/search", params={"q": "budget"}).text
    assert sui.post("/settings/search/update").status_code == 200
    _wait_indexed(sui, 7)
    assert "Q3 Finance Review" in sui.get("/search", params={"q": "budget overrun"}).text


def test_saving_the_tab_maps_auto_to_the_default(sui: TestClient) -> None:
    form = {
        "search.enabled": "1",
        "search.embedding_backend": "auto",
        "search.embedding_model": "nomic-embed-text",
        "search.index_transcripts": "1",
        "search.chunk_tokens": "300",
        "search.chunk_overlap": "40",
        "search.rescan_minutes": "15",
    }
    page = sui.post("/settings/search", data=form)
    assert page.status_code == 200 and "Saved" in page.text
    settings = sui.app.state.settings  # type: ignore[attr-defined]
    assert settings.search.embedding_backend is None and settings.search.chunk_tokens == 300


def test_backend_form_saves_cloud_embedding_consent(sui: TestClient) -> None:
    form = {
        "orig_name": "",
        "name": "router",
        "kind": "openrouter",
        "cloud_embedding_consent": "1",
    }
    assert sui.post("/settings/llm/save", data=form).status_code == 200
    cfg = sui.app.state.settings.llm.backends["router"]  # type: ignore[attr-defined]
    assert cfg.cloud_embedding_consent is True and cfg.consent_remembered is False
    edit = sui.get("/settings/llm/router/edit")
    assert "Indexing sends the full text of every meeting" in edit.text
    sui.post("/settings/llm/router/revoke-consent")
    assert cfg.cloud_embedding_consent is False
