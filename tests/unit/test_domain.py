from __future__ import annotations

import datetime as dt
import uuid

import pytest
from pydantic import ValidationError

from meetingmaster3.domain.filenames import parse_filename
from meetingmaster3.domain.meeting import UNTITLED, MeetingMeta
from meetingmaster3.domain.note import Note, Section, TextBlock, normalise_body
from meetingmaster3.domain.transcript import (
    CompanionTranscript,
    Segment,
    SpeakerMap,
    Transcript,
    group_turns,
)


def seg(i: int, label: str | None, text: str = "x") -> Segment:
    return Segment(id=i, start=float(i), end=i + 0.5, speaker_label=label, text=text)


def test_speaker_map_placeholders_are_stable() -> None:
    t = Transcript(segments=[seg(0, "SPEAKER_10"), seg(1, "SPEAKER_2"), seg(2, None)])
    assert t.speaker_labels == ["SPEAKER_2", "SPEAKER_10"]
    m = SpeakerMap()
    assert [m.display_name(s.speaker_label, t.speaker_labels) for s in t.segments] == [
        "Speaker 2",
        "Speaker 1",
        "Speaker",
    ]
    m = m.with_name("SPEAKER_2", "  Alice \n Smith ")
    assert m.names == {"SPEAKER_2": "Alice Smith"}
    named = m.apply(t)
    assert [s.speaker_name for s in named.segments] == ["Speaker 2", "Alice Smith", "Speaker"]
    assert t.segments[0].speaker_name is None  # apply returns a copy
    assert m.display_name("SPEAKER_99", []) == "Speaker 1"


def test_speaker_map_validation() -> None:
    with pytest.raises(ValidationError):
        SpeakerMap(names={"bad label": "x"})
    with pytest.raises(ValidationError):
        SpeakerMap(names={"SPEAKER_00": "  "})
    with pytest.raises(ValidationError):
        Segment(id=0, start=0, end=1, text="x", speaker_label="no spaces")


def test_transcript_validation_and_turns() -> None:
    with pytest.raises(ValidationError):
        Transcript(segments=[seg(0, "A"), seg(0, "B")])
    with pytest.raises(ValidationError):
        Segment(id=0, start=float("nan"), end=1, text="x")
    t = Transcript(segments=[seg(0, "A", " hi  there "), seg(1, "A", ""), seg(2, "B"), seg(3, "A")])
    turns = group_turns(t)
    assert [(x.speaker_label, len(x.segments)) for x in turns] == [("A", 2), ("B", 1), ("A", 1)]
    assert turns[0].text == "hi there"
    assert (turns[0].start, turns[0].end) == (0.0, 1.5)


def test_meeting_meta_normalisation() -> None:
    m = MeetingMeta(
        title="  Weekly\nSync ",
        participants=["Alice", " Alice", "", "Bob"],
        tags=["#meeting", "two words", "meeting"],
        location="  ",
    )
    assert m.title == "Weekly Sync"
    assert m.participants == ["Alice", "Bob"]
    assert m.tags == ["meeting", "two-words"]
    assert m.location is None
    assert MeetingMeta(title="   ").title == UNTITLED
    with pytest.raises(ValidationError):
        MeetingMeta(transcript_ref="a|b")
    with pytest.raises(ValidationError):
        MeetingMeta(unknown="x")  # type: ignore[call-arg]


def test_section_validation() -> None:
    s = Section(id="summary", title="  Summary ", body_markdown="\r\n\n  \nText\r\nmore\n\n")
    assert (s.title, s.body_markdown) == ("Summary", "Text\nmore")
    for bad_id in ("Summary", "-a", "a b", "", "a" * 65):
        with pytest.raises(ValidationError):
            Section(id=bad_id, title="x")
    with pytest.raises(ValidationError):
        Section(id="a", title="x", body_markdown="<!-- mm3:section:b -->")
    with pytest.raises(ValidationError):
        Section(id="a", title="", body_markdown="## looks like a title")
    assert Section(id="a", title="", body_markdown="plain").title == ""
    assert normalise_body("  indented\n") == "  indented"


