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

from meetingmaster3.config.paths import AppPaths
from meetingmaster3.config.settings import Settings

CheckStatus = Literal["ok", "warn", "fail"]


@dataclass(frozen=True)
class Check:
    name: str
    status: CheckStatus
    detail: str
    hint: str = ""

    @property
    def blocking(self) -> bool:
        return self.status == "fail"


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
    from meetingmaster3.transcription.models import INSTALL_HINT, missing_engine_modules

    missing = missing_engine_modules(lambda m: _spec(find_spec, m))
    if not missing:
        return Check("Transcription engine", "ok", "torch, whisperx and pyannote.audio installed")
    return Check(
        "Transcription engine",
        "warn",
        f"not installed (missing: {', '.join(missing)})",
        f"Transcription needs it. {INSTALL_HINT}",
    )


def check_models(settings: Settings, paths: AppPaths, whisper_model: str) -> list[Check]:
    """Are the transcription, alignment and diarization models in the local cache?"""
    from meetingmaster3.transcription import models

    if models.missing_engine_modules():
        return []
    root = paths.models_dir
    offline = settings.transcription.offline or models.offline_mode()
    missing_status: CheckStatus = "fail" if offline else "warn"
    later = "Offline mode is on, so it cannot be downloaded." if offline else (
        "It downloads on first use, or now with `mm3 models download`."
    )  # fmt: skip
    checks = []
    if models.whisper_cached(root, whisper_model):
        checks.append(Check("Whisper model", "ok", f"{whisper_model} (cached in {root})"))
    else:
        checks.append(
            Check("Whisper model", missing_status, f"{whisper_model} not downloaded", later)
        )
    if models.align_cached(root, "en"):
        checks.append(Check("Alignment model", "ok", "English wav2vec2 (cached)"))
    else:
        checks.append(Check("Alignment model", missing_status, "English not downloaded", later))
    diar = settings.transcription.diarization_model
    if not settings.transcription.diarize:
        checks.append(Check("Diarization model", "ok", "diarization is turned off"))
    elif models.diarization_cached(root, diar):
        checks.append(Check("Diarization model", "ok", f"{diar} (cached)"))
    else:
        checks.append(
            Check(
                "Diarization model",
                "warn",
                f"{diar} not downloaded",
                f"Accept the terms at https://huggingface.co/{diar}, set the Hugging Face token, "
                "then run `mm3 models download`. Until then transcripts have no speakers.",
            )
        )
    return checks


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
        "Needed once to download the gated diarization model (accept the terms at "
        "https://huggingface.co/pyannote/speaker-diarization-community-1, then set "
        "secrets.hf_token or MM3_SECRETS__HF_TOKEN). Transcription without speakers works "
        "without it.",
    )


def check_llm_backends(settings: Settings) -> list[Check]:
    """Reachability and default-model presence for every configured LLM backend (Phase 08)."""
    from meetingmaster3.llm.doctor import check_backends

    return [Check(c.name, c.status, c.detail, c.hint) for c in check_backends(settings)]


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


def run_checks(settings: Settings, paths: AppPaths, whisper_model: str = "") -> list[Check]:
    """All environment checks, in display order."""
    return [
        check_python(),
        check_binary("ffmpeg"),
        check_binary("ffprobe"),
        check_ml_extras(),
        *check_models(settings, paths, whisper_model or "large-v3-turbo"),
        check_hf_token(settings),
        *check_llm_backends(settings),
        check_vault(settings),
        *check_data_dirs(paths),
    ]
