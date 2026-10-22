"""Passages from notes and companion transcripts (Phase 15i)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.note import Section
from meetingmaster3.domain.transcript import Segment, SpeakerMap, Transcript
from meetingmaster3.markdown.note_parser import NoteParseError
from meetingmaster3.markdown.note_writer import build_note, render_note
from meetingmaster3.markdown.transcript_format import build_companion, render_transcript
from meetingmaster3.search.chunking import chunk_note, chunk_transcript, pack
from tests.search_corpus import by_key, note_text, transcript_text

ID = uuid.UUID("00000000-0000-4000-8000-000000000099")


def test_pack_windows_with_overlap() -> None:
    assert pack([10] * 10, 35, 12) == [
        range(0, 3),
        range(2, 5),
        range(4, 7),
        range(6, 9),
        range(8, 10),
    ]
    assert pack([10] * 3, 35, 0) == [range(0, 3)]
    assert pack([100, 5, 5], 35, 12) == [range(0, 1), range(1, 3)]  # a long piece stands alone
    assert pack([], 35, 12) == []


def test_note_passages_per_section_with_title_date_and_heading() -> None:
    m = by_key("finance")
    c = chunk_note(note_text(m), chunk_tokens=350, overlap=50)
    assert (c.mm3_id, c.kind, c.title, c.date) == (str(m.id), "note", m.title, "2026-09-02")
    assert c.participants == ("Dana Whitfield", "Raj Patel", "Mei Lin")
    assert c.speakers == ("Dana Whitfield", "Raj Patel")
    assert [p.section_id for p in c.passages] == ["summary", "discussion", "action-items"]
    first = c.passages[0]
    assert first.text.startswith("Q3 Finance Review · 2026-09-02\n## Summary Succinct\n")
    assert "budget overrun of 12 percent" in first.text
    assert first.heading == "Summary Succinct"
    # The header lines (date, participants, transcript link) are metadata, not passages.
    assert not any("**Participants:**" in p.text for p in c.passages)


def test_ai_recommendations_are_not_indexed() -> None:
    c = chunk_note(note_text(by_key("hiring")), chunk_tokens=350, overlap=50)
    assert "ai-recommendations" not in [p.section_id for p in c.passages]
    assert not any("budget" in p.text for p in c.passages)


def _long_note(paragraphs: int, user_text: str = "") -> str:
    body = "\n\n".join(f"Paragraph {i}: " + "word " * 60 for i in range(paragraphs))
    meta = MeetingMeta(id=ID, title="Long", date=dt.datetime(2026, 1, 5, 9, 0))
    text = render_note(build_note(meta, [Section(id="notes", title="Notes", body_markdown=body)]))
    return text + user_text


def test_a_long_section_is_split_with_overlap() -> None:
    c = chunk_note(_long_note(12), chunk_tokens=200, overlap=80)
    assert len(c.passages) > 3
    for p in c.passages:
        assert p.text.startswith("Long · 2026-01-05\n## Notes\n")
        assert len(p.text) <= 200 * 4 + 200  # budget plus the heading lines
    # Consecutive windows share their boundary paragraph.
    tails = [p.text.splitlines()[-1] for p in c.passages[:-1]]
    heads = [p.text.splitlines()[2] for p in c.passages[1:]]
    assert tails == heads


def test_user_text_outside_sections_is_indexed() -> None:
    c = chunk_note(
        _long_note(1, "\nMy own follow-up: call the bank.\n"), chunk_tokens=350, overlap=0
    )
    other = [p for p in c.passages if p.heading == "Other notes"]
    assert len(other) == 1 and "call the bank" in other[0].text
    assert "# Long" not in other[0].text


def test_a_file_without_mm3_id_is_refused() -> None:
    with pytest.raises(NoteParseError):
        chunk_note("---\ntitle: x\n---\n# x\n", chunk_tokens=350, overlap=0)


def test_transcript_windows_carry_times_and_speaker_names() -> None:
    m = by_key("vendor")
    c = chunk_transcript(transcript_text(m), chunk_tokens=20, overlap=0, date="2026-09-16")
    assert (c.kind, c.title, c.date) == ("transcript", "Vendor Contract Sync", "2026-09-16")
    assert c.speakers == ("Dana Whitfield", "Mei Lin")
    first = c.passages[0]
    assert first.text.startswith(
        "Vendor Contract Sync · 2026-09-16\nTranscript\nSpeakers: Dana Whitfield\n"
    )
    assert "Dana Whitfield: The vendor costs exceeded the forecast" in first.text
    assert (first.start_s, first.end_s, first.speakers) == (0.0, 7.5, ("Dana Whitfield",))
    assert [p.start_s for p in c.passages] == sorted(p.start_s or 0 for p in c.passages)


def test_transcript_turns_are_merged_and_unnamed_speakers_stay_out_of_the_people() -> None:
    t = Transcript(
        segments=[
            Segment(id=0, start=0, end=2, speaker_label="SPEAKER_00", text=" One."),
            Segment(id=1, start=2, end=4, speaker_label="SPEAKER_00", text=" Two."),
            Segment(id=2, start=4, end=6, speaker_label="SPEAKER_01", text=" Three."),
        ],
        diarized=True,
    )
    doc = build_companion(ID, "Call", t, SpeakerMap(names={"SPEAKER_00": "Ann"}), note_ref="Call")
    c = chunk_transcript(render_transcript(doc), chunk_tokens=350, overlap=0)
    assert len(c.passages) == 1
    assert c.passages[0].text.endswith("Ann: One. Two.\nSpeaker 2: Three.")
    assert c.passages[0].speakers == ("Ann", "Speaker 2")
    assert c.speakers == ("Ann",)


def test_non_diarized_transcript_has_no_names() -> None:
    t = Transcript(segments=[Segment(id=0, start=0, end=2, text=" Hello there.")], diarized=False)
    doc = build_companion(ID, "Solo", t, SpeakerMap(), note_ref="Solo")
    c = chunk_transcript(render_transcript(doc), chunk_tokens=350, overlap=0)
    assert c.passages[0].text == "Solo\nTranscript\nHello there."
    assert c.passages[0].speakers == () and c.speakers == ()


def test_transcript_overlap_repeats_trailing_lines() -> None:
    lines = [
        Segment(id=i, start=i, end=i + 1, speaker_label="SPEAKER_00", text=f" Line {i} " + "x" * 40)
        for i in range(8)
    ]
    doc = build_companion(
        ID, "T", Transcript(segments=lines, diarized=True), SpeakerMap(), note_ref="T"
    )
    c = chunk_transcript(render_transcript(doc), chunk_tokens=40, overlap=15)
    assert len(c.passages) > 2
    assert all(
        b.start_s is not None and a.end_s is not None and b.start_s < a.end_s
        for a, b in zip(c.passages, c.passages[1:], strict=False)
    )
