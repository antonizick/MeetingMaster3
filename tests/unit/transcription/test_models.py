from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from meetingmaster3.cli import app
from meetingmaster3.config.paths import AppPaths
from meetingmaster3.config.settings import Settings
from meetingmaster3.hardware.doctor import check_ml_extras, check_models
from meetingmaster3.logging import RedactionFilter
from meetingmaster3.transcription import models
from meetingmaster3.transcription.models import (
    DIARIZATION_MODEL,
    align_cached,
    configure_model_cache,
    diarization_access_error,
    diarization_cached,
    free_gpu_memory,
    hf_token,
    is_oom,
    smaller_model,
    whisper_cached,
)


def snapshot(root: Path, repo: str, *files: str) -> None:
    snap = root / "hub" / ("models--" + repo.replace("/", "--")) / "snapshots" / "abc123"
    for f in files:
        (snap / f).parent.mkdir(parents=True, exist_ok=True)
        (snap / f).write_bytes(b"x")


# -- out of memory -----------------------------------------------------------------------------


class OutOfMemoryError(RuntimeError):
    """Same class name as torch.cuda.OutOfMemoryError."""


@pytest.mark.parametrize(
    "exc",
    [
        OutOfMemoryError("whatever"),
        RuntimeError("CUDA failed with error out of memory"),  # CTranslate2
        RuntimeError("CUDA out of memory. Tried to allocate 20.00 MiB"),  # torch
        RuntimeError("cuBLAS failed with status CUBLAS_STATUS_ALLOC_FAILED"),
    ],
)
def test_is_oom_positive(exc: BaseException) -> None:
    assert is_oom(exc)


def test_is_oom_follows_the_cause_chain() -> None:
    try:
        try:
            raise RuntimeError("CUDA out of memory")
        except RuntimeError as inner:
            raise ValueError("wrapped") from inner
    except ValueError as outer:
        assert is_oom(outer)


@pytest.mark.parametrize("exc", [RuntimeError("cuDNN error"), ValueError("bad"), KeyError("x")])
def test_is_oom_negative(exc: BaseException) -> None:
    assert not is_oom(exc)


def test_smaller_model_ladder() -> None:
    assert smaller_model("large-v3") == "large-v2"
    assert smaller_model("large-v3-turbo") == "medium"
    assert smaller_model("turbo") == "medium"
    assert smaller_model("medium.en") == "small"
    assert smaller_model("tiny") is None
    assert smaller_model("someone/custom-model") == "medium"


def test_free_gpu_memory_uses_an_imported_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    cuda = types.SimpleNamespace(
        is_available=lambda: True,
        memory_allocated=lambda: 2**30,
        memory_reserved=lambda: 2**31,
        empty_cache=lambda: calls.append("empty_cache"),
        ipc_collect=lambda: calls.append("ipc_collect"),
    )
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(cuda=cuda))
    free_gpu_memory("test")
    assert calls == ["empty_cache", "ipc_collect"]
    assert models.vram_used_mb() == (1024.0, 2048.0)


def test_free_gpu_memory_without_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    free_gpu_memory()  # no torch imported: just garbage collection
    assert models.vram_used_mb() is None


# -- cache, tokens, offline --------------------------------------------------------------------


def test_configure_model_cache(tmp_path: Path) -> None:
    root = tmp_path / "models"
    configure_model_cache(root)
    assert os.environ["HF_HOME"] == str(root)
    assert os.environ["TORCH_HOME"] == str(root / "torch")
    assert "HF_HUB_OFFLINE" not in os.environ and not models.offline_mode()
    assert root.stat().st_mode & 0o777 == 0o700
    configure_model_cache(root, offline=True)
    assert models.offline_mode()


