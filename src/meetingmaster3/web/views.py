"""View-model helpers for the HTML pages (kept apart from the routes so they are easy to test)."""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.models import JobStatus
from meetingmaster3.vault.naming import note_stem
from meetingmaster3.vault.paths import confine, expand_folder_template, resolve_vault_root

DEFAULT_OUTPUT_SUBFOLDER = "Meetings/{yyyy}/"

STATUS_LABELS = {
    "queued": "Queued",
    "running": "Running",
    "waiting_for_input": "Needs your input",
    "interrupted": "Interrupted",
    "failed": "Failed",
    "cancelled": "Cancelled",
    "written": "Written to vault",
}
STAGE_ICONS = {
    "pending": ("○", "Waiting"),
    "running": ("▶", "Running"),
    "waiting": ("⏸", "Waiting for you"),
    "completed": ("✓", "Done"),
    "failed": ("✗", "Failed"),
    "cancelled": ("■", "Cancelled"),
    "interrupted": ("↻", "Interrupted"),
}
#: Statuses in which a job can be cancelled.
CANCELLABLE = frozenset({"queued", "running", "waiting_for_input"})
RESUMABLE_VALUES = frozenset({"interrupted", "failed", "cancelled"})
#: Job options a "retry" button may override (the whitelist for the form fields ``o_<name>``).
RETRY_OVERRIDES = {
    "transcription_model": str,
    "compute_type": str,
    "batch_size": int,
    "language": str,
    "model": str,
    "backend": str,
}


def format_duration(seconds: float | None) -> str:
    """``3725`` → ``1h 02m``; ``192`` → ``3m 12s``; ``45`` → ``45s``."""
    if seconds is None or seconds < 0:
        return ""
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def obsidian_link(path: str) -> str:
    """``obsidian://open?path=<absolute path>`` with the path URL-encoded."""
    return f"obsidian://open?path={quote(path, safe='')}"


def _parse_ts(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value) if value else None


def stage_elapsed(stage: dict[str, Any], now: dt.datetime | None = None) -> float | None:
    started = _parse_ts(stage.get("started_at"))
    if started is None:
        return None
    end = _parse_ts(stage.get("finished_at"))
    if end is None and stage["status"] == "running":
        end = now or dt.datetime.now(dt.UTC)
    return (end - started).total_seconds() if end else None


@dataclass
class VaultCheck:
    """The result of looking at a candidate vault folder (the setup screen, spec §3)."""

    path: str
    subfolder: str
    root: Path | None = None
    errors: list[MM3Error] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    preview: str | None = None

    @property
    def ok(self) -> bool:
        return self.root is not None and not self.errors


def check_vault(path: str, subfolder: str, today: dt.date | None = None) -> VaultCheck:
    """Validate a vault path and output-subfolder pattern; never creates anything."""
    result = VaultCheck(path=path.strip(), subfolder=subfolder.strip())
    if not result.path:
        return result
    try:
        result.root = resolve_vault_root(result.path)
    except MM3Error as exc:
        result.errors.append(exc)
        return result
    if not (result.root / ".obsidian").is_dir():
        result.warnings.append(
            "No .obsidian folder here, so this does not look like an Obsidian vault yet. "
            "You can continue: Obsidian will treat the folder as a vault once you open it."
        )
    if not result.subfolder:
        result.errors.append(
            MM3Error(
                "vault_folder_template_invalid",
                "The output folder is empty.",
                f"Use a folder pattern such as {DEFAULT_OUTPUT_SUBFOLDER}.",
            )
        )
        return result
    try:
        day = today or dt.date.today()
        expanded = expand_folder_template(result.subfolder, day)
        folder = confine(result.root, expanded)
    except MM3Error as exc:
        result.errors.append(exc)
        return result
    stem = note_stem(day, "Example meeting")
    result.preview = os.path.join(str(folder), f"{stem}.md")
    return result


def vault_relative(vault: Path | str | None, path: str) -> str | None:
    """``path`` relative to the vault root, or ``None`` if it is not inside the vault."""
    if vault is None:
        return None
    try:
        root = resolve_vault_root(vault)
        return Path(path).resolve().relative_to(root).as_posix()
    except (MM3Error, ValueError, OSError):
        return None


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def job_title(job: dict[str, Any]) -> str:
    return str(job.get("title") or job.get("source_filename") or job["id"])


def is_resumable(status: str | JobStatus) -> bool:
    value = status.value if isinstance(status, JobStatus) else status
    return value in RESUMABLE_VALUES


def failure_of(job: dict[str, Any]) -> dict[str, Any] | None:
    """The error to show for a failed job, with the failed stage's ``suggested_overrides``."""
    if job["status"] != "failed":
        return None
    error: dict[str, Any] = dict(job.get("error") or {})
    for stage in job["stages"]:
        if stage["status"] == "failed":
            detail = (stage.get("detail") or {}).get("error") or {}
            details = detail.get("details") or {}
            error.setdefault("code", detail.get("error_code") or detail.get("code"))
            error["stage"] = stage.get("display_name") or stage["stage"]
            error["suggested_overrides"] = details.get("suggested_overrides") or {}
            break
    error.setdefault("suggested_overrides", {})
    return error
