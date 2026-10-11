"""Environment checks behind ``mm3 doctor``. Phases 06, 08 and 14 add their own checks."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from meetingmaster3.config.paths import AppPaths
from meetingmaster3.config.settings import Settings

CheckStatus = Literal["ok", "warn", "fail"]
DEFAULT_OLLAMA_URL = "http://localhost:11434"
OLLAMA_TIMEOUT_S = 2.0


@dataclass(frozen=True)
class Check:
    name: str
    status: CheckStatus
    detail: str
    hint: str = ""

    @property
    def blocking(self) -> bool:
        return self.status == "fail"


def ollama_url(settings: Settings) -> str:
    cfg = settings.llm.backends.get("ollama", {})
    return str(cfg.get("base_url") or cfg.get("url") or DEFAULT_OLLAMA_URL).rstrip("/")


def check_python(version: tuple[int, int] | None = None) -> Check:
    major, minor = version or (sys.version_info.major, sys.version_info.minor)
    if (major, minor) == (3, 12):
        return Check("Python", "ok", f"{major}.{minor}")
    return Check(
        "Python",
        "fail",
        f"{major}.{minor} (3.12 required)",
        "Run via uv (`uv run mm3 doctor`), which provisions Python 3.12.",
    )


def check_binary(name: str, which: Callable[[str], str | None] = shutil.which) -> Check:
    path = which(name)
    if path:
        return Check(name, "ok", path)
    return Check(
        name,
        "fail",
        "not found on PATH",
        "Install ffmpeg (provides ffmpeg and ffprobe), e.g. `sudo pacman -S ffmpeg`.",
    )


def check_ml_extras(find_spec: Callable[[str], object | None] = importlib.util.find_spec) -> Check:
    missing = [m for m in ("torch", "whisperx", "pyannote.audio") if _spec(find_spec, m) is None]
    if not missing:
        return Check("ML extras", "ok", "torch, whisperx and pyannote.audio are installed")
    return Check(
        "ML extras",
        "warn",
        f"not installed: {', '.join(missing)}",
        "Transcription needs them: `uv sync --extra ml` (available from Phase 06).",
    )


def _spec(find_spec: Callable[[str], object | None], module: str) -> object | None:
    try:
        return find_spec(module)
    except (ImportError, ValueError):
        return None


def check_hf_token(settings: Settings) -> Check:
    token = settings.secrets.hf_token
    if token and token.get_secret_value():
        return Check("Hugging Face token", "ok", "configured")
    return Check(
        "Hugging Face token",
        "warn",
        "not set",
        "Needed once to download the gated pyannote diarization models "
        "(set MM3_SECRETS__HF_TOKEN). Transcription without speakers works without it.",
    )


def check_ollama(
    settings: Settings, client_factory: Callable[[], httpx.Client] | None = None
) -> Check:
    url = ollama_url(settings)
    try:
        client = client_factory() if client_factory else httpx.Client(timeout=OLLAMA_TIMEOUT_S)
        with client:
            resp = client.get(f"{url}/api/tags")
        resp.raise_for_status()
        count = len(resp.json().get("models", []))
    except (httpx.HTTPError, ValueError) as exc:
        return Check(
            "Ollama",
            "warn",
            f"not reachable at {url} ({type(exc).__name__})",
            "Start Ollama (`ollama serve`) or pick a cloud backend in Settings.",
        )
    return Check("Ollama", "ok", f"reachable at {url}, {count} model(s) installed")


def _writable_dir(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.W_OK | os.X_OK)


def check_vault(settings: Settings) -> Check:
    path = settings.vault.path
    if path is None:
        return Check(
            "Vault", "warn", "not configured", "Set vault.path (or MM3_VAULT__PATH) to your vault."
        )
    if not path.is_dir():
        return Check("Vault", "fail", f"{path} is not a directory", "Check vault.path.")
    if not _writable_dir(path):
        return Check("Vault", "fail", f"{path} is not writable", "Fix the folder permissions.")
    return Check("Vault", "ok", f"{path} is writable")


def check_data_dirs(paths: AppPaths) -> list[Check]:
    checks: list[Check] = []
    for label, directory in (("Config dir", paths.config_dir), ("Data dir", paths.data_dir)):
        if not directory.exists():
            checks.append(Check(label, "ok", f"{directory} (will be created on first run)"))
        elif not _writable_dir(directory):
            checks.append(
                Check(label, "fail", f"{directory} is not writable", "Fix the permissions.")
            )
        elif directory.stat().st_mode & 0o077:
            checks.append(
                Check(
                    label,
                    "warn",
                    f"{directory} is accessible to other users",
                    f"Run `chmod 700 {directory}`.",
                )
            )
        else:
            checks.append(Check(label, "ok", f"{directory} (private, writable)"))
    return checks


def run_checks(settings: Settings, paths: AppPaths) -> list[Check]:
    """All environment checks, in display order."""
    return [
        check_python(),
        check_binary("ffmpeg"),
        check_binary("ffprobe"),
        check_ml_extras(),
        check_hf_token(settings),
        check_ollama(settings),
        check_vault(settings),
        *check_data_dirs(paths),
    ]
