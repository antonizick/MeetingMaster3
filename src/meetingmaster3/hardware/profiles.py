"""Hardware profiles, auto-selected from total VRAM or declared by the user."""

from __future__ import annotations

from typing import Literal

from meetingmaster3.errors import MM3Error
from meetingmaster3.hardware.detect import HardwareInfo

ProfileName = Literal["cpu", "vram8", "vram16", "vram24plus"]
PROFILE_NAMES: tuple[ProfileName, ...] = ("cpu", "vram8", "vram16", "vram24plus")
PROFILE_LABELS: dict[str, str] = {
    "cpu": "CPU only",
    "vram8": "8 GB VRAM",
    "vram16": "16 GB VRAM",
    "vram24plus": "24 GB+ VRAM",
}

# Lower bounds in MiB. Cards report slightly less than their nominal size (an "8 GB" card shows
# about 8192 MiB, a "6 GB" card 6144), so the thresholds leave headroom below the nominal size.
_VRAM8_MIN_MB = 7000
_VRAM16_MIN_MB = 14000
_VRAM24_MIN_MB = 22000


def profile_for_vram(total_vram_mb: int) -> ProfileName:
    """Pick a profile from total VRAM. Cards under about 7 GB use the CPU profile."""
    if total_vram_mb >= _VRAM24_MIN_MB:
        return "vram24plus"
    if total_vram_mb >= _VRAM16_MIN_MB:
        return "vram16"
    if total_vram_mb >= _VRAM8_MIN_MB:
        return "vram8"
    return "cpu"


def select_profile(info: HardwareInfo, override: str = "auto") -> tuple[ProfileName, bool]:
    """Return ``(profile, was_overridden)``. ``override`` is ``auto`` or a profile name."""
    if override and override != "auto":
        if override not in PROFILE_NAMES:
            raise MM3Error(
                "invalid_profile",
                f"Unknown hardware profile {override!r}.",
                f"Use one of: auto, {', '.join(PROFILE_NAMES)}.",
            )
        return override, True
    return profile_for_vram(info.total_vram_mb), False
