"""One speaker map, applied to the transcript, note metadata and companion transcript."""

from __future__ import annotations

import uuid
from pathlib import Path

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.transcript import SpeakerMap, Transcript
from meetingmaster3.jobs.fakes import fake_transcript
from meetingmaster3.markdown.note_writer import render_note
from meetingmaster3.markdown.transcript_format import (
    build_companion,
    parse_transcript,
    render_transcript,
)
from meetingmaster3.speakers.cascade import (
    NAMED_TRANSCRIPT_FILE,
    apply_speaker_map,
    load_job_speaker_map,
    participants,
    rename_companion_text,
    save_job_speakers,
    speaker_names,
)

MERGED = SpeakerMap(names={"SPEAKER_00": "Alice", "SPEAKER_01": "Alice"})


def test_speaker_names_merge_and_order() -> None:
    m = SpeakerMap(names={"SPEAKER_10": "Zed", "SPEAKER_2": "Bob", "SPEAKER_1": "bob"})
    assert speaker_names(m, ["SPEAKER_1", "SPEAKER_2", "SPEAKER_10"]) == ["bob", "Zed"]
    assert speaker_names(MERGED, ["SPEAKER_00", "SPEAKER_01"]) == ["Alice"]


def test_participants_replace_old_names_and_keep_manual_ones() -> None:
    labels = ["SPEAKER_00", "SPEAKER_01"]
    old = SpeakerMap(names={"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"})
    new = SpeakerMap(names={"SPEAKER_00": "Alice", "SPEAKER_01": "Robert"})
    current = ["Alice", "Bob", "Carol (dial-in)"]
    assert participants(current, new, labels, old) == ["Alice", "Robert", "Carol (dial-in)"]
    # Unmapped speakers are not participants (no "Speaker 2" placeholder).
    assert participants([], SpeakerMap(names={"SPEAKER_00": "Alice"}), labels) == ["Alice"]


def test_cascade_reaches_every_view() -> None:
    t = fake_transcript(30)
    meta = MeetingMeta(title="Sync", participants=["Carol"])
    companion = build_companion(meta.id, "Sync", t, SpeakerMap())
    out = apply_speaker_map(MERGED, t, meta=meta, companion=companion)
    assert {s.speaker_name for s in out.transcript.segments} == {"Alice"}
    assert out.meta is not None and out.meta.speakers == MERGED
    assert out.meta.participants == ["Alice", "Carol"]
    assert out.companion is not None and out.companion.speakers == MERGED
    assert out.companion.named().segments[1].speaker_name == "Alice"

    # The note frontmatter carries mm3-speakers and participants.
    from meetingmaster3.domain.note import Note

    text = render_note(Note(meta=out.meta))
    assert "participants: [Alice, Carol]" in text
    assert "mm3-speakers:\n  SPEAKER_00: Alice\n  SPEAKER_01: Alice" in text

    # Renaming later goes through the same function with the old map.
    renamed = SpeakerMap(names={"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"})
    again = apply_speaker_map(renamed, t, meta=out.meta, old_map=MERGED)
    assert again.meta is not None and again.meta.participants == ["Alice", "Bob", "Carol"]
    assert apply_speaker_map(renamed, t).meta is None


def test_rename_companion_text_keeps_user_edits() -> None:
    t = fake_transcript(30)
    doc = build_companion(uuid.uuid4(), "Sync", t, SpeakerMap())
    text = render_transcript(doc).replace("launch status", "launch status (edited)")
    renamed = rename_companion_text(text, MERGED)
    assert "launch status (edited)" in renamed
    assert parse_transcript(renamed).doc.speakers == MERGED
    assert "Speaker 1" not in renamed.split("---", 2)[2].split("```")[0]


def test_job_folder_round_trip(tmp_path: Path) -> None:
    assert load_job_speaker_map(tmp_path) == SpeakerMap()
    t = fake_transcript(30)
    save_job_speakers(tmp_path, MERGED, t)
    assert load_job_speaker_map(tmp_path) == MERGED
    named = Transcript.model_validate_json((tmp_path / NAMED_TRANSCRIPT_FILE).read_text())
    assert named.segments[0].speaker_name == "Alice"
    assert named.segments[0].speaker_label == "SPEAKER_00"  # labels stay for re-renaming
