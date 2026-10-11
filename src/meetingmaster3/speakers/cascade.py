"""One speaker map, applied everywhere a name appears (pure, apart from the job-folder helpers).

A job stores one :class:`SpeakerMap` (``speaker_map.json``) once the user confirms the names.
:func:`apply_speaker_map` derives every named view from it: the named transcript (the generation
context of Phase 09), the note's ``mm3-speakers`` and ``participants``, and the companion
transcript. Renaming later (Phase 11) calls the same function with the new map and the old one,
so participants that came from the old names are replaced while people the user typed into
``participants`` by hand are kept. :func:`rename_companion_text` updates an existing companion
file's text in place.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.transcript import (
    CompanionTranscript,
    SpeakerMap,
    Transcript,
    natural_key,
)
from meetingmaster3.markdown.transcript_format import rename_speakers
from meetingmaster3.vault.io import atomic_write_text

SPEAKER_MAP_FILE = "speaker_map.json"
NAMED_TRANSCRIPT_FILE = "transcript.named.json"


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for n in names:
        key = n.casefold()
        if n and key not in seen:
            seen.add(key)
            out.append(n)
    return out


def speaker_names(speaker_map: SpeakerMap, labels: list[str]) -> list[str]:
    """Confirmed names in label order, each once (merged labels share one name)."""
    ordered = sorted(set(labels) | set(speaker_map.names), key=natural_key)
    return _dedupe([speaker_map.names[lbl] for lbl in ordered if lbl in speaker_map.names])


def participants(
    current: list[str], new: SpeakerMap, labels: list[str], old: SpeakerMap | None = None
) -> list[str]:
    """The note's participants after (re)naming: the confirmed speakers first, then anyone the
    user listed who did not come from the old speaker map. Placeholders are never listed."""
    old_names = {n.casefold() for n in (old.names.values() if old else ())}
    manual = [p for p in current if p.casefold() not in old_names]
    return _dedupe(speaker_names(new, labels) + manual)


@dataclass(frozen=True)
class Cascade:
    speaker_map: SpeakerMap
    transcript: Transcript
    """The transcript with ``speaker_name`` set on every segment (generation context)."""
    meta: MeetingMeta | None = None
    companion: CompanionTranscript | None = None


def apply_speaker_map(
    speaker_map: SpeakerMap,
    transcript: Transcript,
    *,
    meta: MeetingMeta | None = None,
    companion: CompanionTranscript | None = None,
    old_map: SpeakerMap | None = None,
) -> Cascade:
    """Apply ``speaker_map`` to the transcript, the note metadata and the companion transcript."""
    labels = transcript.speaker_labels
    new_meta = None
    if meta is not None:
        data = meta.model_dump()
        data["speakers"] = speaker_map
        data["participants"] = participants(meta.participants, speaker_map, labels, old_map)
        new_meta = MeetingMeta.model_validate(data)
    new_companion = None
    if companion is not None:
        new_companion = companion.model_copy(update={"speakers": speaker_map})
    return Cascade(speaker_map, speaker_map.apply(transcript), new_meta, new_companion)


def rename_companion_text(text: str, speaker_map: SpeakerMap) -> str:
    """Rewrite an existing companion file's names (raises ``transcript_turns_mismatch`` if the
    user restructured its turns)."""
    return rename_speakers(text, speaker_map)


# -- job folder --------------------------------------------------------------------------------


def save_job_speakers(job_dir: Path, speaker_map: SpeakerMap, transcript: Transcript) -> Path:
    """Store the job's speaker map and its named transcript; returns the map's path."""
    named = speaker_map.apply(transcript)
    atomic_write_text(
        job_dir / NAMED_TRANSCRIPT_FILE, named.model_dump_json(indent=2) + "\n", overwrite=True
    )
    path = job_dir / SPEAKER_MAP_FILE
    atomic_write_text(path, speaker_map.model_dump_json(indent=2) + "\n", overwrite=True)
    return path


def load_job_speaker_map(job_dir: Path) -> SpeakerMap:
    """The job's confirmed speaker map (empty before confirmation)."""
    path = job_dir / SPEAKER_MAP_FILE
    if not path.is_file():
        return SpeakerMap()
    return SpeakerMap.model_validate(json.loads(path.read_text(encoding="utf-8")))
