"""Words for the review screen's recording-retention line (R26).

One place builds the sentence, so the page, the in-place update after Keep forever / Allow
deletion, and the tests all agree. The numbers come from ``jobs.retention`` (the pruner's rule).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from dataclasses import dataclass
from typing import Any

from meetingmaster3.jobs.retention import RetentionStatus
from meetingmaster3.storage.repositories import JobRecord


@dataclass(frozen=True)
class RetentionView:
    text: str  # the muted line
    action: str | None  # "keep" | "release" | None (no button)
    button: str  # button label ("" when there is no button)
    undo_text: str  # what Allow deletion would mean, for the confirm dialog
    settings_link: bool  # the text ends with a link to Settings → Privacy

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _when(status: RetentionStatus) -> str:
    if status.kind == "due" or status.expires_at is None:
        return "at the next check (it runs daily and at start-up)"
    local = status.expires_at.astimezone()
    date = f"{local.day} {local:%b %Y}"
    days = status.days_left or 1
    return f"in {days} day{'' if days == 1 else 's'} ({date})"


def describe(
    status: RetentionStatus, *, undo: RetentionStatus | None = None
) -> RetentionView | None:
    """The line for a status, or ``None`` when the existing no-audio message applies."""
    undo_text = ""
    if undo is not None and undo.kind in ("expires", "due"):
        undo_text = f"The recording will be deleted {_when(undo)}."
    elif undo is not None and undo.kind == "kept_setting":
        undo_text = "Your retention setting keeps recordings forever, so it stays for now."
    if status.kind == "kept_pinned":
        return RetentionView(
            "Recording kept forever.", "release", "Allow deletion", undo_text, False
        )
    if status.kind == "kept_setting":
        return RetentionView(
            "Recording kept: your retention setting keeps recordings forever.",
            "keep",
            "Keep this one even if the setting changes",
            "",
            True,
        )
    if status.kind in ("expires", "due"):
        verb = "deleted" if status.kind == "expires" else "due to be deleted"
        text = f"Recording {verb} {_when(status)} under your retention setting."
        return RetentionView(text, "keep", "Keep forever", "", True)
    return None


def for_job(
    job: JobRecord, status: RetentionStatus, privacy: Any, now: dt.datetime | None = None
) -> RetentionView | None:
    from meetingmaster3.jobs.retention import audio_retention_status

    undo = None
    if job.audio_pinned:
        undo = audio_retention_status(dataclasses.replace(job, audio_pinned=False), privacy, now)
    return describe(status, undo=undo)
