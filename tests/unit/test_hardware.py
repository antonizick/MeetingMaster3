from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr
from typer.testing import CliRunner

from meetingmaster3.app import create_app
from meetingmaster3.cli import app as cli_app
from meetingmaster3.config.paths import AppPaths
from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.hardware import detect, doctor
from meetingmaster3.hardware.detect import GPUInfo, HardwareInfo, detect_hardware, parse_nvidia_smi
from meetingmaster3.hardware.profiles import profile_for_vram, select_profile
from meetingmaster3.hardware.recommend import (
    check_risks,
    estimate_seconds,
    format_eta,
    load_data,
    recommend,
)

SMI_2070 = "NVIDIA GeForce RTX 2070 with Max-Q Design, 8192, 483, 610.57.04\n"
SMI_4090 = "NVIDIA GeForce RTX 4090, 24564, 1200, 560.35.03\n"
SMI_MULTI = SMI_2070 + SMI_4090


def info_for(smi: str | None) -> HardwareInfo:
    return detect_hardware(smi_output=smi if smi is not None else "")


def gpu_info(total_mb: int, used_mb: int = 300) -> HardwareInfo:
    return HardwareInfo(
        gpus=[GPUInfo("Test GPU", total_mb, used_mb, "1.0")],
        cuda_available=True,
        ram_total_mb=32000,
    )


CPU_ONLY = HardwareInfo()


# -- detection ---------------------------------------------------------------------------


def test_parse_single_gpu() -> None:
    [gpu] = parse_nvidia_smi(SMI_2070)
    assert gpu.name.startswith("NVIDIA GeForce RTX 2070")
    assert (gpu.vram_total_mb, gpu.vram_used_mb, gpu.vram_free_mb) == (8192, 483, 7709)
    assert gpu.driver_version == "610.57.04"


def test_parse_multi_gpu_picks_largest_as_primary() -> None:
    info = info_for(SMI_MULTI)
    assert len(info.gpus) == 2
    assert info.primary_gpu is not None and "4090" in info.primary_gpu.name
    assert info.total_vram_mb == 24564 and info.cuda_available


@pytest.mark.parametrize("garbage", ["not a csv", "a, b", "NVIDIA X, lots, 1, 2"])
def test_parse_garbage_raises(garbage: str) -> None:
    with pytest.raises(ValueError):
        parse_nvidia_smi(garbage)


def test_garbage_output_falls_back_to_cpu_with_note() -> None:
    info = detect_hardware(smi_output="Failed to initialize NVML")
    assert not info.cuda_available and info.gpus == []
    assert any("parse" in n for n in info.notes)


def test_empty_output_is_cpu_only() -> None:
    info = info_for(None)
    assert not info.cuda_available
    assert info.cpu_cores >= 1


def test_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detect.shutil, "which", lambda _name: None)
    monkeypatch.setattr(detect, "_detect_torch", lambda: [])
    info = detect_hardware()
    assert info.gpus == [] and info.detection_source == "cpu"


def test_torch_fallback_used_when_smi_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(detect.shutil, "which", lambda _name: None)
    monkeypatch.setattr(detect, "_detect_torch", lambda: [GPUInfo("T", 8192, 0)])
    info = detect_hardware()
    assert info.detection_source == "torch" and info.cuda_available


def test_unsupported_gpu_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        detect.shutil, "which", lambda n: "/usr/bin/rocm-smi" if "rocm" in n else None
    )
    monkeypatch.setattr(detect, "_detect_torch", lambda: [])
    info = detect_hardware()
    assert info.unsupported_gpus and not info.cuda_available


def test_cache_and_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(detect, "detect_hardware", lambda: calls.append(1) or CPU_ONLY)
    detect.clear_cache()
    detect.get_hardware()
    detect.get_hardware()
    assert len(calls) == 1
    detect.get_hardware(refresh=True)
    assert len(calls) == 2
    detect.clear_cache()


@pytest.mark.gpu
def test_real_detection_on_reference_machine() -> None:
    info = detect_hardware()
    assert info.cuda_available and info.total_vram_mb >= 6000


