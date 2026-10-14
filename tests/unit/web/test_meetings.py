"""The Meetings page (Phase 15c, R27): the rename from Recent, merged Open-a-note, paging."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from meetingmaster3.app import create_app
from meetingmaster3.config.settings import Settings
from meetingmaster3.jobs.models import JobStatus
from meetingmaster3.storage.repositories import RecentMeetingsRepository
from meetingmaster3.web import paging

NO_TOKEN = {"X-CSRF-Token": ""}


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / ".obsidian").mkdir(parents=True)
    return root.resolve()


@pytest.fixture
def ui(vault: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    settings = Settings()
    settings.vault.path = vault
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        client.get("/healthz")
        client.headers["X-CSRF-Token"] = client.cookies["mm3_csrf"]
        yield client


def add_jobs(ui: TestClient, n: int) -> list[str]:
    runner = ui.app.state.runner  # type: ignore[attr-defined]
    ids = []
    for i in range(n):
        job_id = f"00000000-0000-4000-8000-{i:012d}"
        runner.jobs.create(job_id, stages=["a"], title=f"Meeting {i:02d}", status=JobStatus.WRITTEN)
        ids.append(job_id)
    return ids


def add_notes(ui: TestClient, vault: Path, n: int) -> list[Path]:
    repo = RecentMeetingsRepository(ui.app.state.runner.db)  # type: ignore[attr-defined]
    paths = []
    for i in range(n):
        note = vault / "Meetings" / f"2026-10-11 - Note {i:02d}.md"
        note.parent.mkdir(exist_ok=True)
        note.write_text("# n\n", "utf-8")
        repo.touch(str(note), title=f"Note {i:02d}")
        paths.append(note)
    return paths


# -- the helpers -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("total", "asked", "number", "pages"),
    [(0, 1, 1, 1), (10, 1, 1, 1), (11, 2, 2, 2), (11, 9, 2, 2), (25, 0, 1, 3), (25, -4, 1, 3)],
)
def test_paginate_clamps_to_real_pages(total: int, asked: int, number: int, pages: int) -> None:
    page = paginate = paging.paginate(total, asked, 10)
    assert (paginate.number, paginate.pages) == (number, pages)
    assert page.offset == (number - 1) * 10


def test_parse_page_ignores_junk() -> None:
    assert [paging.parse_page(x) for x in (None, "", "x", "-3", "0", "4", "99999999999")] == [
        1, 1, 1, 1, 1, 4, paging.MAX_PAGE
    ]  # fmt: skip


def test_page_window_has_gaps_and_the_ends() -> None:
    assert paging.page_window(paging.paginate(30, 1, 10)) == [1, 2, 3]
    assert paging.page_window(paging.paginate(300, 15, 10)) == [
        1,
        None,
        13,
        14,
        15,
        16,
        17,
        None,
        30,
    ]


def test_with_params_drops_the_first_page_and_empty_values() -> None:
    assert (
        paging.with_params("/meetings", {"dir": "", "notes_page": "3"}) == "/meetings?notes_page=3"
    )
    assert paging.with_params("/meetings", {"notes_page": "3"}, notes_page=1) == "/meetings"
    assert paging.with_params("", {"jobs_page": "2"}) == "?jobs_page=2"


# -- the page --------------------------------------------------------------------------------------


def test_meetings_is_the_name_everywhere(ui: TestClient) -> None:
    page = ui.get("/meetings").text
    assert "<title>Meetings · MeetingMaster3</title>" in page and "<h1>Meetings</h1>" in page
    nav = re.search(r'<nav aria-label="Main">(.*?)</nav>', page, re.S)
    assert nav and ">Meetings</a>" in nav.group(1)
    assert "Recent" not in nav.group(1) and "Open a note" not in nav.group(1)
    order = [page.index(h) for h in ('id="h-jobs"', 'id="h-notes"', 'id="h-browse"')]
    assert order == sorted(order)  # Browse the vault is at the bottom
    assert 'id="sec-notes" aria-labelledby="h-notes" class="card"' in page


def test_old_open_links_land_on_meetings(ui: TestClient) -> None:
    r = ui.get("/open", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/meetings"
    r = ui.get("/open?dir=Meetings", follow_redirects=False)
    assert r.headers["location"] == "/meetings?dir=Meetings"


def test_jobs_page_in_tens_and_out_of_range_pages_clamp(ui: TestClient) -> None:
    add_jobs(ui, 23)
    first = ui.get("/meetings").text
    assert first.count('id="job-row-') == 10 and "Page 1 of 3" in first
    assert 'aria-label="Jobs pages"' in first and 'rel="next"' in first
    assert ui.get("/meetings?jobs_page=3").text.count('id="job-row-') == 3
    assert ui.get("/meetings?jobs_page=99").text.count('id="job-row-') == 3  # last page, not empty
    assert ui.get("/meetings?jobs_page=abc").text.count('id="job-row-') == 10
    partial = ui.get("/ui/meetings/jobs?jobs_page=2").text
    assert partial.count('id="job-row-') == 10 and "<html" not in partial
    assert 'hx-push-url="/meetings?jobs_page=3"' in partial


def test_notes_page_independently_and_counts_orphans_everywhere(
    ui: TestClient, vault: Path
) -> None:
    paths = add_notes(ui, vault, 14)
    paths[0].unlink()  # the oldest entry, so it is on page 2
    first = ui.get("/meetings").text
    assert first.count("Remove from list</button>") == 10 and "Page 1 of 2" in first
    assert "1 entry points to a note that is missing" in first  # counted across all pages
    second = ui.get("/meetings?notes_page=2").text
    assert second.count("Remove from list</button>") == 4
    # Another section's page stays where it is.
    add_jobs(ui, 12)
    both = ui.get("/meetings?jobs_page=2&notes_page=2").text
    assert 'href="/meetings?notes_page=2"' in both  # Jobs' own "Page 1" link keeps the notes page
    assert both.count('id="job-row-') == 2


def test_removing_the_last_entry_of_a_page_shows_the_previous_page(
    ui: TestClient, vault: Path
) -> None:
    paths = add_notes(ui, vault, 11)
    oldest = paths[0]
    r = ui.post("/ui/recent/remove?notes_page=2", data={"path": str(oldest)})
    assert r.status_code == 200
    assert r.text.count("Remove from list</button>") == 10 and "Page 1 of 1" not in r.text
    assert (
        ui.post(
            "/ui/recent/remove?notes_page=2", data={"path": str(oldest)}, headers=NO_TOKEN
        ).status_code
        == 403
    )


def test_deleting_the_last_job_of_a_page_shows_the_previous_page(ui: TestClient) -> None:
    ids = add_jobs(ui, 11)
    oldest = ids[-1]  # same timestamp, ordered by id: the last row of page 2
    r = ui.delete(f"/ui/jobs/{oldest}?jobs_page=2")
    assert r.status_code == 200 and r.text.count('id="job-row-') == 10
    assert oldest not in r.text


def test_browse_pages_a_folder_in_25s_and_keeps_the_deep_link(ui: TestClient, vault: Path) -> None:
    folder = vault / "Meetings"
    folder.mkdir()
    for i in range(30):
        (folder / f"2026-10-11 - Note {i:02d}.md").write_text(
            f"---\nmm3-id: 3f2b8c1e-7d4a-4e9b-a6c2-5b1d0e8f9a{i:02d}\n"
            f"title: Note {i:02d}\n---\n# n\n",
            "utf-8",
        )
    page = ui.get("/meetings?dir=Meetings").text
    assert "<code>Meetings</code>" in page and page.count("📝") == 25
    assert 'aria-label="Folder pages"' in page and "Page 1 of 2" in page
    second = ui.get(f"/ui/open/browse?dir={quote('Meetings')}&browse_page=2").text
    assert second.count("📝") == 5 and "<html" not in second
    # Every link carries the folder, and the plain link works without JavaScript.
    assert 'href="/meetings?dir=Meetings&amp;browse_page=2"' in page
