"""Model cache, model ids, downloads, VRAM release and out-of-memory detection.

Every model lives under one folder, ``MM3_MODELS_DIR`` (default
``$XDG_CACHE_HOME/meetingmaster3/models``): ``HF_HOME`` (faster-whisper, pyannote and the
Hugging Face alignment models) and ``TORCH_HOME`` (torchaudio alignment models) both point there.
:func:`configure_model_cache` must run before torch, whisperx or huggingface_hub are imported,
because those libraries read the variables at import time.

Nothing here imports an ML library at module level, so ``mm3 doctor`` and the unit tests work
without the ``ml`` extra.
"""

from __future__ import annotations

import gc
import importlib
import importlib.util
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from meetingmaster3.errors import MM3Error

if TYPE_CHECKING:
    from meetingmaster3.config.settings import Settings

log = logging.getLogger(__name__)

#: Diarization pipeline used by the pinned WhisperX (3.8.6) and pyannote.audio 4 (spec R14).
DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
DIARIZATION_TERMS_URL = f"https://huggingface.co/{DIARIZATION_MODEL}"
HF_TOKEN_URL = "https://huggingface.co/settings/tokens"  # noqa: S105 - a URL, not a secret

#: faster-whisper model names and their CTranslate2 repositories (``faster_whisper.utils``).
WHISPER_REPOS: dict[str, str] = {
    "tiny": "Systran/faster-whisper-tiny",
    "tiny.en": "Systran/faster-whisper-tiny.en",
    "base": "Systran/faster-whisper-base",
    "base.en": "Systran/faster-whisper-base.en",
    "small": "Systran/faster-whisper-small",
    "small.en": "Systran/faster-whisper-small.en",
    "medium": "Systran/faster-whisper-medium",
    "medium.en": "Systran/faster-whisper-medium.en",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
}

#: The "retry with a smaller model" ladder (largest first), used after a second OOM.
MODEL_LADDER = ["large-v3", "large-v2", "large-v3-turbo", "medium", "small", "base", "tiny"]

ENGINE_MODULES = ("torch", "whisperx", "pyannote.audio")
INSTALL_HINT = (
    "Install it with `uv sync --extra ml` (about 6 GB of Python packages), then restart "
    "MeetingMaster3 (see docs/user-guide/transcription.md). To try the app without it, start "
    "the server with MM3_FAKE_PIPELINE=1 for simulated results."
)

FindSpec = Callable[[str], object | None]


def _has_module(name: str, find_spec: FindSpec) -> bool:
    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def missing_engine_modules(find_spec: FindSpec = importlib.util.find_spec) -> list[str]:
    """The ML modules the transcription engine needs that are not installed."""
    return [m for m in ENGINE_MODULES if not _has_module(m, find_spec)]


def engine_available(find_spec: FindSpec = importlib.util.find_spec) -> bool:
    return not missing_engine_modules(find_spec)


def smaller_model(model: str) -> str | None:
    """The next smaller model to suggest after an out-of-memory failure, or ``None``."""
    base = model.removesuffix(".en")
    aliases = {"turbo": "large-v3-turbo", "large": "large-v3", "distil-large-v3": "large-v3-turbo"}
    base = aliases.get(base, base)
    if base not in MODEL_LADDER:
        return "medium"
    i = MODEL_LADDER.index(base)
    return MODEL_LADDER[i + 1] if i + 1 < len(MODEL_LADDER) else None


# -- cache location and tokens ------------------------------------------------------------------


def configure_model_cache(models_dir: Path, *, offline: bool = False) -> None:
    """Point every model cache at ``models_dir`` and honour offline mode.

    ``HF_HUB_OFFLINE=1`` set by the user is always respected; ``offline=True`` (the
    ``transcription.offline`` setting) sets it."""
    disable_telemetry()
    models_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(models_dir)
    os.environ["TORCH_HOME"] = str(models_dir / "torch")
    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"


TELEMETRY_OFF = {
    # pyannote.audio 4 sends OpenTelemetry traces to otel.pyannote.ai by default (model and
    # pipeline names, audio duration, speaker hints). It reads this variable at every report.
    "PYANNOTE_METRICS_ENABLED": "false",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
}


