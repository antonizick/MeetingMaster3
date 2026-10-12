"""Background model downloads for the Settings screen (the web twin of ``mm3 models download``).

One download runs at a time, in a daemon thread. The page polls :meth:`DownloadManager.snapshot`.
Failures are reported with the error's message and hint (they never contain tokens).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error

log = logging.getLogger(__name__)

Action = Callable[[], object]


@dataclass
class Item:
    name: str
    kind: str
    state: str = "pending"  # pending | running | done | failed
    message: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "kind": self.kind, "state": self.state, "message": self.message}


@dataclass
class DownloadManager:
    items: list[Item] = field(default_factory=list)
    running: bool = False
    error: MM3Error | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self.running,
                "steps": [i.to_dict() for i in self.items],
                "error": self.error.to_dict() if self.error else None,
            }

    def start(self, plan: list[tuple[Item, Action]], *, setup: Callable[[], None]) -> bool:
        """Run ``plan`` (after ``setup``) in the background. Returns False if one is running."""
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.error = None
            self.items = [item for item, _ in plan]
        self._thread = threading.Thread(
            target=self._run, args=(plan, setup), name="mm3-model-download", daemon=True
        )
        self._thread.start()
        return True

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)

    def _set(self, item: Item, state: str, message: str = "") -> None:
        with self._lock:
            item.state, item.message = state, message

    def _run(self, plan: list[tuple[Item, Action]], setup: Callable[[], None]) -> None:
        try:
            setup()
            for item, action in plan:
                self._set(item, "running")
                try:
                    action()
                except MM3Error as exc:
                    self._set(item, "failed", f"{exc.message} {exc.hint}".strip())
                    with self._lock:
                        self.error = exc
                except Exception as exc:
                    log.exception("Model download %s failed", item.name)
                    self._set(item, "failed", f"{type(exc).__name__}: see the log for details.")
                else:
                    self._set(item, "done")
        except MM3Error as exc:
            with self._lock:
                self.error = exc
        finally:
            with self._lock:
                self.running = False


def build_plan(
    settings: Settings,
    models_dir: Path,
    *,
    whisper: str,
    align_language: str,
    diarization: bool,
) -> tuple[list[tuple[Item, Action]], Callable[[], None]]:
    """The downloads to run and the setup step that checks the engine is installed."""
    from meetingmaster3.transcription import models

    def setup() -> None:
        missing = models.missing_engine_modules()
        if missing:
            raise MM3Error(
                "E_ENGINE_MISSING",
                f"The transcription engine is not installed (missing: {', '.join(missing)}).",
                models.INSTALL_HINT,
                status_code=409,
            )
        models.configure_model_cache(models_dir, offline=False)
        if models.offline_mode():
            raise MM3Error(
                "E_OFFLINE",
                "Offline mode is on (HF_HUB_OFFLINE is set).",
                "Turn it off to download models.",
                status_code=409,
            )

    plan: list[tuple[Item, Action]] = [
        (Item(whisper, "whisper"), lambda: models.download_whisper(whisper))
    ]
    if align_language:
        plan.append(
            (
                Item(f"{align_language} (wav2vec2)", "alignment"),
                lambda: models.download_align(align_language),
            )
        )
    if diarization:
        model_id = settings.transcription.diarization_model
        token = models.hf_token(settings)
        plan.append(
            (Item(model_id, "diarization"), lambda: models.download_diarization(token, model_id))
        )
    return plan, setup
