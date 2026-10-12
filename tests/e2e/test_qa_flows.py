"""Phase 15 browser QA: re-open from the vault, the cloud-consent dialog, the out-of-memory retry
path, error pages, keyboard operation and an axe-core accessibility scan of the main pages.

Runs a real server with the fake pipeline (``MM3_FAKE_PIPELINE=1``). Needs Chromium: set
``MM3_E2E_BROWSER=/usr/bin/chromium`` or run ``playwright install chromium``. axe-core is vendored
for tests only (``tests/e2e/vendor/axe.min.js``, MPL-2.0).
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from pydantic import SecretStr

from meetingmaster3.app import create_app
from meetingmaster3.config.settings import BackendConfig, Settings
from tests.e2e.test_review_flow import SPEAKERS, written_note
from tests.e2e.test_web_flow import free_port
from tests.unit.jobs.helpers import make_tone, requires_ffmpeg
from tests.unit.jobs.test_jobs_api import upload, wait

pytestmark = [pytest.mark.e2e, requires_ffmpeg]
playwright_sync = pytest.importorskip("playwright.sync_api")
AXE = Path(__file__).with_name("vendor") / "axe.min.js"
#: axe impact levels that fail the scan (minor/moderate ones are reported, not fatal).
BLOCKING = {"serious", "critical"}


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[str, Path]]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    vault = (tmp_path / "vault").resolve()
    (vault / ".obsidian").mkdir(parents=True)
    port = free_port()
    settings = Settings()
    settings.server.port = port
    settings.vault.path = vault
    settings.llm.backends["cloud"] = BackendConfig(
        kind="openrouter", api_key=SecretStr("sk-e2e-not-a-real-key-000")
    )
    srv = uvicorn.Server(
        uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", vault
    srv.should_exit = True
    thread.join(10)


@contextmanager
def browser_page(base: str, **context: Any) -> Iterator[Any]:
    """A page that fails the test on script errors or requests to any other host."""
    external: list[str] = []
    errors: list[str] = []
    with playwright_sync.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("MM3_E2E_BROWSER") or None)
        except playwright_sync.Error as exc:
            pytest.skip(f"no Chromium available for Playwright: {exc}")
        page = browser.new_context(viewport={"width": 1280, "height": 900}, **context).new_page()
        page.on(
            "request",
            lambda r: (
                external.append(r.url) if not r.url.startswith((base, "data:", "blob:")) else None
            ),
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        yield page
        browser.close()
    assert not external, f"the browser contacted other hosts: {external}"
    assert not errors, errors


@contextmanager
def api(base: str) -> Iterator[httpx.Client]:
    with httpx.Client(base_url=base, timeout=30) as client:
        client.get("/healthz")
        client.headers["X-CSRF-Token"] = client.cookies["mm3_csrf"]
        yield client


def test_reopen_a_note_from_the_vault_picker(server: tuple[str, Path], tmp_path: Path) -> None:
    base, _ = server
    written_note(base, make_tone(tmp_path / "2026-10-11 Design Review.m4a", 10.0))
    with browser_page(base) as page:
        page.goto(base + "/open")
        picker = page.locator("#picker")
        picker.get_by_role("button", name="Meetings", exact=True).click()
        picker.get_by_role("button", name="2026", exact=True).click()
        picker.get_by_role("link", name="Design Review", exact=True).click()
        page.wait_for_url(re.compile(r"/meetings/[0-9a-f-]{36}\?path="))
        page.wait_for_selector("#editor textarea.sec")
        assert "Design Review" in page.inner_text("main")


def test_cloud_consent_dialog_can_switch_to_a_local_model(
    server: tuple[str, Path], tmp_path: Path
) -> None:
    base, vault = server
    audio = make_tone(tmp_path / "2026-10-11 Budget.m4a", 5.0)
    with api(base) as client:
        job = upload(client, audio, {"backend": "cloud"}).json()  # type: ignore[arg-type]
        wait(client, job["id"], "waiting_for_input", timeout=30)  # type: ignore[arg-type]
        client.post(f"/api/jobs/{job['id']}/speakers", json=SPEAKERS).raise_for_status()
        wait(client, job["id"], "waiting_for_input", timeout=30)  # type: ignore[arg-type]
    with browser_page(base) as page:
        page.goto(f"{base}/jobs/{job['id']}")
        page.wait_for_selector("text=Send the transcript to cloud?")
        assert page.locator(".badge:has-text('cloud')").count() >= 1 or page.locator("text=cloud: ")
        page.click("text=Use a local model instead")
        page.wait_for_selector("text=Written to your vault", timeout=30_000)
    assert list(vault.rglob("2026-10-11 - Budget.md"))


def test_out_of_memory_offers_a_smaller_model(
    server: tuple[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base, _ = server
    monkeypatch.setenv("MM3_FAKE_OOM", "1")
    audio = make_tone(tmp_path / "2026-10-11 Long Call.m4a", 5.0)
    with api(base) as client:
        job = upload(client, audio, {}).json()  # type: ignore[arg-type]
        wait(client, job["id"], "failed", timeout=30)  # type: ignore[arg-type]
    with browser_page(base) as page:
        page.goto(f"{base}/jobs/{job['id']}")
        page.wait_for_selector("text=ran out of memory")
        page.click("text=Retry with smaller model (medium)")
        page.wait_for_selector("text=Who is speaking?", timeout=30_000)
    with api(base) as client:
        detail = client.get(f"/api/jobs/{job['id']}").json()
    assert detail["options"]["transcription_model"] == "medium"


@pytest.mark.parametrize(
    ("path", "text"),
    [
        (f"/jobs/{uuid.uuid4()}", "no job with id"),
        ("/jobs/not-a-job", "not a valid job id"),
        (f"/meetings/{uuid.uuid4()}?path=nowhere.md", "not found"),
        ("/open/note?path=../../etc/passwd", "outside the vault"),
    ],
)
def test_error_pages_are_friendly(server: tuple[str, Path], path: str, text: str) -> None:
    base, _ = server
    with browser_page(base) as page:
        response = page.goto(base + path)
        assert response is not None and 400 <= response.status < 500
        assert text.lower() in page.inner_text("main").lower()
        assert page.locator("nav a[href='/']").count() >= 1  # a way back


def test_keyboard_only_core_controls(server: tuple[str, Path], tmp_path: Path) -> None:
    """The upload form and the review workspace work from the keyboard."""
    base, _ = server
    url = written_note(base, make_tone(tmp_path / "2026-10-11 Keyboard.m4a", 30.0))
    with browser_page(base) as page:
        page.goto(base + "/")
        reached: set[str] = set()
        for _ in range(40):
            page.keyboard.press("Tab")
            reached.add(
                page.evaluate("document.activeElement.id || document.activeElement.tagName")
            )
        assert "file" in reached  # the file picker is reachable by Tab

        page.goto(url)
        page.wait_for_selector("#editor textarea.sec")
        splitter = page.locator("[role=separator]")
        splitter.focus()
        before = splitter.get_attribute("aria-valuenow")
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowRight")
        assert splitter.get_attribute("aria-valuenow") != before
        stamp = page.locator(".transcript .ts").nth(1)
        stamp.focus()
        page.keyboard.press("Enter")
        target = float(stamp.get_attribute("data-t") or 0)
        page.wait_for_function(
            f"Math.abs(document.getElementById('audio').currentTime - {target}) < 0.6"
        )


def _axe(page: Any) -> list[dict[str, Any]]:
    page.evaluate(AXE.read_text(encoding="utf-8"))
    result = page.evaluate(
        "async () => await axe.run(document, {runOnly: {type: 'tag', values: "
        "['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']}})"
    )
    return list(result["violations"])


def test_main_pages_have_no_serious_accessibility_violations(
    server: tuple[str, Path], tmp_path: Path
) -> None:
    base, vault = server
    url = written_note(base, make_tone(tmp_path / "2026-10-11 Axe Review.m4a", 10.0))
    with api(base) as client:
        audio = make_tone(tmp_path / "2026-10-11 Waiting.m4a", 5.0)
        waiting = upload(client, audio, {}).json()  # type: ignore[arg-type]
        wait(client, waiting["id"], "waiting_for_input", timeout=30)  # type: ignore[arg-type]
    template = next((vault / "MeetingMaster3" / "templates").glob("*.md")).name
    pages = [
        "/", "/open", "/meetings", "/templates", f"/templates/{template}/edit",
        f"/templates/{template}/preview", f"/jobs/{waiting['id']}",
        f"/jobs/{waiting['id']}/speakers", f"/jobs/{uuid.uuid4()}",
        *(f"/settings/{tab}" for tab in
          ("vault", "transcription", "notes", "llm", "privacy", "about")),
        url.removeprefix(base),  # the review workspace with the rating widgets
    ]  # fmt: skip
    report: dict[str, list[dict[str, Any]]] = {}
    with browser_page(base, bypass_csp=True) as page:  # CSP would block the injected axe script
        for path in pages:
            page.goto(base + path)
            page.wait_for_load_state("networkidle")
            violations = _axe(page)
            if violations:
                report[path] = [
                    {"id": v["id"], "impact": v["impact"], "nodes": len(v["nodes"]),
                     "target": v["nodes"][0]["target"]}
                    for v in violations
                ]  # fmt: skip
    out = os.environ.get("MM3_AXE_REPORT")
    if out:
        Path(out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    blocking = {path: [v for v in vs if v["impact"] in BLOCKING] for path, vs in report.items()}
    assert not any(blocking.values()), json.dumps(blocking, indent=2)
