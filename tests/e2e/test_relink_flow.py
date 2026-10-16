"""Browser test: re-link Meetings entries whose notes moved with the vault."""

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
from meetingmaster3.storage.db import Database
from meetingmaster3.storage.repositories import RecentMeetingsRepository

pytestmark = pytest.mark.e2e
playwright_sync = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, Path]]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    for name in ("CONFIG", "DATA", "CACHE"):
        monkeypatch.setenv(f"XDG_{name}_HOME", str(tmp_path / name.lower()))
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    note = vault / "Meetings" / "2026" / "2026-10-01 - Standup.md"
    note.parent.mkdir(parents=True)
    note.write_text('---\nmm3-id: "id-1"\ntitle: Standup\ndate: 2026-10-01\n---\n# T\n', "utf-8")
    # The entry was made before the folder moved: it points at the old location.
    data = tmp_path / "data" / "meetingmaster3"
    data.mkdir(parents=True)
    db = Database.open(data / "mm3.db")
    RecentMeetingsRepository(db).touch(
        str(tmp_path / "OldVault" / "2026-10-01 - Standup.md"), mm3_id="id-1", title="Standup"
    )
    db.close()
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    settings = Settings()
    settings.server.port = port
    settings.vault.path = vault
    srv = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", note
    srv.should_exit = True
    thread.join(10)


def test_relink_an_orphaned_meeting(server: tuple[str, Path]) -> None:
    url, _ = server
    errors: list[str] = []
    with playwright_sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("MM3_E2E_BROWSER") or None)
        except playwright_sync.Error as exc:
            pytest.skip(f"no Chromium available for Playwright: {exc}")
        page = browser.new_page(viewport={"width": 1100, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{url}/meetings")
        assert "File not found" in page.inner_text("#sec-notes")
        page.click("text=Find them in the vault")
        page.wait_for_selector("#sec-notes >> text=Found: Meetings/2026/2026-10-01 - Standup.md")
        folder = os.environ.get("MM3_E2E_SCREENSHOTS")
        if folder:
            page.locator("#sec-notes").screenshot(path=str(Path(folder) / "09-relink.png"))
        page.once("dialog", lambda d: d.accept())
        page.click("#sec-notes >> text=Re-link 1 found")
        page.wait_for_selector("#sec-notes >> text=Re-linked 1 entry.")
        text = page.inner_text("#sec-notes")
        assert "File not found" not in text and "Open in Obsidian" in text
        page.click("#sec-notes >> text=Standup")  # the entry now opens the note
        page.wait_for_load_state()
        assert "Standup" in page.url  # opens the note (a bare fixture opens as a preview)
        assert "not found" not in page.inner_text("body").lower()
        browser.close()
    assert not errors