# -- profiles ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mb", "expected"),
    [
        (0, "cpu"),
        (4096, "cpu"),
        (6144, "cpu"),
        (6999, "cpu"),
        (7000, "vram8"),
        (8192, "vram8"),
        (11264, "vram8"),
        (13999, "vram8"),
        (14000, "vram16"),
        (16384, "vram16"),
        (21999, "vram16"),
        (22000, "vram24plus"),
        (24564, "vram24plus"),
        (49152, "vram24plus"),
    ],
)
def test_profile_boundaries(mb: int, expected: str) -> None:
    assert profile_for_vram(mb) == expected


def test_user_override_wins() -> None:
    assert select_profile(gpu_info(8192), "vram24plus") == ("vram24plus", True)
    assert select_profile(gpu_info(8192), "auto") == ("vram8", False)


def test_invalid_override_rejected() -> None:
    with pytest.raises(MM3Error):
        select_profile(CPU_ONLY, "vram99")


# -- recommendations ---------------------------------------------------------------------


def test_data_file_is_complete() -> None:
    data = load_data()
    for name in ("cpu", "vram8", "vram16", "vram24plus"):
        entry = data["profiles"][name]
        assert entry["transcription"]["status"] in ("estimated", "measured")
        assert entry["llm"]["models"]


def test_vram8_recommendation_matches_spec() -> None:
    rec = recommend(info_for(SMI_2070))
    assert rec.profile == "vram8" and not rec.overridden
    assert rec.transcription.model == "large-v3-turbo"
    # measured in Phase 06 on the reference RTX 2070 Max-Q (the spec estimated 15-30x)
    assert (rec.transcription.rtf_low, rec.transcription.rtf_high) == (14, 16)
    assert rec.transcription.status == "measured"
    assert rec.transcription.diarize is True
    assert any(m.size_b <= 9 for m in rec.llm.models)
    assert "never share the GPU" in rec.llm.vram_handoff
    assert [w.code for w in rec.warnings] == ["vram_handoff"]


def test_each_profile_has_recommendation() -> None:
    assert recommend(CPU_ONLY).profile == "cpu"
    assert recommend(gpu_info(16384)).transcription.model == "large-v3"
    assert recommend(gpu_info(24564)).profile == "vram24plus"


def test_eta_estimate() -> None:
    assert estimate_seconds(3600, 15, 30) == (120.0, 240.0)
    assert estimate_seconds(0, 15, 30) == (0.0, 0.0)
    t = recommend(info_for(SMI_2070)).transcription
    assert t.estimate(1680) == (105.0, 120.0)  # measured 14-16x


def test_format_eta() -> None:
    assert format_eta(10, 40) == "under a minute"
    assert format_eta(120, 240) == "2-4 minutes"
    assert format_eta(60, 60) == "about 1 minute"


def test_large_v3_float16_on_8gb_is_critical() -> None:
    codes = {
        w.code: w
        for w in check_risks(gpu_info(8192), "vram8", model="large-v3", compute_type="float16")
    }
    assert codes["whisper_oom_risk"].severity == "critical"


def test_14b_llm_on_8gb_is_critical_and_8b_is_not() -> None:
    big = check_risks(gpu_info(8192), "vram8", llm_size_b=14)
    assert any(w.code == "llm_too_large" and w.severity == "critical" for w in big)
    small = check_risks(gpu_info(8192), "vram8", llm_size_b=7)
    assert not any(w.code in ("llm_too_large",) for w in small)


def test_busy_gpu_warns() -> None:
    warnings = check_risks(gpu_info(8192, used_mb=6500), "vram8")
    assert any(w.code == "vram_in_use" for w in warnings)


def test_oversized_override_warns() -> None:
    rec = recommend(gpu_info(8192), "vram24plus")
    assert any(w.code == "profile_exceeds_hardware" for w in rec.warnings)


def test_cpu_warnings() -> None:
    codes = {w.code for w in check_risks(CPU_ONLY, "cpu", model="medium")}
    assert {"no_gpu", "cpu_large_model"} <= codes


def test_recommendation_to_dict_is_json_ready() -> None:
    import json

    json.dumps(recommend(info_for(SMI_2070)).to_dict())


# -- doctor ------------------------------------------------------------------------------


def test_check_python() -> None:
    assert doctor.check_python((3, 12)).status == "ok"
    assert doctor.check_python((3, 14)).blocking