def disable_telemetry() -> None:
    """Turn off every library's usage reporting (spec S6: no telemetry, ever). Forced, not a
    default: a user-level setting cannot turn it back on inside MeetingMaster3."""
    os.environ.update(TELEMETRY_OFF)


def offline_mode() -> bool:
    return os.environ.get("HF_HUB_OFFLINE", "").strip().lower() in {"1", "true", "yes", "on"}


def hf_token(settings: Settings) -> str | None:
    """The Hugging Face token: ``secrets.hf_token`` (config or ``MM3_SECRETS__HF_TOKEN``), else
    ``HF_TOKEN``. Passed explicitly to the libraries and never logged."""
    secret = settings.secrets.hf_token
    value = secret.get_secret_value().strip() if secret else ""
    value = value or os.environ.get("HF_TOKEN", "").strip()
    if value:
        from meetingmaster3.logging import register_secret

        register_secret(value)
    return value or None


def _repo_dir(models_dir: Path, repo_id: str) -> Path:
    return models_dir / "hub" / ("models--" + repo_id.replace("/", "--"))


def _complete_snapshot(models_dir: Path, repo_id: str, required: tuple[str, ...]) -> Path | None:
    snapshots = _repo_dir(models_dir, repo_id) / "snapshots"
    if not snapshots.is_dir():
        return None
    for snap in sorted(snapshots.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if all((snap / f).exists() for f in required):
            return snap
    return None


def _snapshot_has(models_dir: Path, repo_id: str, required: tuple[str, ...]) -> bool:
    return _complete_snapshot(models_dir, repo_id, required) is not None


def whisper_cached(models_dir: Path, model: str) -> bool:
    repo = WHISPER_REPOS.get(model)
    if repo is None:  # a local path or a custom repo id
        path = Path(model).expanduser()
        if path.is_dir():
            return (path / "model.bin").exists()
        repo = model
    return _snapshot_has(models_dir, repo, ("model.bin", "config.json"))


def _diarization_files(model: str) -> tuple[str, ...]:
    if model == DIARIZATION_MODEL:
        return (
            "config.yaml",
            "segmentation/pytorch_model.bin",
            "embedding/pytorch_model.bin",
            "plda/plda.npz",
        )
    return ("config.yaml",)


def diarization_cached(models_dir: Path, model: str = DIARIZATION_MODEL) -> bool:
    return _snapshot_has(models_dir, model, _diarization_files(model))


def diarization_snapshot(models_dir: Path, model: str = DIARIZATION_MODEL) -> Path | None:
    """The cached pipeline folder. pyannote loads it without contacting Hugging Face (from the
    repo id it checks every file's metadata online, on every job)."""
    return _complete_snapshot(models_dir, model, _diarization_files(model))


def align_cached(models_dir: Path, language: str = "en") -> bool:
    """English uses torchaudio's ``WAV2VEC2_ASR_BASE_960H`` checkpoint; others are not checked."""
    if language != "en":
        return False
    checkpoints = models_dir / "torch" / "hub" / "checkpoints"
    return checkpoints.is_dir() and any(checkpoints.glob("wav2vec2_fairseq_base_ls960_asr_ls960*"))


@dataclass(frozen=True)
class ModelStatus:
    name: str
    kind: str
    cached: bool
    note: str = ""


def model_status(
    models_dir: Path, whisper_models: list[str], diarization: str
) -> list[ModelStatus]:
    out = [ModelStatus(m, "whisper", whisper_cached(models_dir, m)) for m in whisper_models]
    out.append(ModelStatus("en (wav2vec2)", "alignment", align_cached(models_dir, "en")))
    out.append(
        ModelStatus(
            diarization, "diarization", diarization_cached(models_dir, diarization), "gated"
        )
    )
    return out


# -- downloads (`mm3 models download`) ----------------------------------------------------------


def download_whisper(model: str) -> Path:
    """Fetch a faster-whisper model into the cache (``configure_model_cache`` first)."""
    utils: Any = importlib.import_module("faster_whisper.utils")
    return Path(utils.download_model(model))


def download_align(language: str = "en") -> None:
    """Fetch the wav2vec2 alignment model for ``language`` by loading it once on the CPU."""
    whisperx: Any = importlib.import_module("whisperx")
    model, _meta = whisperx.load_align_model(language_code=language, device="cpu")
    del model


def download_diarization(token: str | None, model: str = DIARIZATION_MODEL) -> Path:
    """Fetch the gated diarization pipeline; raise ``MM3Error`` with guidance when refused."""
    hub: Any = importlib.import_module("huggingface_hub")
    try:
        return Path(hub.snapshot_download(model, token=token))
    except Exception as exc:
        raise diarization_access_error(exc, token_present=bool(token)) from exc


def diarization_access_error(exc: BaseException, *, token_present: bool) -> MM3Error:
    """Turn a Hugging Face or pyannote failure into actionable guidance (never echoes tokens)."""
    text = f"{type(exc).__name__}: {exc}"
    gated = any(
        s in text for s in ("GatedRepo", "gated", "401", "403", "Unauthorized", "access", "token")
    )
    if not token_present:
        return MM3Error(
            "E_HF_TOKEN_MISSING",
            "Speaker diarization needs a one-time Hugging Face download, and no token is set.",
            f"Accept the model terms at {DIARIZATION_TERMS_URL}, create a read token at "
            f"{HF_TOKEN_URL}, and paste it into Settings (or set MM3_SECRETS__HF_TOKEN).",
            status_code=400,
        )
    if gated:
        return MM3Error(
            "E_HF_ACCESS",
            "Hugging Face refused access to the diarization model.",
            f"Sign in to Hugging Face, accept the terms at {DIARIZATION_TERMS_URL} with the "
            "account that owns the token, and check that the token has read access.",
            status_code=400,
        )
    if offline_mode():
        return MM3Error(
            "E_MODEL_MISSING",
            "The diarization model is not downloaded and offline mode is on.",
            "Turn offline mode off once and run `mm3 models download --diarization`.",
            status_code=400,
        )
    return MM3Error(
        "E_MODEL_DOWNLOAD",
        f"Could not load the diarization model ({type(exc).__name__}).",
        "Check the network connection and try again; see the server log for details.",
        status_code=502,
    )


# -- GPU memory -----------------------------------------------------------------------------------


OOM_MARKERS = (
    "CUDA out of memory",
    "out of memory",
    "CUDA_ERROR_OUT_OF_MEMORY",
    "CUBLAS_STATUS_ALLOC_FAILED",
    "cudaErrorMemoryAllocation",
    "CUDNN_STATUS_ALLOC_FAILED",
    "failed to allocate",
)


def is_oom(exc: BaseException) -> bool:
    """True for torch's ``OutOfMemoryError`` and CTranslate2's ``RuntimeError`` messages."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__ == "OutOfMemoryError":
            return True
        text = str(current)
        if any(m.lower() in text.lower() for m in OOM_MARKERS):
            return True
        current = current.__cause__ or current.__context__
    return False


def _torch() -> Any | None:
    """torch, only if something already imported it (freeing memory never loads torch)."""
    return sys.modules.get("torch")


def vram_used_mb() -> tuple[float, float] | None:
    """``(allocated, reserved)`` MiB held by this process through torch, if CUDA is in use."""
    torch = _torch()
    if torch is None or not torch.cuda.is_available():
        return None
    return (
        torch.cuda.memory_allocated() / 2**20,
        torch.cuda.memory_reserved() / 2**20,
    )


def free_gpu_memory(reason: str = "") -> None:
    """Collect garbage and return cached CUDA memory to the driver (spec R5). Callers drop their
    references first (``del model``). VRAM before and after is logged at DEBUG."""
    before = vram_used_mb()
    gc.collect()
    torch = _torch()
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()
        if hasattr(torch.cuda, "ipc_collect"):
            torch.cuda.ipc_collect()
    after = vram_used_mb()
    if before is not None and after is not None:
        log.debug(
            "Freed GPU memory%s: allocated %.0f -> %.0f MiB, reserved %.0f -> %.0f MiB",
            f" ({reason})" if reason else "",
            before[0],
            after[0],
            before[1],
            after[1],
        )