def test_note_canonical_blocks_and_views() -> None:
    meta = MeetingMeta(id=uuid.UUID(int=1), title="T")
    note = Note(
        meta=meta,
        blocks=[
            TextBlock(text="# T\n"),
            TextBlock(text="- **Participants:** A\nintro"),  # merged, gets a newline
            Section(id="a", title="A"),
            TextBlock(text=""),  # dropped
            Section(id="b", title="B"),
            {"kind": "text", "text": "tail"},
        ],
    )
    assert [type(b).__name__ for b in note.blocks] == [
        "TextBlock",
        "Section",
        "Section",
        "TextBlock",
    ]
    assert note.preamble == "# T\n- **Participants:** A\nintro\n"
    assert note.header_markdown == "- **Participants:** A\n"
    assert note.interstitial_text == [""]
    assert note.trailing_text == "tail"
    assert note.section("b") == Section(id="b", title="B")
    assert note.section("zzz") is None
    updated = note.with_section(Section(id="a", title="A", body_markdown="new"))
    assert updated.section("a").body_markdown == "new"  # type: ignore[union-attr]
    with pytest.raises(KeyError):
        note.with_section(Section(id="zzz", title="Z"))
    with pytest.raises(ValidationError):
        Note(meta=meta, blocks=[Section(id="a", title="A"), Section(id="a", title="A")])
    with pytest.raises(ValidationError):
        Note(meta=meta, extra_properties={"title": "clash"})
    bare = Note(meta=meta)
    assert (bare.preamble, bare.trailing_text, bare.interstitial_text) == ("", "", [])
    assert Note(meta=meta, blocks=[TextBlock(text="no heading")]).header_markdown == ""


def test_companion_transcript_validation() -> None:
    doc = CompanionTranscript(meeting_id=uuid.UUID(int=1), title=" ", transcript=Transcript())
    assert doc.title == "Untitled meeting"
    assert doc.named() == Transcript()
    with pytest.raises(ValidationError):
        CompanionTranscript(
            meeting_id=uuid.UUID(int=1), title="x", transcript=Transcript(), note_ref="[[x]]"
        )
    with pytest.raises(ValidationError):
        CompanionTranscript(
            meeting_id=uuid.UUID(int=1),
            title="x",
            transcript=Transcript(),
            extra_properties={"language": "en"},
        )


@pytest.mark.parametrize(
    ("name", "date", "time", "title"),
    [
        ("2026-10-11 Product Sync.m4a", dt.date(2026, 10, 11), None, "Product Sync"),
        ("2026-10-11 - Product Sync.mp3", dt.date(2026, 10, 11), None, "Product Sync"),
        ("20261011_143000.wav", dt.date(2026, 10, 11), dt.time(14, 30), None),
        ("Zoom_Recording_2026-10-11_14-30-00.mp4", dt.date(2026, 10, 11), dt.time(14, 30), None),
        ("GMT20261011-143000_Recording.m4a", dt.date(2026, 10, 11), dt.time(14, 30), None),
        (
            "Product Sync-20261011_143000-Meeting Recording.mp4",
            dt.date(2026, 10, 11),
            dt.time(14, 30),
            "Product Sync",
        ),
        ("Recording_20261011_143000.m4a", dt.date(2026, 10, 11), dt.time(14, 30), None),
        (
            "abc-defg-hij (2026-10-11 at 14 30 GMT-7).mp4",
            dt.date(2026, 10, 11),
            dt.time(14, 30),
            "abc-defg-hij",
        ),
        ("2026.10.11 Board.wav", dt.date(2026, 10, 11), None, "Board"),
        ("New Recording 3.m4a", None, None, None),
        ("Quarterly planning.ogg", None, None, "Quarterly planning"),
        ("2026-13-45 Bad date.wav", None, None, "2026-13-45 Bad date"),
        ("C:\\Users\\me\\2026-10-11 Sync.wav", dt.date(2026, 10, 11), None, "Sync"),
        ("noextension", None, None, "noextension"),
    ],
)
def test_parse_filename(
    name: str, date: dt.date | None, time: dt.time | None, title: str | None
) -> None:
    info = parse_filename(name)
    assert (info.date, info.time, info.title) == (date, time, title)


def test_filename_when() -> None:
    assert parse_filename("20261011_143000.wav").when == dt.datetime(2026, 10, 11, 14, 30)
    assert parse_filename("2026-10-11 x.wav").when == dt.datetime(2026, 10, 11)
    assert parse_filename("x.wav").when is None
