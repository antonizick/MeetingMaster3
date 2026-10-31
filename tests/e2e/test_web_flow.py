"""Browser smoke test of the core flow (Phase 10): upload -> name speakers -> note in the vault.

Runs a real server with the fake pipeline and drives it with Playwright. Needs Chromium: set
``MM3_E2E_BROWSER`` to its path (e.g. /usr/bin/chromium) or run ``playwright install chromium``.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from meetingmaster3.app import create_app
from meetingmaster3.config.settings import Settings
from tests.unit.jobs.helpers import make_tone, requires_ffmpeg

pytestmark = [pytest.mark.e2e, requires_ffmpeg]
playwright_sync = pytest.importorskip("playwright.sync_api")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, Path]]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0.3")
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    port = free_port()
    settings = Settings()
    settings.server.port = port
    app = create_app(settings)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", vault
    srv.should_exit = True
    thread.join(10)


def test_happy_path_in_a_browser(server: tuple[str, Path], tmp_path: Path) -> None:
    base, vault = server
    audio = make_tone(tmp_path / "2026-10-11 Product Sync.m4a", 2.0)
    external: list[str] = []
    with playwright_sync.sync_playwright() as pw:
        exe = os.environ.get("MM3_E2E_BROWSER") or None
        try:
            browser = pw.chromium.launch(executable_path=exe)
        except playwright_sync.Error as exc:
            pytest.skip(f"no Chromium available for Playwright: {exc}")
        page = browser.new_page()
        page.on(
            "request",
            lambda r: (
                external.append(r.url) if not r.url.startswith((base, "data:", "blob:")) else None
            ),
        )
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(base)
        page.wait_for_url("**/setup")
        page.fill("#vault_path", str(vault))
        page.wait_for_selector("text=is a writable folder")
        page.click("text=Save and continue")
        page.wait_for_url(base + "/")

        page.wait_for_load_state("networkidle")  # Alpine must be running before the file is chosen
        page.set_input_files("#file", str(audio))
        playwright_sync.expect(page.locator("#title")).to_have_value("Product Sync")
        playwright_sync.expect(page.locator("#meeting_date")).to_have_value("2026-10-11")
        page.wait_for_selector("#hardware-panel dl.facts")
        page.click("text=Accept settings & start")

        page.wait_for_url("**/jobs/*")
        page.click("text=Name speakers")
        page.wait_for_selector("#speakers-form")
        page.fill("input[name=name__SPEAKER_00]", "Alice")
        page.fill("input[name=name__SPEAKER_01]", "Bob")
        page.click("text=Confirm & write notes")
        page.wait_for_selector("text=Written to your vault", timeout=30000)
        assert page.locator("a[href^='obsidian://open?path=']").count() == 1
        page.click("text=Review & edit")
        page.wait_for_selector("#preview:not([hidden]) h2")
        browser.close()

    notes = [p for p in vault.rglob("*.md") if "MeetingMaster3" not in p.parts]
    assert any(not p.name.endswith(".transcript.md") for p in notes), notes
    assert not external, f"the browser contacted other hosts: {external}"
    assert not errors, errors
