"""Phase 15d browser check: Title & date… renames and re-dates a meeting across a year, the
note reopens at its new path, a second note's link follows, the transcript links resolve, the
recording still plays and Meetings shows the new title and date. Fake pipeline; needs Chromium
(``MM3_E2E_BROWSER=/usr/bin/chromium``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.transcript_format import parse_transcript
from meetingmaster3.vault.io import read_text
from meetingmaster3.vault.readable import find_readable
from tests.e2e import test_qa_flows as qa
from tests.e2e.test_qa_flows import BLOCKING, _axe, browser_page
from tests.e2e.test_review_flow import shot, written_note
from tests.unit.jobs.helpers import make_tone, requires_ffmpeg

pytestmark = [pytest.mark.e2e, requires_ffmpeg]
pytest.importorskip("playwright.sync_api")

server = qa.server


def test_rename_and_redate_a_meeting_across_a_year(
    server: tuple[str, Path], tmp_path: Path
) -> None:
    base, vault = server
    url = written_note(base, make_tone(tmp_path / "2026-10-11 Wrong Name.m4a", 10.0))
    (old_note,) = [
        p for p in vault.rglob("2026-10-11 - *.md") if p.name.count(".") == 1 and "(" not in p.name
    ]
    old_stem = old_note.stem
    (vault / "Daily.md").write_text(f"- [[{old_stem}|yesterday's meeting]]\n", encoding="utf-8")
    sections_before = [s.body_markdown for s in parse_note(read_text(old_note)).note.sections]

    with browser_page(base) as page:
        page.goto(url)
        page.wait_for_selector("#preview:not([hidden]) h2")
        page.click("#btn-retitle")
        page.fill("#form-retitle input[name=title]", "Right Name")
        page.fill("#form-retitle input[name=date]", "2025-12-30")
        page.click("#form-retitle button[type=submit]")
        page.wait_for_selector("#retitle-apply")
        assert "1 link in 1 other note" in page.inner_text("#retitle-result")
        assert "2025-12-30 - Right Name.md" in page.inner_text("#retitle-result")
        bad = [v for v in _axe(page) if v["impact"] in BLOCKING]
        assert not bad, [v["id"] for v in bad]
        shot(page, "retitle-preview")
        page.click("#retitle-apply")
        page.wait_for_url("**/meetings/*path=Meetings%2F2025*")
        page.wait_for_selector("#preview:not([hidden]) h2")
        assert page.inner_text(".ws-title h1") == "Right Name"
        assert "Meetings/2025/2025-12-30 - Right Name.md" in page.inner_text(".ws-meta")
        page.wait_for_selector(".toast", timeout=5000)
        assert "Renamed to 2025-12-30 - Right Name.md" in page.inner_text("body")
        # The recording still plays from the job, and Keep forever still works.
        assert page.locator("#audio").count() == 1
        page.click("#retention-btn")
        page.wait_for_function(
            "() => document.querySelector('#retention-text').textContent.includes('kept forever')"
        )

        page.goto(base + "/meetings")
        listing = page.inner_text("main")
        assert "Right Name" in listing and "2025-12-30" in listing and "Wrong Name" not in listing

    note = vault / "Meetings/2025/2025-12-30 - Right Name.md"
    assert not old_note.exists() and not list((vault / "Meetings/2026").glob("*.md"))
    parsed = parse_note(read_text(note))
    assert parsed.note.meta.title == "Right Name"
    assert [s.body_markdown for s in parsed.note.sections] == sections_before
    companion = note.parent / (parsed.note.meta.transcript_ref or "")
    companion = companion.with_name(companion.name + ".md")
    assert parse_transcript(read_text(companion)).doc.note_ref == note.stem
    readable = find_readable(note, str(parsed.note.meta.id))
    assert readable is not None and f"[[{readable.stem}|Read the transcript]]" in read_text(note)
    assert (vault / "Daily.md").read_text() == f"- [[{note.stem}|yesterday's meeting]]\n"
