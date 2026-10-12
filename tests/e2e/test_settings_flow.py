"""Browser smoke test of Settings and the template library (Phase 12).

Runs a real server and drives it with Playwright (see ``test_web_flow.py`` for the browser
setup): change a setting and see it survive a reload, then duplicate a template.
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
from meetingmaster3.config.settings import Settings, load_settings

pytestmark = pytest.mark.e2e
playwright_sync = pytest.importorskip("playwright.sync_api")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, Path, Path]]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    port = free_port()
    settings = Settings()
    settings.server.port = port
    settings.vault.path = vault
    app = create_app(settings)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", vault, app.state.paths.config_file
    srv.should_exit = True
    thread.join(10)


def test_save_a_setting_and_duplicate_a_template(server: tuple[str, Path, Path]) -> None:
    base, vault, config_file = server
    external: list[str] = []
    errors: list[str] = []
    with playwright_sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("MM3_E2E_BROWSER") or None)
        except playwright_sync.Error as exc:
            pytest.skip(f"no Chromium available for Playwright: {exc}")
        page = browser.new_page()
        page.on(
            "request",
            lambda r: (
                external.append(r.url) if not r.url.startswith((base, "data:", "blob:")) else None
            ),
        )
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(base + "/settings")
        page.wait_for_url("**/settings/vault")
        page.click("nav[aria-label='Settings sections'] >> text=Notes & jobs")
        page.wait_for_selector("#f-generation-max_context")
        page.fill("#f-generation-max_context", "24576")
        page.click("form >> text=Save")
        page.wait_for_selector("text=✓ Saved.")
        page.reload()
        playwright_sync.expect(page.locator("#f-generation-max_context")).to_have_value("24576")
        assert load_settings(config_file).generation.max_context == 24576

        page.fill("#f-generation-max_context", "5")  # below the allowed minimum
        page.click("form >> text=Save")
        page.wait_for_selector("text=Some values need fixing")
        assert load_settings(config_file).generation.max_context == 24576

        page.goto(base + "/templates")
        page.wait_for_selector("text=Executive Summary")
        card = page.locator("li.card", has_text="Executive Summary").first
        card.locator("button", has_text="Duplicate").click()
        page.wait_for_selector("text=Executive Summary (copy)")
        browser.close()

    assert (vault / "MeetingMaster3" / "templates" / "Executive Summary (copy).md").is_file()
    assert not external, f"the browser contacted other hosts: {external}"
    assert not errors, errors
