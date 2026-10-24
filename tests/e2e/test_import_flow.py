"""Phase 15k browser check: import the unlabelled voice-mode fixture from New meeting, flip one
turn on the check page (keyboard), write the notes and open the review page (with an axe-core
scan of the check page). Fake pipeline; needs Chromium (``MM3_E2E_BROWSER=/usr/bin/chromium``)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from meetingmaster3.markdown.transcript_format import parse_transcript
from meetingmaster3.vault.io import read_text
from tests.e2e import test_qa_flows as qa
from tests.e2e.test_qa_flows import BLOCKING, _axe, browser_page
from tests.unit.jobs.test_jobs_api import wait

pytestmark = [pytest.mark.e2e]
pytest.importorskip("playwright.sync_api")

server = qa.server
FIXTURE = Path(__file__).parents[1] / "fixtures" / "imports" / "voice-mode-unlabelled.md"


def test_import_flip_a_turn_and_write(server: tuple[str, Path]) -> None:
    base, vault = server
    with browser_page(base) as page:
        page.goto(base + "/")
        assert page.is_visible("#h-speakers")
        page.get_by_label("Import a transcript or AI conversation").check()
        assert page.inner_text("#h-audio") == "1. Transcript or conversation"
        assert not page.is_visible("#h-speakers") and not page.is_visible("#h-hw")
        assert ".md" in (page.get_attribute("#file", "accept") or "")
        page.set_input_files("#file", str(FIXTURE))
        page.fill("#participants", "Nick")
        page.get_by_role("button", name="Accept settings & start").click()
        page.wait_for_url(re.compile(r"/jobs/[0-9a-f-]{36}$"))
        page.get_by_role("link", name="Check the speakers").click(timeout=20_000)
        page.wait_for_selector("#import-form")

        violations = [v for v in _axe(page) if v["impact"] in BLOCKING]
        assert not violations, violations
        assert page.input_value("#name-SPEAKER_00") == "Nick"
        page.fill("#name-SPEAKER_01", "Grok")
        turn = page.locator('li.import-turn[data-i="1"] button.who')
        assert turn.inner_text() == "Grok"  # renaming updates every turn of that speaker
        turn.focus()
        page.keyboard.press("Enter")  # keyboard-accessible toggle
        assert turn.inner_text() == "Nick"
        assert page.input_value('input[name="turn__1"]') == "SPEAKER_00"
        assert page.locator("li.import-turn.low").count() >= 1
        page.get_by_role("button", name="Confirm & write notes").click()
        page.wait_for_selector("text=Written to your vault", timeout=30_000)
        page.get_by_role("link", name="Review & edit").click()
        page.wait_for_selector("#imported-badge")
        assert "Imported from AI conversation (unlabelled)" in page.inner_text("#imported-badge")
        assert page.locator("#audio").count() == 0
        assert "Grok" in page.inner_text("#transcript")

    companion = next(vault.rglob("*.transcript.md"))
    doc = parse_transcript(read_text(companion)).doc
    assert doc.transcript.segments[1].speaker_label == "SPEAKER_00"
    assert doc.speakers.names == {"SPEAKER_00": "Nick", "SPEAKER_01": "Grok"}


def test_a_timed_import_jumps_to_the_clicked_time(server: tuple[str, Path]) -> None:
    base, _ = server
    source = FIXTURE.with_name("timestamped.txt")
    with qa.api(base) as client, source.open("rb") as fh:
        job = client.post(
            "/api/imports",
            files={"file": (source.name, fh, "text/plain")},
            data={"options": '{"import_confirmed": true}'},
        ).json()
        wait(client, job["id"], "written", timeout=30)  # type: ignore[arg-type]
        written = client.get(f"/jobs/{job['id']}").text
    url = re.search(r'href="(/meetings/[^"]+)"', written)
    assert url
    with browser_page(base) as page:
        page.goto(base + url.group(1).replace("&amp;", "&"))
        assert page.locator("#audio").count() == 0
        page.locator('.ts[data-t="62.0"]').click()
        current = page.locator(".seg.current")
        assert current.count() == 1 and "login page" in current.inner_text()


# -- Phase 15l: a Grok share link (the download is faked; no request leaves the machine) ---------

SHARE_LINK = "https://grok.com/share/c3ludGhldGlj_0f8b5c3e-1111-4222-8333-944445555666"


def test_paste_a_share_link(server: tuple[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    from meetingmaster3.importing import stages as stages_mod

    body = FIXTURE.with_name("grok-share-linear.json").read_bytes()
    monkeypatch.setattr(stages_mod, "fetch_share", lambda share_id, **kw: body)
    base, vault = server
    with browser_page(base) as page:
        page.goto(base + "/")
        assert not page.is_visible("#share_url")
        page.get_by_label("Import a transcript or AI conversation").check()
        page.get_by_label("Or paste a Grok share link").fill(SHARE_LINK)
        page.get_by_role("button", name="Accept settings & start").click()
        page.wait_for_url(re.compile(r"/jobs/[0-9a-f-]{36}$"), timeout=20_000)
        page.get_by_role("link", name="Check the speakers").click(timeout=20_000)
        page.wait_for_selector("#import-form")
        assert "00:12" in page.inner_text("#import-form")
        assert page.locator("li.import-turn.low").count() == 0
        violations = [v for v in _axe(page) if v["impact"] in BLOCKING]
        assert not violations, violations
        page.get_by_role("button", name="Confirm & write notes").click()
        page.wait_for_selector("text=Written to your vault", timeout=30_000)
    note = next(vault.rglob("*community garden*.transcript.md"))
    assert parse_transcript(read_text(note)).doc.transcript.timed


def test_a_failed_download_shows_inline_and_upload_still_works(
    server: tuple[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from meetingmaster3.importing import stages as stages_mod
    from meetingmaster3.importing.fetch import offline

    def fail(share_id: str, **kw: object) -> bytes:
        raise offline("ConnectError")

    monkeypatch.setattr(stages_mod, "fetch_share", fail)
    base, _ = server
    with browser_page(base) as page:
        page.goto(base + "/?mode=import")
        page.fill("#share_url", "https://chatgpt.com/share/abc")
        page.get_by_role("button", name="Accept settings & start").click()
        page.wait_for_selector("text=Only Grok share links")
        page.fill("#share_url", SHARE_LINK)
        page.get_by_role("button", name="Accept settings & start").click()
        page.wait_for_selector("text=Are you offline?", timeout=20_000)
        assert "export the conversation to Markdown" in page.inner_text("[role=alert]")
        assert page.url.rstrip("/").endswith("?mode=import")
        page.fill("#share_url", "")
        page.set_input_files("#file", str(FIXTURE))
        page.get_by_role("button", name="Accept settings & start").click()
        page.wait_for_url(re.compile(r"/jobs/[0-9a-f-]{36}$"))
