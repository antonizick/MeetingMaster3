"""Turn a hardware profile into concrete, explained recommendations and risk warnings.

All numbers live in ``recommendations.yaml`` so measured values (Phases 06 and 15) can replace the
estimates without code changes.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from meetingmaster3.hardware.detect import HardwareInfo
from meetingmaster3.hardware.profiles import (
    PROFILE_LABELS,
    ProfileName,
    profile_for_vram,
    select_profile,
)

DATA_FILE = Path(__file__).with_name("recommendations.yaml")
Severity = Literal["info", "warning", "critical"]
Status = Literal["estimated", "measured"]


@dataclass(frozen=True)
class HardwareWarning:
    severity: Severity
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"severity": self.severity, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class TranscriptionRecommendation:
    model: str
    alternatives: list[str]
    compute_type: str
    batch_size: int
    diarize: bool | Literal["optional"]
    rtf_low: float
    rtf_high: float
    status: Status
    notes: str

    def estimate(self, duration_s: float) -> tuple[float, float]:
        """Expected processing time in seconds as ``(low, high)`` for ``duration_s`` of audio."""
        return estimate_seconds(duration_s, self.rtf_low, self.rtf_high)


@dataclass(frozen=True)
class LLMModelSuggestion:
    family: str
    size_b: float
    quant: str
    context: str
    quality: str
    speed: str


@dataclass(frozen=True)
class LLMRecommendation:
    summary: str
    models: list[LLMModelSuggestion]
    context_note: str
    vram_handoff: str
    status: Status


@dataclass(frozen=True)
class Recommendation:
    profile: ProfileName
    profile_label: str
    overridden: bool
    transcription: TranscriptionRecommendation
    llm: LLMRecommendation
    warnings: list[HardwareWarning] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        t = self.transcription
        return {
            "profile": self.profile,
            "profile_label": self.profile_label,
            "overridden": self.overridden,
            "transcription": {
                "model": t.model,
                "alternatives": t.alternatives,
                "compute_type": t.compute_type,
                "batch_size": t.batch_size,
                "diarize": t.diarize,
                "rtf": [t.rtf_low, t.rtf_high],
                "status": t.status,
                "notes": t.notes,
                "example_60_min_seconds": list(t.estimate(3600)),
            },
            "llm": {
                "summary": self.llm.summary,
                "models": [vars(m) for m in self.llm.models],
                "context_note": self.llm.context_note,
                "vram_handoff": self.llm.vram_handoff,
                "status": self.llm.status,
            },
            "warnings": [w.to_dict() for w in self.warnings],
        }


def estimate_seconds(duration_s: float, rtf_low: float, rtf_high: float) -> tuple[float, float]:
    """ETA range for ``duration_s`` of audio at a real-time factor range (audio s per wall s)."""
    if duration_s <= 0 or rtf_low <= 0 or rtf_high <= 0:
        return (0.0, 0.0)
    return (duration_s / max(rtf_low, rtf_high), duration_s / min(rtf_low, rtf_high))


def format_eta(low_s: float, high_s: float) -> str:
    """Human wording for an ETA range, e.g. ``2-5 minutes`` or ``under a minute``."""
    if high_s < 60:
        return "under a minute"
    lo, hi = max(round(low_s / 60), 1), max(round(high_s / 60), 1)
    unit = "minute" if hi == 1 else "minutes"
    return f"about {hi} {unit}" if lo == hi else f"{lo}-{hi} {unit}"


@functools.cache
def load_data(path: Path = DATA_FILE) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a mapping")
    return data


def _transcription(data: dict[str, Any]) -> TranscriptionRecommendation:
    rtf = data["rtf"]
    return TranscriptionRecommendation(
        model=data["model"],
        alternatives=list(data.get("alternatives", [])),
        compute_type=data["compute_type"],
        batch_size=int(data["batch_size"]),
        diarize=data["diarize"],
        rtf_low=float(rtf[0]),
        rtf_high=float(rtf[1]),
        status=data.get("status", "estimated"),
        notes=data.get("notes", ""),
    )


def _llm(data: dict[str, Any]) -> LLMRecommendation:
    return LLMRecommendation(
        summary=data["summary"],
        models=[LLMModelSuggestion(**m) for m in data.get("models", [])],
        context_note=data.get("context_note", ""),
        vram_handoff=data.get("vram_handoff", ""),
        status=data.get("status", "estimated"),
    )


def profile_recommendation(
    profile: ProfileName,
) -> tuple[TranscriptionRecommendation, LLMRecommendation]:
    entry = load_data()["profiles"][profile]
    return _transcription(entry["transcription"]), _llm(entry["llm"])


def whisper_vram_mb(model: str, compute_type: str) -> int | None:
    value = load_data()["vram_needs_mb"]["whisper"].get(model, {}).get(compute_type)
    return int(value) if value is not None else None


def check_risks(
    info: HardwareInfo,
    profile: ProfileName,
    *,
    overridden: bool = False,
    model: str | None = None,
    compute_type: str | None = None,
    diarize: bool = True,
    llm_size_b: float | None = None,
) -> list[HardwareWarning]:
    """Warn about risky combinations for the chosen (or recommended) settings."""
    warnings: list[HardwareWarning] = []
    needs = load_data()["vram_needs_mb"]
    rec_t, _ = profile_recommendation(profile)
    model = model or rec_t.model
    compute_type = compute_type or rec_t.compute_type
    total = info.total_vram_mb

    if not info.cuda_available:
        warnings.append(
            HardwareWarning(
                "info",
                "no_gpu",
                "No supported GPU detected. Transcription runs on the CPU and is much slower "
                "(roughly real time).",
            )
        )
    for name in info.unsupported_gpus:
        warnings.append(
            HardwareWarning("info", "unsupported_gpu", f"{name}; using the CPU instead.")
        )

    if overridden and info.cuda_available:
        detected = profile_for_vram(total)
        order = ["cpu", "vram8", "vram16", "vram24plus"]
        if order.index(profile) > order.index(detected):
            warnings.append(
                HardwareWarning(
                    "warning",
                    "profile_exceeds_hardware",
                    f"The {PROFILE_LABELS[profile]} profile is larger than the detected "
                    f"{total // 1024} GB GPU; expect out-of-memory errors.",
                )
            )

    if info.cuda_available:
        need = whisper_vram_mb(model, compute_type)
        if need is not None:
            if diarize:
                need += int(needs["diarization"])
            if need > total:
                warnings.append(
                    HardwareWarning(
                        "critical",
                        "whisper_oom_risk",
                        f"{model} with {compute_type}{' and diarization' if diarize else ''} "
                        f"needs about {need / 1024:.1f} GB of VRAM but this GPU has "
                        f"{total / 1024:.1f} GB. "
                        "Choose a smaller model or int8_float16.",
                    )
                )
            elif need > info.free_vram_mb:
                warnings.append(
                    HardwareWarning(
                        "warning",
                        "vram_in_use",
                        f"Only {info.free_vram_mb / 1024:.1f} GB of VRAM is free (other programs "
                        f"are using the GPU) but about {need / 1024:.1f} GB is needed. Close them "
                        "or expect an out-of-memory retry.",
                    )
                )
            elif need > total * 0.85:
                warnings.append(
                    HardwareWarning(
                        "warning",
                        "whisper_vram_tight",
                        f"{model} with {compute_type} uses most of this GPU's VRAM; the job may "
                        "retry with a smaller batch size.",
                    )
                )
    elif model in ("large-v3", "large-v3-turbo", "medium"):
        warnings.append(
            HardwareWarning(
                "warning",
                "cpu_large_model",
                f"{model} on the CPU will be very slow; 'small' with int8 is recommended.",
            )
        )

    if llm_size_b is not None and info.cuda_available:
        llm_need = llm_size_b * float(needs["llm_q4_per_b_params"])
        if llm_need > total:
            warnings.append(
                HardwareWarning(
                    "critical",
                    "llm_too_large",
                    f"A {llm_size_b:g}B model needs about {llm_need / 1024:.1f} GB at Q4 but this "
                    f"GPU has {total / 1024:.1f} GB; Ollama would spill to the CPU and run slowly.",
                )
            )
        elif llm_need > total * 0.85:
            warnings.append(
                HardwareWarning(
                    "warning",
                    "llm_tight",
                    f"A {llm_size_b:g}B model leaves little VRAM for context; keep prompts short.",
                )
            )
    if profile == "vram8" and info.cuda_available:
        warnings.append(
            HardwareWarning(
                "info",
                "vram_handoff",
                "On 8 GB, transcription and the LLM never share the GPU: models are unloaded "
                "between stages, so the LLM step starts after transcription finishes.",
            )
        )
    return warnings


def recommend(
    info: HardwareInfo,
    override: str = "auto",
    *,
    model: str | None = None,
    compute_type: str | None = None,
    diarize: bool = True,
    llm_size_b: float | None = None,
) -> Recommendation:
    """Build the full recommendation for the detected hardware and optional user override."""
    profile, overridden = select_profile(info, override)
    transcription, llm = profile_recommendation(profile)
    warnings = check_risks(
        info,
        profile,
        overridden=overridden,
        model=model,
        compute_type=compute_type,
        diarize=diarize,
        llm_size_b=llm_size_b,
    )
    return Recommendation(
        profile=profile,
        profile_label=PROFILE_LABELS[profile],
        overridden=overridden,
        transcription=transcription,
        llm=llm,
        warnings=warnings,
    )
