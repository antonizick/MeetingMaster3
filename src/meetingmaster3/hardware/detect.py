"""Hardware detection: nvidia-smi, then torch.cuda (if importable), then a CPU-only fallback.

Nothing here requires the ML extras. AMD/ROCm and Apple GPUs are reported as unsupported and the
app falls back to CPU.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

NVIDIA_SMI_QUERY = "--query-gpu=name,memory.total,memory.used,driver_version"
NVIDIA_SMI_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class GPUInfo:
    name: str
    vram_total_mb: int
    vram_used_mb: int
    driver_version: str = ""

    @property
    def vram_free_mb(self) -> int:
        return max(self.vram_total_mb - self.vram_used_mb, 0)


@dataclass(frozen=True)
class HardwareInfo:
    gpus: list[GPUInfo] = field(default_factory=list)
    cuda_available: bool = False
    detection_source: str = "cpu"  # "nvidia-smi" | "torch" | "cpu"
    cpu_name: str = ""
    cpu_cores: int = 1
    ram_total_mb: int = 0
    unsupported_gpus: list[str] = field(default_factory=list)  # AMD/Apple etc.
    notes: list[str] = field(default_factory=list)

    @property
    def primary_gpu(self) -> GPUInfo | None:
        """The GPU with the most VRAM (the one jobs run on)."""
        return max(self.gpus, key=lambda g: g.vram_total_mb, default=None)

    @property
    def total_vram_mb(self) -> int:
        gpu = self.primary_gpu
        return gpu.vram_total_mb if gpu else 0

    @property
    def free_vram_mb(self) -> int:
        gpu = self.primary_gpu
        return gpu.vram_free_mb if gpu else 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["total_vram_mb"] = self.total_vram_mb
        data["free_vram_mb"] = self.free_vram_mb
        data["gpus"] = [{**asdict(g), "vram_free_mb": g.vram_free_mb} for g in self.gpus]
        return data


def parse_nvidia_smi(output: str) -> list[GPUInfo]:
    """Parse ``--format=csv,noheader,nounits`` output. Raises ``ValueError`` on garbage."""
    gpus: list[GPUInfo] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4:
            raise ValueError(f"unexpected nvidia-smi line: {line!r}")
        # GPU names do not contain commas in practice, but tolerate it: take the last 3 fields.
        name = ", ".join(parts[:-3])
        total, used, driver = parts[-3:]
        try:
            gpus.append(GPUInfo(name, int(float(total)), int(float(used)), driver))
        except ValueError as exc:
            raise ValueError(f"unexpected nvidia-smi line: {line!r}") from exc
    return gpus


def _run_nvidia_smi() -> str | None:
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return None
    try:
        proc = subprocess.run(  # noqa: S603
            [exe, NVIDIA_SMI_QUERY, "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=NVIDIA_SMI_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("nvidia-smi failed: %s", exc)
        return None
    return proc.stdout if proc.returncode == 0 else None


def _detect_torch() -> list[GPUInfo]:
    """Ask torch.cuda for devices, only if torch is already installed."""
    try:
        import torch
    except Exception:
        return []
    try:
        if not torch.cuda.is_available():
            return []
        gpus = []
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            free, total = torch.cuda.mem_get_info(i)
            gpus.append(
                GPUInfo(
                    props.name,
                    int(total // (1024 * 1024)),
                    int((total - free) // (1024 * 1024)),
                    "",
                )
            )
        return gpus
    except Exception as exc:
        log.info("torch.cuda detection failed: %s", exc)
        return []


def _detect_unsupported_gpus() -> list[str]:
    """Best-effort: spot AMD (ROCm) or Apple GPUs so the UI can say why it is using the CPU."""
    found: list[str] = []
    if shutil.which("rocm-smi") or Path("/dev/kfd").exists():
        found.append("AMD GPU (ROCm is not supported)")
    if os.uname().sysname == "Darwin":
        found.append("Apple GPU (Metal is not supported)")
    return found


def _read_meminfo_mb(meminfo: Path = Path("/proc/meminfo")) -> int:
    try:
        for line in meminfo.read_text().splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _read_cpu_name(cpuinfo: Path = Path("/proc/cpuinfo")) -> str:
    try:
        for line in cpuinfo.read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except (OSError, IndexError):
        pass
    return ""


def detect_hardware(smi_output: str | None = None) -> HardwareInfo:
    """Run the detection chain. ``smi_output`` lets tests inject nvidia-smi output."""
    notes: list[str] = []
    gpus: list[GPUInfo] = []
    source = "cpu"

    raw = smi_output if smi_output is not None else _run_nvidia_smi()
    if raw is not None:
        try:
            gpus = parse_nvidia_smi(raw)
            source = "nvidia-smi" if gpus else "cpu"
        except ValueError as exc:
            notes.append(f"Could not parse nvidia-smi output ({exc}).")
    if not gpus and smi_output is None:
        gpus = _detect_torch()
        if gpus:
            source = "torch"

    unsupported = [] if gpus else _detect_unsupported_gpus()
    if unsupported:
        notes.append("Unsupported GPU detected; falling back to CPU.")
    if not gpus:
        notes.append("No NVIDIA GPU detected; using the CPU profile.")

    return HardwareInfo(
        gpus=gpus,
        cuda_available=bool(gpus),
        detection_source=source,
        cpu_name=_read_cpu_name(),
        cpu_cores=os.cpu_count() or 1,
        ram_total_mb=_read_meminfo_mb(),
        unsupported_gpus=unsupported,
        notes=notes,
    )


_cache: HardwareInfo | None = None
_lock = threading.Lock()


def get_hardware(refresh: bool = False) -> HardwareInfo:
    """Cached detection; ``refresh=True`` re-runs it."""
    global _cache
    with _lock:
        if _cache is None or refresh:
            _cache = detect_hardware()
        return _cache


def clear_cache() -> None:
    global _cache
    with _lock:
        _cache = None
