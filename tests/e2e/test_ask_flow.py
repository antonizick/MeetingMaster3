"""Browser test (Phase 15j): ask a question with the offline fake model, see the cited answer
and its table, open a cited meeting, and come back to the answer from the meeting's review page.
With ``MM3_E2E_SCREENSHOTS=<dir>`` it saves ``11-ask.png`` (the answer) for the docs."""

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
from meetingmaster3.config.settings import BackendConfig, Settings
from tests import ask_corpus

pytestmark = pytest.mark.e2e
playwright_sync = pytest.importorskip("playwright.sync_api")

QUESTION = (
    "How many times have we discussed the budget overrun and spending more than planned? Who "
    "took part, and in what role? Make a table of the meetings, dates and attendees."
)


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, object]]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_LLM_SECONDS", "0.2")
    monkeypatch.delenv("MM3_SEARCH__ENABLED", raising=False)
    for name in ("CONFIG", "DATA", "CACHE"):
        monkeypatch.setenv(f"XDG_{name}_HOME", str(tmp_path / name.lower()))
    vault = ask_corpus.write_vault(tmp_path / "vault")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    settings = Settings()
    settings.server.port = port
    settings.vault.path = vault
    settings.llm.backends["ollama"] = BackendConfig(kind="ollama", default_model="qwen3:8b")
    app = create_app(settings)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        search = getattr(app.state, "search", None)
        if srv.started and search is not None:
            st = search.status()
            ready = st["meetings"] == len(ask_corpus.MEETINGS) and st["vectors_complete"]
            if ready and not st["running"]:
                break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}", app
    srv.should_exit = True
    thread.join(10)


def test_ask_answer_open_a_meeting_and_come_back(server: tuple[str, object]) -> None:
    url, _ = server
    errors: list[str] = []
    with playwright_sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("MM3_E2E_BROWSER") or None)
        except playwright_sync.Error as exc:
            pytest.skip(f"no Chromium available for Playwright: {exc}")
        page = browser.new_page(viewport={"width": 1100, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{url}/ask")
        page.wait_for_selector("#ask-consent >> text=Runs on this computer")
        page.fill("#ask-q", QUESTION)
        page.click("#ask-submit")
        page.wait_for_selector(".progress-widget")  # the long-task widget with its steps
        page.wait_for_url("**/ask/*", timeout=30_000)
        page.wait_for_selector("article.ask-answer table")
        text = page.inner_text("article.ask-answer")
        assert "Q3 Finance Review" in text and "Dana Whitfield" in text
        folder = os.environ.get("MM3_E2E_SCREENSHOTS")
        if folder:
            page.screenshot(path=str(Path(folder) / "11-ask.png"), full_page=True)
        answer_url = page.url
        page.click("article.ask-answer table >> a:has-text('2026-09-02 - Q3 Finance Review')")
        page.wait_for_url("**/meetings/**")
        page.click("#cited-by summary")
        page.click(f"#cited-by a[href='{answer_url.removeprefix(url)}']")
        page.wait_for_url(answer_url)
        page.goto(f"{url}/ask")
        assert page.locator("#ask-history a").count() == 1
        browser.close()
    assert errors == []
