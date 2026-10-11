"""Merge hardware-based local recommendations (Phase 05) with the cloud suggestions data file."""

from __future__ import annotations

import dataclasses
import logging
from pathlib import Path
from typing import Any

import yaml

from meetingmaster3.hardware.detect import get_hardware
from meetingmaster3.hardware.recommend import recommend

log = logging.getLogger(__name__)

DATA_FILE = Path(__file__).with_name("cloud_recommendations.yaml")


def load_cloud(path: Path = DATA_FILE) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [dict(item) for item in data.get("cloud", [])]


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
