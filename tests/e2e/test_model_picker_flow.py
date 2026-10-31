"""Browser test of the cloud model picker (Phase 15h): choose a recommended model on New meeting
and in Settings, with a fake OpenRouter that lists priced models."""

from __future__ import annotations

import asyncio
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
from meetingmaster3.llm.base import ModelInfo
from meetingmaster3.llm.openai_compat import OpenAICompatBackend

pytestmark = pytest.mark.e2e
playwright_sync = pytest.importorskip("playwright.sync_api")

HAIKU = "anthropic/claude-haiku-5.5"
SONNET = "anthropic/claude-sonnet-5.5"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def priced(
    model_id: str, name: str, price_in: float, price_out: float, **extra: object
) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        name=name,
        context_window=200_000,
        price_in=price_in,
        price_out=price_out,
        price_source="live",
        text_only=True,
        **extra,  # type: ignore[arg-type]
    )


FAKE_MODELS = [
    priced(HAIKU, "Anthropic: Claude Haiku 5.5", 0.1, 0.5),
    priced(SONNET, "Anthropic: Claude Sonnet 5.5", 2.0, 10.0),
    priced("meta/llama-4-maverick", "Meta: Llama 4 Maverick", 0.15, 0.6),
    priced("deepseek/deepseek-r1-0528", "DeepSeek: R1", 0.5, 2.0),
]


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")

    async def fake_list(self: OpenAICompatBackend) -> list[ModelInfo]:
        await asyncio.sleep(1.5)  # a real provider takes a moment: the sync banner shows
        return list(FAKE_MODELS)

    monkeypatch.setattr(OpenAICompatBackend, "list_models", fake_list)
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    port = free_port()
    settings = Settings()
    settings.server.port = port
    settings.vault.path = vault
    settings.llm.backends = {
        "or_": BackendConfig(kind="openrouter", api_key="sk-or-v1-fakefakefakefake12345")
    }
    settings.register_secrets()
    app = create_app(settings)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(10)


def shot(page: object, name: str) -> None:
    folder = os.environ.get("MM3_E2E_SCREENSHOTS")
    if folder:
        page.screenshot(path=str(Path(folder) / f"{name}.png"), full_page=False)  # type: ignore[attr-defined]


def test_choose_a_recommended_cloud_model_on_new_meeting(server: str) -> None:
    errors: list[str] = []
    with playwright_sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("MM3_E2E_BROWSER") or None)
        except playwright_sync.Error as exc:
            pytest.skip(f"no Chromium available for Playwright: {exc}")
        page = browser.new_page(viewport={"width": 1100, "height": 1000})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(server)
        page.wait_for_load_state("networkidle")  # Alpine must be running before we act
        page.select_option("#backend", "or_")
        page.click("text=Allow for this meeting")
        picker = page.locator("#model-picker select")
        picker.wait_for()
        # Best value is pre-selected into the model input, and both picks are explained.
        playwright_sync.expect(page.locator("#model")).to_have_value(HAIKU)
        text = page.inner_text("#model-picker")
        assert "Best value: Anthropic: Claude Haiku 5.5." in text
        assert "Best quality: Anthropic: Claude Sonnet 5.5." in text
        options = picker.locator("option").all_inner_texts()
        assert any("$0.10 in / $0.50 out per 1M tokens" in o and "(estimate)" in o for o in options)
        assert not any("DeepSeek" in o for o in options)  # measured as unsuitable: hidden
        page.locator("#model-picker").scroll_into_view_if_needed()
        shot(page, "08-model-picker")

        picker.select_option(label=next(o for o in options if o.startswith("Best quality")))
        playwright_sync.expect(page.locator("#model")).to_have_value(SONNET)

        page.click("text=Show all models (1 hidden)")
        page.wait_for_selector("#model-picker >> text=Showing all")
        shown = page.locator("#model-picker select option").all_inner_texts()
        assert any("DeepSeek" in o and "Measured as unsuitable" in o for o in shown)

        page.fill("#model", "my/custom-model")  # a typed id still works
        playwright_sync.expect(page.locator("#model")).to_have_value("my/custom-model")
        browser.close()
    assert not errors


def test_new_meeting_says_it_is_synchronizing_while_models_load(server: str) -> None:
    with playwright_sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("MM3_E2E_BROWSER") or None)
        except playwright_sync.Error as exc:
            pytest.skip(f"no Chromium available for Playwright: {exc}")
        page = browser.new_page(viewport={"width": 1100, "height": 1000})
        page.goto(server)
        banner = page.locator(".sync")
        playwright_sync.expect(banner).to_be_hidden()  # nothing to wait for yet
        page.select_option("#backend", "or_")
        page.click("text=Allow for this meeting")
        playwright_sync.expect(banner).to_be_visible()
        assert "Synchronizing models" in banner.inner_text()
        page.wait_for_timeout(500)  # past the short fade-in delay
        shot(page, "10-model-sync")
        page.locator("#model-picker select").wait_for()  # the drop-down arrives ...
        playwright_sync.expect(banner).to_be_hidden()  # ... and the banner goes away
        browser.close()
