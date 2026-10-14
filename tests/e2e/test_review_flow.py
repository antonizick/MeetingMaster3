"""Browser test of the review workspace (Phase 11): seek from the transcript, regenerate a
section with the fake LLM, accept with archive, save, and check the file in the vault.

Needs Chromium (``MM3_E2E_BROWSER=/usr/bin/chromium``). ``MM3_E2E_SCREENSHOTS=<dir>`` saves
screenshots of the workspace.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn

from meetingmaster3.app import create_app
from meetingmaster3.config.settings import Settings
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.sections import scan_sections
from tests.e2e.test_web_flow import free_port
from tests.unit.jobs.helpers import make_tone, requires_ffmpeg
from tests.unit.jobs.test_jobs_api import upload, wait

pytestmark = [pytest.mark.e2e, requires_ffmpeg]
playwright_sync = pytest.importorskip("playwright.sync_api")
SPEAKERS = {"SPEAKER_00": {"name": "Alice"}, "SPEAKER_01": {"name": "Bob"}}


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, Path]]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    port = free_port()
    settings = Settings()
    settings.server.port = port
    settings.vault.path = vault.resolve()
    srv = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", vault.resolve()
    srv.should_exit = True
    thread.join(10)


def written_note(base: str, audio: Path) -> str:
    """Process ``audio`` through the fake pipeline over HTTP; returns the workspace URL."""
    with httpx.Client(base_url=base, timeout=30) as client:
        client.get("/healthz")
        client.headers["X-CSRF-Token"] = client.cookies["mm3_csrf"]
        job = upload(client, audio, {}).json()  # type: ignore[arg-type]
        wait(client, job["id"], "waiting_for_input", timeout=30)  # type: ignore[arg-type]
        client.post(f"/api/jobs/{job['id']}/speakers", json=SPEAKERS).raise_for_status()
        wait(client, job["id"], "written", timeout=30)  # type: ignore[arg-type]
        page = client.get(f"/jobs/{job['id']}").text
    link = re.search(r'href="(/meetings/[^"]+)"', page)
    assert link, page
    return base + link.group(1).replace("&amp;", "&")


def shot(page: object, name: str) -> None:
    folder = os.environ.get("MM3_E2E_SCREENSHOTS")
    if folder:
        page.screenshot(path=str(Path(folder) / f"{name}.png"), full_page=False)  # type: ignore[attr-defined]


def test_review_regenerate_archive_save(server: tuple[str, Path], tmp_path: Path) -> None:
    base, vault = server
    url = written_note(base, make_tone(tmp_path / "2026-10-11 Product Sync.m4a", 30.0))
    note = next(p for p in vault.rglob("2026-10-11 - Product Sync.md"))
    before = note.read_text("utf-8")
    external: list[str] = []
    errors: list[str] = []
    with playwright_sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("MM3_E2E_BROWSER") or None)
        except playwright_sync.Error as exc:
            pytest.skip(f"no Chromium available for Playwright: {exc}")
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on(
            "request",
            lambda r: (
                external.append(r.url) if not r.url.startswith((base, "data:", "blob:")) else None
            ),
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.goto(url)
        page.wait_for_selector("#preview:not([hidden]) h2")  # opens on the rendered note
        assert page.locator("#editor").is_hidden()
        shot(page, "review-workspace")
        assert (
            page.inner_text("#btn-mode") == "Edit note"
            and page.inner_text("#mode-label") == "Viewing"
        )
        page.click("#btn-mode")
        page.wait_for_selector("#editor textarea.sec")
        assert page.inner_text("#btn-mode") == "Show preview"
        assert page.inner_text("#mode-label") == "Editing"

        # Clicking a timestamp in the transcript seeks the audio.
        stamp = page.locator(".transcript .ts").nth(2)
        target = float(stamp.get_attribute("data-t") or 0)
        assert target > 1
        stamp.click()
        page.wait_for_function(
            f"Math.abs(document.getElementById('audio').currentTime - {target}) < 0.6"
        )
        page.evaluate("document.getElementById('audio').pause()")
        assert page.locator(".seg.current").count() == 1

        # Personal text outside the markers, then regenerate the summary.
        own = page.locator('textarea[data-kind="text"]').nth(1)
        own.fill("My own aside, outside the markers.")
        page.wait_for_selector("#save-status:has-text('Unsaved')")
        page.click('.regen-btn[data-section-id="summary"]')
        page.fill("#regen-instructions", "Make it shorter.")
        page.click("#form-regen button[type=submit]")
        page.wait_for_selector('.regen-result[data-section-id="summary"] .regen-box')
        page.click(".regen-box >> text=Unified")
        page.click(".regen-box >> text=Side by side")
        page.locator(".regen-box").scroll_into_view_if_needed()
        shot(page, "review-regenerate-diff")
        page.click("text=Accept & archive previous")
        page.wait_for_selector("text=Previous version archived.")
        page.click("#btn-save")
        page.wait_for_selector("#save-status:has-text('Saved to vault')")

        # The rendered preview turns [mm:ss] references into seek buttons.
        page.click("#btn-mode")
        page.wait_for_selector("#preview:not([hidden]) h2")
        assert page.inner_text("#btn-mode") == "Edit note"
        shot(page, "review-preview")
        browser.close()

    after = note.read_text("utf-8")
    assert "My own aside, outside the markers." in after
    assert after != before
    parsed = parse_note(after)
    assert parsed.ok and {s.id for s in parsed.note.sections} == {
        s.id for s in parse_note(before).note.sections
    }
    archives = list((note.parent / "Archive").glob("2026-10-11 - Product Sync.summary.*.md"))
    assert len(archives) == 1 and "mm3-archived-section: summary" in archives[0].read_text("utf-8")
    # Outside the summary section and the edited gap, the file is byte-identical.
    span_before = scan_sections(before).get("summary")
    span_after = scan_sections(after).get("summary")
    assert span_before and span_after
    assert after[: span_after.inner_start] == before[: span_before.inner_start]
    assert not external, f"the browser contacted other hosts: {external}"
    assert not errors, errors


def test_preview_first_edit_then_keep_forever(server: tuple[str, Path], tmp_path: Path) -> None:
    base, vault = server
    url = written_note(base, make_tone(tmp_path / "2026-10-11 Keep Me.m4a", 20.0))
    note = next(p for p in vault.rglob("2026-10-11 - Keep Me.md"))
    with playwright_sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("MM3_E2E_BROWSER") or None)
        except playwright_sync.Error as exc:
            pytest.skip(f"no Chromium available for Playwright: {exc}")
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(url)
        page.wait_for_selector("#preview:not([hidden]) h2")
        assert page.inner_text("#btn-mode") == "Edit note"
        assert page.locator("#editor").is_hidden()
        shot(page, "review-preview-retention")

        # Edit, type, Preview shows the unsaved edit, then Save.
        page.click("#btn-mode")
        page.locator('textarea[data-kind="text"]').nth(1).fill("Typed in the editor.")
        page.click("#btn-mode")
        page.wait_for_selector("#preview:not([hidden]):has-text('Typed in the editor.')")
        page.click("#btn-save")
        page.wait_for_selector("#save-status:has-text('Saved to vault')")
        assert page.locator("#preview").is_visible()  # Save keeps the mode
        assert "Typed in the editor." in note.read_text("utf-8")

        # Keep forever -> the line changes -> a reload keeps it -> Allow deletion -> days are back.
        assert "deleted in 90 days" in page.inner_text("#retention-text")
        page.click("#retention-btn")
        page.wait_for_selector("#retention-text:has-text('Recording kept forever')")
        page.reload()
        page.wait_for_selector("#retention-text:has-text('Recording kept forever')")
        page.click("#retention-btn")
        page.wait_for_selector("#dlg-unkeep[open]")
        assert "will be deleted in 90 days" in page.inner_text("#unkeep-message")
        page.click("#unkeep-ok")
        page.wait_for_selector("#retention-text:has-text('deleted in 90 days')")
        shot(page, "review-retention-line")
        browser.close()
