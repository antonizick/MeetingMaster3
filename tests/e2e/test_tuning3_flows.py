"""Phase 15c browser checks: the switch-template progress widget (moving bar, elapsed clock, time
left, Cancel, a full switch), the recording download, the action-labelled Edit/Preview toggle and
the paged Meetings page. Fake pipeline with a slowed fake model; needs Chromium
(``MM3_E2E_BROWSER=/usr/bin/chromium``)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.e2e import test_qa_flows as qa
from tests.e2e.test_qa_flows import BLOCKING, _axe, api, browser_page
from tests.e2e.test_review_flow import shot, written_note
from tests.unit.jobs.helpers import make_tone, requires_ffmpeg
from tests.unit.jobs.test_jobs_api import upload, wait

pytestmark = [pytest.mark.e2e, requires_ffmpeg]
pytest.importorskip("playwright.sync_api")

server = qa.server


def open_switch(page: object, template: str = "decision-log") -> None:
    page.click("#btn-switch")  # type: ignore[attr-defined]
    page.select_option("#form-switch select[name=template]", template)  # type: ignore[attr-defined]


def test_switch_shows_a_moving_bar_elapsed_time_and_eta(
    server: tuple[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, vault = server
    url = written_note(base, make_tone(tmp_path / "2026-10-11 Progress.m4a", 20.0))
    monkeypatch.setenv("MM3_FAKE_LLM_SECONDS", "0.6")
    with browser_page(base, bypass_csp=True) as page:
        page.goto(url)
        page.wait_for_selector("#preview:not([hidden]) h2")
        open_switch(page)
        page.click("#form-switch button[type=submit]")
        widget = page.locator("#switch-result .progress-widget")
        widget.wait_for(state="visible")
        bar = page.locator("#switch-result [role=progressbar]")
        assert bar.get_attribute("aria-valuenow") is not None
        shot(page, "switch-progress")

        # The bar moves, the clock ticks and a time-left line is shown.
        first_clock = page.inner_text(".pw-elapsed")
        page.wait_for_function(
            "() => Number("
            "document.querySelector('[role=progressbar]').getAttribute('aria-valuenow')) > 0"
        )
        page.wait_for_function(
            "(c) => document.querySelector('.pw-elapsed').textContent !== c", arg=first_clock
        )
        assert re.search(r"left|Estimating|longer than expected", page.inner_text(".pw-left"))
        assert re.search(r"Section \d+ of \d+: \S", page.inner_text(".pw-step"))
        assert (
            page.evaluate(
                "() => getComputedStyle(document.querySelector('.pw-fill')).animationName"
            )
            != "none"
        )
        bad = [v for v in _axe(page) if v["impact"] in BLOCKING]
        assert not bad, [v["id"] for v in bad]

        # Cancel: nothing is written, and the form is back.
        page.click(".progress-widget button.danger")
        page.wait_for_selector("#switch-result .progress-widget", state="detached")
        assert page.locator("#form-switch").is_visible()
        assert not list((vault).rglob("Archive/*.md"))

        # Again, to the end: the preview appears and Apply switches the template.
        page.click("#form-switch button[type=submit]")
        page.wait_for_selector("#switch-apply", timeout=60_000)
        with page.expect_navigation():  # the page reloads once the switch is applied
            page.click("#switch-apply")
        page.wait_for_selector("#preview:not([hidden]) h2")
        assert list(vault.rglob("Archive/*.md"))  # the previous note was archived (R12)


def test_closing_the_dialog_keeps_the_switch_running_in_the_background(
    server: tuple[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, _ = server
    url = written_note(base, make_tone(tmp_path / "2026-10-11 Background.m4a", 20.0))
    monkeypatch.setenv("MM3_FAKE_LLM_SECONDS", "0.5")
    with browser_page(base) as page:
        page.goto(url)
        page.wait_for_selector("#preview:not([hidden]) h2")
        open_switch(page)
        page.click("#form-switch button[type=submit]")
        page.wait_for_selector("#switch-result .progress-widget")
        page.keyboard.press("Escape")  # asks instead of closing
        assert page.locator("#switch-ask").is_visible()
        page.click("#switch-keep")
        assert not page.locator("#dlg-switch").is_visible()
        assert "running" in page.inner_text("#btn-switch-bg")
        # A reload picks the running (or finished) switch up again.
        page.reload()
        page.wait_for_selector("#btn-switch-bg:not([hidden])")
        page.click("#btn-switch-bg")
        page.wait_for_selector("#switch-apply", timeout=60_000)


def test_reduced_motion_drops_the_animation_but_the_clock_ticks(
    server: tuple[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, _ = server
    url = written_note(base, make_tone(tmp_path / "2026-10-11 Reduced.m4a", 20.0))
    monkeypatch.setenv("MM3_FAKE_LLM_SECONDS", "0.6")
    with browser_page(base, reduced_motion="reduce") as page:
        page.goto(url)
        page.wait_for_selector("#preview:not([hidden]) h2")
        open_switch(page)
        page.click("#form-switch button[type=submit]")
        page.wait_for_selector("#switch-result .progress-widget")
        assert (
            page.evaluate(
                "() => getComputedStyle(document.querySelector('.pw-fill')).animationName"
            )
            == "none"
        )
        before = page.inner_text(".pw-elapsed")
        page.wait_for_function(
            "(c) => document.querySelector('.pw-elapsed').textContent !== c", arg=before
        )
        page.click(".progress-widget button.danger")


def test_recording_size_download_and_the_action_labelled_toggle(
    server: tuple[str, Path], tmp_path: Path
) -> None:
    base, _ = server
    url = written_note(base, make_tone(tmp_path / "2026-10-11 Download.m4a", 5.0))
    with browser_page(base, bypass_csp=True) as page:
        page.goto(url)
        page.wait_for_selector("#preview:not([hidden]) h2")
        info = page.inner_text("#rec-info")
        assert re.search(r"Recording: \d+(\.\d)? (B|kB|MB) \(Opus\)", info), info
        shot(page, "review-size-download")
        with page.expect_download() as download:
            page.click("#rec-download")
        assert download.value.suggested_filename == "2026-10-11 - Download.opus"

        # The toggle always names what clicking it does.
        button = page.locator("#btn-mode")
        assert button.inner_text() == "Edit note" and page.inner_text("#mode-label") == "Viewing"
        button.click()
        assert button.inner_text() == "Show preview" and page.inner_text("#mode-label") == "Editing"
        assert page.locator("#editor").is_visible()
        bad = [v for v in _axe(page) if v["impact"] in BLOCKING]
        assert not bad, ("edit", [v["id"] for v in bad])
        button.click()
        page.wait_for_selector("#preview:not([hidden])")
        bad = [v for v in _axe(page) if v["impact"] in BLOCKING]
        assert not bad, ("preview", [v["id"] for v in bad])
        assert button.inner_text() == "Edit note"
        assert page.evaluate("() => localStorage.getItem('mm3.review.mode')") == "preview"


def test_meetings_pages_its_jobs_and_browses_the_vault(
    server: tuple[str, Path], tmp_path: Path
) -> None:
    base, _ = server
    audio = make_tone(tmp_path / "2026-10-11 Many.m4a", 2.0)
    written_note(base, audio)
    with api(base) as client:
        for _ in range(11):
            wait(client, upload(client, audio, {}).json()["id"], "waiting_for_input", timeout=30)  # type: ignore[arg-type]
    with browser_page(base, bypass_csp=True) as page:
        page.goto(base + "/meetings")
        assert page.title() == "Meetings · MeetingMaster3" and page.inner_text("h1") == "Meetings"
        assert page.locator("nav[aria-label=Main] a", has_text="Open a note").count() == 0
        assert page.locator("#sec-jobs tbody tr").count() == 10
        nav = page.locator('nav[aria-label="Jobs pages"]')
        assert "Page 1 of 2" in nav.inner_text()
        nav.get_by_role("link", name="Older").click()
        page.wait_for_function("() => document.querySelectorAll('#sec-jobs tbody tr').length === 2")
        assert page.url.endswith("/meetings?jobs_page=2")
        assert page.evaluate("() => document.activeElement.id") == "h-jobs"
        shot(page, "meetings-paged")
        bad = [v for v in _axe(page) if v["impact"] in BLOCKING]
        assert not bad, [v["id"] for v in bad]
        page.reload()  # bookmarkable: the same page again
        assert page.locator("#sec-jobs tbody tr").count() == 2

        # Browse the vault at the bottom of the page opens a folder.
        picker = page.locator("#picker")
        picker.get_by_role("button", name="Meetings", exact=True).click()
        picker.get_by_role("button", name="2026", exact=True).wait_for()
        # The old Open-a-note address still lands here.
        page.goto(base + "/open")
        assert page.url.endswith("/meetings")