def test_cache_checks(tmp_path: Path) -> None:
    assert not whisper_cached(tmp_path, "large-v3-turbo")
    snapshot(tmp_path, "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "model.bin", "config.json")
    assert whisper_cached(tmp_path, "large-v3-turbo") and whisper_cached(tmp_path, "turbo")
    snapshot(tmp_path, "me/custom-whisper", "model.bin", "config.json")
    assert whisper_cached(tmp_path, "me/custom-whisper")
    local = tmp_path / "local-model"
    local.mkdir()
    assert not whisper_cached(tmp_path, str(local))
    (local / "model.bin").write_bytes(b"x")
    assert whisper_cached(tmp_path, str(local))

    snapshot(tmp_path, DIARIZATION_MODEL, "config.yaml", "segmentation/pytorch_model.bin")
    assert not diarization_cached(tmp_path)  # incomplete download
    snapshot(tmp_path, DIARIZATION_MODEL, "embedding/pytorch_model.bin", "plda/plda.npz")
    assert diarization_cached(tmp_path)
    snapshot(tmp_path, "other/diarizer", "config.yaml")
    assert diarization_cached(tmp_path, "other/diarizer")

    assert not align_cached(tmp_path, "en") and not align_cached(tmp_path, "de")
    ckpt = tmp_path / "torch" / "hub" / "checkpoints"
    ckpt.mkdir(parents=True)
    (ckpt / "wav2vec2_fairseq_base_ls960_asr_ls960.pth").write_bytes(b"x")
    assert align_cached(tmp_path, "en")


def test_hf_token_sources_and_redaction(monkeypatch: pytest.MonkeyPatch) -> None:
    assert hf_token(Settings()) is None
    monkeypatch.setenv("HF_TOKEN", "hf_from_env_123")
    assert hf_token(Settings()) == "hf_from_env_123"
    s = Settings(secrets={"hf_token": " hf_from_settings_456 "})  # type: ignore[arg-type]
    assert hf_token(s) == "hf_from_settings_456"
    record = __import__("logging").LogRecord("x", 20, "", 0, "token hf_from_settings_456", (), None)
    RedactionFilter().filter(record)
    assert "hf_from_settings_456" not in record.getMessage()


def test_diarization_access_error_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    assert diarization_access_error(RuntimeError(), token_present=False).code == (
        "E_HF_TOKEN_MISSING"
    )
    gated = diarization_access_error(RuntimeError("401 Unauthorized"), token_present=True)
    assert gated.code == "E_HF_ACCESS" and "accept the terms" in gated.hint
    other = diarization_access_error(ConnectionError("dns"), token_present=True)
    assert other.code == "E_MODEL_DOWNLOAD"
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    offline = diarization_access_error(OSError("not in cache"), token_present=True)
    assert offline.code == "E_MODEL_MISSING"


def test_engine_detection() -> None:
    present = {"torch", "whisperx", "pyannote.audio"}

    def spec(name: str) -> object | None:
        return object() if name in present else None

    assert models.engine_available(spec)
    present.discard("whisperx")
    assert models.missing_engine_modules(spec) == ["whisperx"]

    def broken(name: str) -> object | None:
        raise ModuleNotFoundError(name)

    assert models.missing_engine_modules(broken) == list(models.ENGINE_MODULES)


# -- doctor and CLI ----------------------------------------------------------------------------


def paths_in(tmp: Path) -> AppPaths:
    return AppPaths(config_dir=tmp / "c", data_dir=tmp / "d", cache_dir=tmp / "k")


def test_doctor_engine_check() -> None:
    check = check_ml_extras(lambda m: None)
    assert check.status == "warn" and "uv sync --extra ml" in check.hint
    assert check_ml_extras(lambda m: object()).status == "ok"


def test_doctor_model_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "missing_engine_modules", lambda *a: [])
    paths = paths_in(tmp_path)
    checks = {c.name: c for c in check_models(Settings(), paths, "large-v3-turbo")}
    assert {c.status for c in checks.values()} == {"warn"}
    assert "mm3 models download" in checks["Whisper model"].hint
    root = paths.models_dir
    snapshot(root, "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "model.bin", "config.json")
    offline = Settings(transcription={"offline": True})  # type: ignore[arg-type]
    checks = {c.name: c for c in check_models(offline, paths, "large-v3-turbo")}
    assert checks["Whisper model"].status == "ok"
    assert checks["Alignment model"].status == "fail"  # offline and missing: blocking
    no_diar = Settings(transcription={"diarize": False})  # type: ignore[arg-type]
    checks = {c.name: c for c in check_models(no_diar, paths, "large-v3-turbo")}
    assert checks["Diarization model"].status == "ok"
    monkeypatch.setattr(models, "missing_engine_modules", lambda *a: ["torch"])
    assert check_models(Settings(), paths, "large-v3-turbo") == []


def test_cli_models_status() -> None:
    result = CliRunner().invoke(app, ["models", "status"])
    assert result.exit_code == 0
    assert "[missing] whisper" in result.output and DIARIZATION_MODEL in result.output


def test_cli_models_download_needs_the_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(models, "missing_engine_modules", lambda *a: ["whisperx"])
    result = CliRunner().invoke(app, ["models", "download"])
    assert result.exit_code == 1 and "uv sync --extra ml" in result.output


def test_cli_models_download(monkeypatch: pytest.MonkeyPatch) -> None:
    got: list[str] = []
    monkeypatch.setattr(models, "missing_engine_modules", lambda *a: [])
    monkeypatch.setattr(models, "download_whisper", lambda m: got.append(m) or Path("/w"))
    monkeypatch.setattr(models, "download_align", lambda lang: got.append("align-" + lang))

    def refuse(token: str | None, model: str) -> Path:
        raise diarization_access_error(RuntimeError("x"), token_present=False)

    monkeypatch.setattr(models, "download_diarization", refuse)
    result = CliRunner().invoke(app, ["models", "download", "--whisper", "small"])
    assert got == ["small", "align-en"]
    assert result.exit_code == 1 and "accept the model terms" in result.output.lower()

    monkeypatch.setattr(models, "download_diarization", lambda t, m: Path("/d"))
    result = CliRunner().invoke(
        app, ["models", "download", "--whisper", "small", "--align", "", "--no-diarization"]
    )
    assert result.exit_code == 0 and "Done." in result.output
