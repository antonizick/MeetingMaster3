"""Merge hardware-based local recommendations (Phase 05) with the cloud data file: generic
suggestions, the measured Best value / Best quality picks and the models known to be unsuitable
(Phase 15h, ADR-0042)."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from meetingmaster3.hardware.detect import get_hardware
from meetingmaster3.hardware.recommend import recommend

log = logging.getLogger(__name__)

DATA_FILE = Path(__file__).with_name("cloud_recommendations.yaml")
SUPPORTED_VERSION = 2
"""The data-file format this code reads. A file with another ``version`` still serves the
generic ``cloud`` list, but no picks or unsuitable models, so a stale install degrades."""
BADGE_LABELS = {"best-value": "Best value", "best-quality": "Best quality"}


@dataclass(frozen=True)
class Pick:
    badge: str
    model: str
    why: str
    measured: str

    @property
    def label(self) -> str:
        return BADGE_LABELS.get(self.badge, self.badge)


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _current(data: dict[str, Any]) -> bool:
    if data.get("version") == SUPPORTED_VERSION:
        return True
    log.warning("cloud_recommendations.yaml version %r is not supported", data.get("version"))
    return False


def load_cloud(path: Path = DATA_FILE) -> list[dict[str, Any]]:
    return [dict(item) for item in _load(path).get("cloud", [])]


def load_picks(kind: str, path: Path = DATA_FILE) -> list[Pick]:
    """The measured recommendations for a backend kind (``bedrock``, ``openrouter``)."""
    data = _load(path)
    if not _current(data):
        return []
    return [
        Pick(
            badge=str(p["badge"]),
            model=str(p["model"]),
            why=" ".join(str(p.get("why", "")).split()),
            measured=str(p.get("measured", "")),
        )
        for p in (data.get("picks") or {}).get(kind, [])
    ]


def load_unsuitable(kind: str, path: Path = DATA_FILE) -> list[tuple[str, str]]:
    """``(model-id prefix, reason)`` pairs for models measured as unable to write notes."""
    data = _load(path)
    if not _current(data):
        return []
    return [
        (str(u["match"]).lower(), str(u["reason"]))
        for u in data.get("unsuitable", [])
        if kind in u.get("kinds", [])
    ]


def unsuitable_reason(model_id: str, rules: Iterable[tuple[str, str]]) -> str | None:
    for prefix, reason in rules:
        if model_id.lower().startswith(prefix):
            return reason
    return None


def local_recommendations(profile: str = "auto") -> dict[str, Any] | None:
    """The hardware-aware Ollama recommendation (Phase 05), or None if detection fails."""
    try:
        return dataclasses.asdict(recommend(get_hardware(), profile).llm)
    except Exception:
        log.exception("Hardware recommendation failed")
        return None


def build(profile: str = "auto") -> dict[str, Any]:
    return {
        "local": local_recommendations(profile),
        "cloud": load_cloud(),
        "note": "Prices change often; follow each pricing_url for current figures.",
    }
