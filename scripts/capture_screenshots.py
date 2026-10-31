"""Capture the documentation screenshots of the core flow into a folder.

Runs a real server with the offline fake pipeline in a throw-away config, data and vault folder
(your own settings and vault are never touched) and drives it with Chromium through Playwright.

    uv run python scripts/capture_screenshots.py docs/assets            # needs /usr/bin/chromium
    MM3_E2E_BROWSER=/path/to/chromium uv run python scripts/capture_screenshots.py out/

Writes 01-setup, 02-new-meeting, 03-progress, 04-name-speakers, 05-done, 12-meetings,
13-import and 14-import-check (``.png``). The review, search, Ask-AI, model-picker and re-link
screenshots come from ``tests/e2e`` with ``MM3_E2E_SCREENSHOTS=<dir>``.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPORT_FIXTURE = ROOT / "tests" / "fixtures" / "imports" / "voice-mode-unlabelled.md"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def make_tone(path: Path, seconds: float) -> Path:
    subprocess.run(  # noqa: S603
        [  # noqa: S607
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            str(path),
        ],
        check=True,
    )
    return path


def main(out: Path) -> int:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mm3-shots-") as tmp_name:
        tmp = Path(tmp_name)
        for key, sub in (("CONFIG", "config"), ("DATA", "data"), ("CACHE", "cache")):
            os.environ[f"MM3_{key}_DIR"] = str(tmp / sub)
        os.environ["MM3_MODELS_DIR"] = str(tmp / "cache" / "models")
        os.environ["MM3_FAKE_PIPELINE"] = "1"
        os.environ["MM3_FAKE_STAGE_SECONDS"] = "4"
        vault = tmp / "MyVault"
        (vault / ".obsidian").mkdir(parents=True)

        import uvicorn

        from meetingmaster3.app import create_app
        from meetingmaster3.config.settings import Settings

        port = free_port()
        settings = Settings()
        settings.server.port = port
        srv = uvicorn.Server(
            uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning")
        )
        threading.Thread(target=srv.run, daemon=True).start()
        deadline = time.monotonic() + 15
        while not srv.started and time.monotonic() < deadline:
            time.sleep(0.05)
        base = f"http://127.0.0.1:{port}"
        audio = make_tone(tmp / "2026-10-11 Product Sync.m4a", 2.0)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=os.environ.get("MM3_E2E_BROWSER") or "/usr/bin/chromium"
            )
            page = browser.new_page(viewport={"width": 1000, "height": 900})

            def shot(name: str, full: bool = True) -> None:
                page.screenshot(path=str(out / f"{name}.png"), full_page=full)
                print("wrote", out / f"{name}.png")

            page.goto(base)
            page.wait_for_url("**/setup")
            page.fill("#vault_path", str(vault))
            page.wait_for_selector("text=is a writable folder")
            shot("01-setup", full=False)
            page.click("text=Save and continue")
            page.wait_for_url(base + "/")

            page.wait_for_load_state("networkidle")
            page.set_input_files("#file", str(audio))
            page.on("pageerror", lambda e: print("pageerror", e))
            try:
                page.wait_for_selector("#hardware-panel dl.facts", timeout=15000)
            except Exception:
                print(page.inner_text("#hardware-panel"))
                raise
            shot("02-new-meeting")
            page.click("text=Accept settings & start")
            page.wait_for_url("**/jobs/*")
            time.sleep(6)
            shot("03-progress", full=False)
            page.click("text=Name speakers", timeout=60000)
            page.wait_for_selector("#speakers-form")
            page.fill("input[name=name__SPEAKER_00]", "Alice")
            page.fill("input[name=name__SPEAKER_01]", "Bob")
            shot("04-name-speakers")
            page.click("text=Confirm & write notes")
            page.wait_for_selector("text=Written to your vault", timeout=90000)
            shot("05-done", full=False)

            page.goto(base + "/meetings")
            shot("12-meetings")

            page.goto(base + "/")
            page.get_by_label("Import a transcript or AI conversation").check()
            page.set_input_files("#file", str(IMPORT_FIXTURE))
            page.fill("#participants", "Alice")
            shot("13-import")
            page.get_by_role("button", name="Accept settings & start").click()
            page.wait_for_url(re.compile(r"/jobs/[0-9a-f-]{36}$"))
            page.get_by_role("link", name="Check the speakers").click(timeout=90000)
            page.wait_for_selector("#import-form")
            page.fill("#name-SPEAKER_00", "Alice")
            page.fill("#name-SPEAKER_01", "Grok")
            shot("14-import-check")
            browser.close()
        srv.should_exit = True
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "docs/assets")))