def test_check_binary() -> None:
    assert doctor.check_binary("ffmpeg", which=lambda _n: "/usr/bin/ffmpeg").status == "ok"
    assert doctor.check_binary("ffmpeg", which=lambda _n: None).blocking


def test_check_ml_extras() -> None:
    assert doctor.check_ml_extras(find_spec=lambda _m: object()).status == "ok"
    missing = doctor.check_ml_extras(find_spec=lambda _m: None)
    assert missing.status == "warn" and not missing.blocking


def test_check_hf_token() -> None:
    s = Settings()
    assert doctor.check_hf_token(s).status == "warn"
    s.secrets.hf_token = SecretStr("hf_x")
    assert doctor.check_hf_token(s).status == "ok"


def test_check_llm_backends_unreachable_is_nonblocking() -> None:
    with respx.mock:
        respx.get("http://127.0.0.1:11434/api/tags").mock(side_effect=httpx.ConnectError("no"))
        checks = doctor.check_llm_backends(Settings())
    assert [c.status for c in checks] == ["warn"] and not checks[0].blocking
    assert checks[0].name == "LLM ollama (local)"


def test_check_llm_backends_reachable() -> None:
    with respx.mock:
        respx.get("http://127.0.0.1:11434/api/tags").respond(json={"models": [{"name": "a"}]})
        checks = doctor.check_llm_backends(Settings())
    assert checks[0].status == "ok" and "1 model" in checks[0].detail


def test_check_vault(tmp_path: Path) -> None:
    s = Settings()
    assert doctor.check_vault(s).status == "warn"
    s.vault.path = tmp_path / "missing"
    assert doctor.check_vault(s).blocking
    s.vault.path = tmp_path
    assert doctor.check_vault(s).status == "ok"


def test_check_data_dirs(tmp_path: Path) -> None:
    paths = AppPaths(tmp_path / "c", tmp_path / "d", tmp_path / "k")
    assert all(c.status == "ok" for c in doctor.check_data_dirs(paths))
    paths.data_dir.mkdir(mode=0o755)
    paths.data_dir.chmod(0o755)
    statuses = {c.name: c.status for c in doctor.check_data_dirs(paths)}
    assert statuses["Data dir"] == "warn"


# -- CLI and API -------------------------------------------------------------------------


def test_cli_doctor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "meetingmaster3.hardware.detect.detect_hardware", lambda: info_for(SMI_2070)
    )
    monkeypatch.setattr(
        doctor,
        "run_checks",
        lambda *_a: [doctor.Check("ffmpeg", "ok", "/usr/bin/ffmpeg")],
    )
    detect.clear_cache()
    r = CliRunner().invoke(cli_app, ["doctor"])
    assert r.exit_code == 0, r.output
    assert "RTX 2070" in r.output and "vram8" in r.output and "large-v3-turbo" in r.output
    detect.clear_cache()


def test_cli_doctor_exits_nonzero_on_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        doctor, "run_checks", lambda *_a: [doctor.Check("ffmpeg", "fail", "missing", "install it")]
    )
    detect.clear_cache()
    r = CliRunner().invoke(cli_app, ["doctor"])
    assert r.exit_code == 1
    detect.clear_cache()


def test_api_hardware(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setattr(detect, "detect_hardware", lambda: info_for(SMI_2070))
    detect.clear_cache()
    body = client.get("/api/hardware").json()
    assert body["hardware"]["total_vram_mb"] == 8192
    assert body["recommendation"]["profile"] == "vram8"
    detect.clear_cache()


def test_api_refresh_requires_csrf_then_works(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    monkeypatch.setattr(detect, "detect_hardware", lambda: info_for(SMI_4090))
    detect.clear_cache()
    assert client.post("/api/hardware/refresh").status_code == 403
    client.get("/")  # sets the CSRF cookie
    token = client.cookies["mm3_csrf"]
    r = client.post("/api/hardware/refresh", headers={"X-CSRF-Token": token})
    assert r.status_code == 200
    assert r.json()["recommendation"]["profile"] == "vram24plus"
    detect.clear_cache()


def test_api_profile_override() -> None:
    s = Settings()
    s.hardware.profile = "cpu"
    c = TestClient(create_app(s), base_url="http://localhost")
    assert c.get("/api/hardware").json()["recommendation"]["overridden"] is True
