"""An :class:`ImportedConversation` as the pipeline's :class:`Transcript`, plus its speakers.

Each imported turn becomes one segment (id = the turn's index), so the preview can reassign a
turn by segment id. Speakers get the usual ``SPEAKER_00``, ``SPEAKER_01``… labels in order of
first appearance; an AI conversation always has a user and an assistant label, so any turn can
be flipped to the other side even when the guess put every turn on one. Untimed turns get
``start = end = 0`` and the transcript is marked ``timed=False`` (R32).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from meetingmaster3.domain.transcript import Segment, Transcript, clean_name
from meetingmaster3.importing.model import ImportedConversation, Role

DEFAULT_ASSISTANT_NAME = "AI"
LOW_CONFIDENCE = 0.8
"""Turns guessed with less confidence than this are highlighted in the preview."""


@dataclass(frozen=True)
class ImportSpeaker:
    label: str
    role: Role | None
    detected: str
    """The name the file gives ("Grok", "Alice"), or "" when it only gives a role."""
    default_name: str
    """What the speaker is called unless the user changes it."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _label(index: int) -> str:
    return f"SPEAKER_{index:02d}"


def speaker_key(role: Role | None, speaker: str) -> tuple[str, str]:
    if role in ("user", "assistant"):
        return role, ""  # one person per side of an AI conversation, whatever the export says
    return "other", speaker.casefold()


def to_transcript(
    conv: ImportedConversation,
    *,
    user_name: str,
    assistant_name: str = DEFAULT_ASSISTANT_NAME,
) -> tuple[Transcript, list[ImportSpeaker]]:
    keys: dict[tuple[str, str], ImportSpeaker] = {}
    order: list[tuple[str, str]] = []
    if conv.source_format == "chat-unlabelled":
        order = [("user", ""), ("assistant", "")]
    for t in conv.turns:
        if not t.speaker and t.role not in ("user", "assistant"):
            continue
        key = speaker_key(t.role, t.speaker)
        if key not in order:
            order.append(key)
    detected: dict[tuple[str, str], str] = {}
    for t in conv.turns:
        key = speaker_key(t.role, t.speaker)
        if t.speaker and key not in detected:
            detected[key] = clean_name(t.speaker)
    roles: dict[str, Role] = {"user": "user", "assistant": "assistant", "other": "other"}
    for i, key in enumerate(order):
        role = roles[key[0]]
        found = detected.get(key, "")
        if role == "user":
            default = found or user_name
        elif role == "assistant":
            default = found or assistant_name
        else:
            default = found
        keys[key] = ImportSpeaker(_label(i), role, found, clean_name(default))
    timed = conv.timed
    segments = []
    for index, t in enumerate(conv.turns):
        has_speaker = bool(t.speaker) or t.role in ("user", "assistant")
        label = keys[speaker_key(t.role, t.speaker)].label if has_speaker else None
        start = float(t.start or 0.0) if timed else 0.0
        end = max(float(t.end if t.end is not None else start), start) if timed else 0.0
        segments.append(
            Segment(
                id=index,
                start=start,
                end=end,
                speaker_label=label,
                text=t.text,
                words=list(t.words) if timed else [],
            )
        )
    transcript = Transcript(
        segments=segments,
        duration=max((s.end for s in segments), default=0.0) if timed else None,
        diarized=bool(keys),
        timed=timed,
    )
    return transcript, list(keys.values())
