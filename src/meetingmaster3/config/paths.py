"""XDG path resolution with ``MM3_*_DIR`` overrides. Directories are created ``0700``."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP = "meetingmaster3"


def _base(env_override: str, xdg_var: str, default: str) -> Path:
    override = os.environ.get(env_override)
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get(xdg_var)
    root = Path(xdg).expanduser() if xdg else Path.home() / default
    return root / APP


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    cache_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.yaml"

    @property
    def database(self) -> Path:
        return self.data_dir / "mm3.db"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def models_dir(self) -> Path:
        override = os.environ.get("MM3_MODELS_DIR")
        return Path(override).expanduser() if override else self.cache_dir / "models"

    def ensure(self) -> None:
        for d in (self.config_dir, self.data_dir, self.jobs_dir, self.logs_dir, self.models_dir):
            d.mkdir(mode=0o700, parents=True, exist_ok=True)


def resolve_paths() -> AppPaths:
    return AppPaths(
        config_dir=_base("MM3_CONFIG_DIR", "XDG_CONFIG_HOME", ".config"),
        data_dir=_base("MM3_DATA_DIR", "XDG_DATA_HOME", ".local/share"),
        cache_dir=_base("MM3_CACHE_DIR", "XDG_CACHE_HOME", ".cache"),
    )
