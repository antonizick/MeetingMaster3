"""Phase 15a browser checks: the date from a month-day file name, the job page's "can I leave?"
line and tab title, the logo on navigation pages only, and the "Update older notes" card (with an
axe-core scan). Fake pipeline; needs Chromium (``MM3_E2E_BROWSER=/usr/bin/chromium``)."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest

from tests.e2e import test_qa_flows as qa
from tests.e2e.test_qa_flows import BLOCKING, _axe, api, browser_page
from tests.e2e.test_review_flow import SPEAKERS, written_note
from tests.unit.jobs.helpers import make_tone, requires_ffmpeg
from tests.unit.jobs.test_jobs_api import upload, wait

pytestmark = [pytest.mark.e2e, requires_ffmpeg]
pytest.importorskip("playwright.sync_api")

server = qa.server  # the same fake-pipeline server fixture

NICK = "09-22 Interview_ Nick Antoncic - SOC Manager _ Cyber Defense Candidate.m4a"


def expected_year() -> int:
    today = dt.date.today()
    return (
        today.year if dt.date(today.year, 9, 22) <= today + dt.timedelta(days=1) else today.year - 1
    )


def test_month_day_file_name_fills_the_date(server: tuple[str, Path], tmp_path: Path) -> None:
    base, _ = server
    audio = make_tone(tmp_path / NICK, 3.0)
    with browser_page(base) as page:
        page.goto(base + "/")
        hint = page.locator("#date-hint")
        assert not hint.is_visible()
        page.set_input_files("#file", str(audio))
        page.wait_for_function(
            "() => document.querySelector('#meeting_date').value.endsWith('-09-22')"
        )
        assert page.input_value("#meeting_date") == f"{expected_year()}-09-22"
        assert page.input_value("#title") == (
            "Interview Nick Antoncic - SOC Manager - Cyber Defense Candidate"
        )
        assert hint.is_visible() and hint.inner_text() == "From the file name"
        page.fill("#meeting_date", "2026-01-05")
        page.dispatch_event("#meeting_date", "input")
        assert not hint.is_visible()


def test_job_page_says_leaving_is_safe_and_titles_the_tab(
    server: tuple[str, Path], tmp_path: Path
) -> None:
    base, _ = server
    with api(base) as client:
        job = upload(client, make_tone(tmp_path / "2026-10-11 Title.m4a", 5.0), {}).json()  # type: ignore[arg-type]
        wait(client, job["id"], "waiting_for_input", timeout=30)  # type: ignore[arg-type]
        with browser_page(base) as page:
            page.goto(f"{base}/jobs/{job['id']}")
            note = page.locator(".leave-note")
            assert "paused until you name the speakers" in note.inner_text()
            assert page.title() == "Waiting for you · MeetingMaster3"
            client.post(f"/api/jobs/{job['id']}/speakers", json=SPEAKERS).raise_for_status()
            page.wait_for_function(
                "() => document.title === '✓ Notes ready · MeetingMaster3'", timeout=20000
            )
            assert page.locator(".leave-note").count() == 0


def test_logo_on_navigation_pages_only(server: tuple[str, Path], tmp_path: Path) -> None:
    base, _ = server
    url = written_note(base, make_tone(tmp_path / "2026-10-11 Logo Check.m4a", 5.0))
    with browser_page(base) as page:
        brand: list[str] = []
        page.on("request", lambda r: brand.append(r.url) if "/static/brand/" in r.url else None)
        for path in ("/", "/meetings", "/open", "/templates", "/settings"):
            page.goto(base + path)
            logo = page.locator("img.brand-logo")
            assert logo.count() == 1 and logo.is_visible(), path
            assert page.evaluate("() => document.querySelector('img.brand-logo').naturalWidth") > 0
            box = logo.bounding_box()
            assert box is not None and round(box["height"]) == 40
        page.goto(base + "/")
        hero = page.locator("img.hero-logo")
        assert (
            hero.is_visible()
            and page.evaluate("() => document.querySelector('img.hero-logo').naturalWidth") > 0
        )
        box = hero.bounding_box()
        h1 = page.locator("h1").bounding_box()
        assert box is not None and h1 is not None and round(box["width"]) == 320
        assert round(box["height"]) == 230 and box["y"] + box["height"] <= h1["y"]
        main = page.locator("main").bounding_box()
        assert main is not None  # centred in the content column
        assert abs((box["x"] + box["width"] / 2) - (main["x"] + main["width"] / 2)) <= 1
        page.set_viewport_size({"width": 380, "height": 800})
        page.goto(base + "/")
        box = page.locator("img.brand-logo").bounding_box()
        assert box is not None and round(box["height"]) == 32  # phone width
        hero_box = page.locator("img.hero-logo").bounding_box()
        assert hero_box is not None and hero_box["width"] <= 380 - 32
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
        page.set_viewport_size({"width": 1280, "height": 900})
        brand.clear()
        page.goto(url)
        page.wait_for_selector("#preview:not([hidden]) h2")
        assert page.locator(".brand-logo").count() == 0 and brand == []
        assert page.locator(".brand").inner_text() == "MeetingMaster3"


def test_update_older_notes_card(server: tuple[str, Path], tmp_path: Path) -> None:
    base, vault = server
    written_note(base, make_tone(tmp_path / "2026-10-11 Old Note.m4a", 5.0))
    note = next(vault.rglob("2026-10-11 - Old Note.md"))
    # Make it look like a note from before Phase 15a.
    text = note.read_text("utf-8")
    text = re.sub(
        r"<!-- mm3:section:summary-detailed -->.*?<!-- /mm3:section:summary-detailed -->\n\n",
        "",
        text,
        flags=re.S,
    ).replace("## Summary Succinct", "## Summary")
    text = re.sub(r"- \*\*Transcript:\*\* .*\n", "", text)
    note.write_text(text, encoding="utf-8")
    note.with_name("2026-10-11 - Old Note (Transcript).md").unlink()
    with browser_page(base, bypass_csp=True) as page:  # bypass only for the injected axe script
        page.goto(base + "/meetings")
        card = page.locator("#notes-upgrade")
        card.wait_for()
        assert "Update older notes" in card.inner_text() and "Summary Detailed" in card.inner_text()
        violations = [v for v in _axe(page) if v["impact"] in BLOCKING]
        assert not violations, violations
        card.get_by_role("button", name=re.compile(r"^Preview")).click()
        page.wait_for_selector("#notes-upgrade-preview .card")
        assert "Nothing has been written" in page.inner_text("#notes-upgrade-preview")
        assert "summary-detailed" not in note.read_text("utf-8")
        card.get_by_role("button", name="Update 1 note").click()
        page.wait_for_selector("text=Done.", timeout=20000)
        assert "1 of 1 notes updated" in page.inner_text("#notes-upgrade")
    text = note.read_text("utf-8")
    assert "<!-- mm3:section:summary-detailed -->" in text and "## Summary Succinct" in text
    assert note.with_name("2026-10-11 - Old Note (Transcript).md").is_file()
    assert any((note.parent / "Archive").glob("2026-10-11 - Old Note*.md"))
