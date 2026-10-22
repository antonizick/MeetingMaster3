"""Browser test (Phase 15i): search the corpus vault and open the meeting at the passage."""

from __future__ import annotations

import os
import shutil
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from meetingmaster3.app import create_app
from meetingmaster3.config.settings import Settings
from tests.search_corpus import FOLDER

pytestmark = pytest.mark.e2e
playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, object]]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.delenv("MM3_SEARCH__ENABLED")
    for name in ("CONFIG", "DATA", "CACHE"):
        monkeypatch.setenv(f"XDG_{name}_HOME", str(tmp_path / name.lower()))
    vault = tmp_path / "vault"
    shutil.copytree(FOLDER, vault)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    settings = Settings()
    settings.server.port = port
    settings.vault.path = vault
    app = create_app(settings)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        search = getattr(app.state, "search", None)
        if srv.started and search is not None:
            st = search.status()
            if st["meetings"] == 7 and st["vectors_complete"] and not st["running"]:
                break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}", app
    srv.should_exit = True
    thread.join(10)


def test_search_and_open_the_transcript_moment(server: tuple[str, object]) -> None:
    url, _ = server
    errors: list[str] = []
    with playwright_sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("MM3_E2E_BROWSER") or None)
        except playwright_sync.Error as exc:
            pytest.skip(f"no Chromium available for Playwright: {exc}")
        page = browser.new_page(viewport={"width": 1100, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{url}/search")
        page.fill("#s-q", "costs exceeded the forecast")
        page.keyboard.press("Enter")
        page.wait_for_selector("#search-results >> text=Vendor Contract Sync")
        assert "/search?q=costs" in page.url  # bookmarkable
        assert page.locator("#search-results mark").count() > 0
        folder = os.environ.get("MM3_E2E_SCREENSHOTS")
        if folder:
            page.screenshot(path=str(Path(folder) / "10-search.png"), full_page=True)
        page.click("#search-results >> a:has-text('Transcript · 00:00:00')")
        page.wait_for_url("**/meetings/**#t=0")
        page.wait_for_selector("#transcript .seg.current")
        assert "costs exceeded the forecast" in page.inner_text("#transcript .seg.current")
        assert page.title().startswith("Vendor Contract Sync") or "Vendor" in page.content()
        browser.close()
    assert errors == []
