"""The readable transcript (Phase 15a, R25, ADR-0031): renderer, writer and vault scanners."""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest

from meetingmaster3.domain.transcript import CompanionTranscript, Segment, SpeakerMap, Transcript
from meetingmaster3.errors import MM3Error
from meetingmaster3.exporting import locate as export_locate
from meetingmaster3.markdown.frontmatter import split_frontmatter
from meetingmaster3.markdown.readable_transcript import (
    NEUTRAL,
    SPEAKER_COLOURS,
    clock,
    neutralise,
    render_readable,
)
from meetingmaster3.review import workspace
from meetingmaster3.templates.regenerate import note_path
from meetingmaster3.vault.picker import browse, find_companions, read_identity
from meetingmaster3.vault.readable import find_readable, refresh_readable, write_readable

MID = uuid.UUID("3f2b8c1e-7d4a-4e9b-a6c2-5b1d0e8f9a71")


def seg(i: int, start: float, label: str | None, text: str, end: float | None = None) -> Segment:
    return Segment(id=i, start=start, end=end or start + 4, speaker_label=label, text=text)


def doc(*segments: Segment, names: dict[str, str] | None = None) -> CompanionTranscript:
    return CompanionTranscript(
        meeting_id=MID,
        title="Product Sync",
        note_ref="2026-10-11 - Product Sync",
        transcript=Transcript(
            segments=list(segments), language="en", duration=3725.0, diarized=True
        ),
        speakers=SpeakerMap(names=names or {}),
    )


NAMES = {"SPEAKER_00": "Nick", "SPEAKER_01": "Michelle"}


def body_of(text: str) -> str:
    fm, body = split_frontmatter(text)
    assert fm is not None
    return body


def test_layout_matches_the_review_screen() -> None:
    d = doc(
        seg(0, 254, "SPEAKER_00", "Yes, in the project."),
        seg(1, 258, "SPEAKER_00", "Stand by."),
        seg(2, 279, "SPEAKER_01", "Oh, that came through as plain text."),
        names=NAMES,
    )
    text = render_readable(d, transcript_link="2026-10-11 - Product Sync.transcript")
    fm, body = split_frontmatter(text)
    assert fm is not None
    assert fm.data == {
        "mm3-id": str(MID),
        "mm3-kind": "readable-transcript",
        "mm3-note": "[[2026-10-11 - Product Sync]]",
        "mm3-transcript": "[[2026-10-11 - Product Sync.transcript]]",
        "duration": "1:02:05",
        "language": "en",
        "speakers": ["Nick", "Michelle"],
    }
    lines = body.split("\n")
    assert (
        lines[0].startswith('<span style="color: var(--text-muted)')
        and "MeetingMaster3" in (lines[0])
    )
    assert lines[1] == ""
    assert lines[2] == (
        '<span style="color: var(--text-muted)">04:14</span> '
        f'<mark style="background: {SPEAKER_COLOURS[0]}; font-weight: 600">Nick</mark>'
    )
    assert lines[3] == "Yes, in the project. Stand by."
    assert lines[4] == ""
    assert lines[5].endswith(f'{SPEAKER_COLOURS[1]}; font-weight: 600">Michelle</mark>')
    assert lines[6] == "Oh, that came through as plain text."
    assert body.endswith("plain text.\n") and "\n\n\n" not in body


def test_colours_are_stable_per_speaker_and_match_the_app() -> None:
    d = doc(
        seg(0, 0, "SPEAKER_01", "a"),
        seg(1, 5, "SPEAKER_00", "b"),
        seg(2, 9, "SPEAKER_01", "c"),
        names=NAMES,
    )
    marks = re.findall(r'<mark style="background: ([^;]+);[^>]*>([^<]+)</mark>', render_readable(d))
    assert marks == [
        (SPEAKER_COLOURS[1], "Michelle"),
        (SPEAKER_COLOURS[0], "Nick"),
        (SPEAKER_COLOURS[1], "Michelle"),
    ]
    # the same palette index as the review screen
    view = workspace.transcript_view(d)
    assert [t.colour for t in view.turns] == [1, 0, 1]


def test_unnamed_speakers_and_undiarized_text_are_neutral() -> None:
    d = doc(seg(0, 0, "SPEAKER_03", "a"), seg(1, 5, None, "b"), names={"SPEAKER_00": "Nick"})
    marks = re.findall(r'<mark style="background: ([^;]+);[^>]*>([^<]+)</mark>', render_readable(d))
    assert marks == [(NEUTRAL, "Speaker 1"), (NEUTRAL, "Speaker")]


def test_long_turns_are_split_into_paragraphs() -> None:
    segments = [seg(i, i * 20.0, "SPEAKER_00", f"part{i}.", end=i * 20.0 + 19) for i in range(10)]
    body = body_of(render_readable(doc(*segments, names=NAMES)))
    assert body.count("<mark") == 1  # the heading is not repeated
    paragraphs = body.split("\n\n")[1:]
    assert paragraphs[0].split("\n")[1] == "part0. part1. part2. part3. part4."
    assert paragraphs[1] == "part5. part6. part7. part8. part9.\n"


def test_hour_long_clocks() -> None:
    assert clock(59.9) == "00:59" and clock(254) == "04:14" and clock(3725) == "1:02:05"
    body = body_of(render_readable(doc(seg(0, 3725, "SPEAKER_00", "late"), names=NAMES)))
    assert ">1:02:05</span>" in body


@pytest.mark.parametrize(
    "hostile",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "see [[Secret note]] and ![[embed.png]]",
        "#tag and #another",
        "<!-- mm3:section:summary -->",
        "<!-- /mm3:section:summary -->",
        "%%hidden comment%%",
        "==highlight== ~~strike~~ $x^2$ `code` *em* __b__",
        "- not a list",
        "> not a quote",
        "1. not a list",
        "[link](javascript:alert(1))",
        "a | b | c",
        "block ref ^abc123",
    ],
)
def test_spoken_text_can_never_become_markup(hostile: str) -> None:
    d = doc(seg(0, 0, "SPEAKER_00", hostile), names={"SPEAKER_00": "Nick"})
    body = body_of(render_readable(d))
    text = body.split("\n")[3]
    assert text == neutralise(hostile)
    for live in ("<script", "<img", "<!--", "[[", "![[", "%%", "=="):
        assert live not in text
    assert not re.search(r"(?<!\\)\]\(", text)  # no live link
    assert not re.search(r"(?<!\\)#\w", text)
    assert not re.match(r"[-+>]|\d+\.", text)


def test_hostile_speaker_names_are_escaped() -> None:
    d = doc(seg(0, 0, "SPEAKER_00", "hi"), names={"SPEAKER_00": "Eve <b>&"})
    assert ">Eve &lt;b&gt;&amp;</mark>" in render_readable(d)


def test_no_speech() -> None:
    assert body_of(render_readable(doc())).endswith("_No speech was detected._\n")


# -- writer --------------------------------------------------------------------------------------


@pytest.fixture
def note(vault: Path) -> Path:
    folder = vault / "Meetings" / "2026"
    folder.mkdir(parents=True)
    path = folder / "2026-10-11 - Product Sync.md"
    path.write_text(f"---\nmm3-id: {MID}\ntitle: Product Sync\n---\n# Product Sync\n")
    return path


def test_writer_refreshes_its_own_file_and_never_replaces_others(vault: Path, note: Path) -> None:
    d = doc(seg(0, 0, "SPEAKER_00", "hi"), names=NAMES)
    first = write_readable(vault, note, d)
    assert first.name == "2026-10-11 - Product Sync (Transcript).md"
    mtime = first.stat().st_mtime_ns
    assert write_readable(vault, note, d) == first and first.stat().st_mtime_ns == mtime
    renamed = d.model_copy(update={"speakers": SpeakerMap(names={"SPEAKER_00": "Nicholas"})})
    assert write_readable(vault, note, renamed) == first
    assert ">Nicholas</mark>" in first.read_text()

    other = note.with_name("2026-10-11 - Other (Transcript).md")  # unrelated, fine
    other.write_text("x")
    first.write_text("my own notes\n")  # the user replaced the file: no longer ours
    second = write_readable(vault, note, d)
    assert second.name == "2026-10-11 - Product Sync (Transcript 2).md"
    assert first.read_text() == "my own notes\n"
    assert find_readable(note, str(MID)) == second
    foreign = d.model_copy(update={"meeting_id": uuid.uuid4()})
    assert write_readable(vault, note, foreign).name.endswith("(Transcript 3).md")


def test_refresh_follows_the_setting(vault: Path, note: Path) -> None:
    from meetingmaster3.markdown.transcript_format import render_transcript

    companion = note.with_name("2026-10-11 - Product Sync.transcript.md")
    companion.write_text(render_transcript(doc(seg(0, 0, "SPEAKER_00", "hi"), names=NAMES)))
    assert refresh_readable(vault, note, companion, enabled=False) is None
    assert find_readable(note, str(MID)) is None
    made = refresh_readable(vault, note, companion, enabled=True)
    assert made is not None and made.is_file()
    # an existing one is still kept fresh when the setting is off
    assert refresh_readable(vault, note, companion, enabled=False) == made
    companion.write_text("damaged")
    assert refresh_readable(vault, note, companion, enabled=True) is None


# -- every vault scanner ignores or classifies it ------------------------------------------------


@pytest.fixture
def readable(vault: Path, note: Path) -> Path:
    return write_readable(vault, note, doc(seg(0, 0, "SPEAKER_00", "hi"), names=NAMES))


def test_identity_classifies_it(readable: Path, note: Path) -> None:
    info = read_identity(readable)
    assert info is not None and info.is_readable and not info.is_transcript and not info.is_note
    note_info = read_identity(note)
    assert note_info is not None and note_info.is_note


def test_open_a_note_picker_skips_it(vault: Path, readable: Path) -> None:
    entries = browse(vault, "Meetings/2026").entries
    assert [e.name for e in entries] == ["2026-10-11 - Product Sync.md"]


def test_locate_transcript_does_not_offer_it(vault: Path, readable: Path) -> None:
    assert find_companions(vault, str(MID)) == []


def test_reopen_by_id_never_opens_it(vault: Path, readable: Path, note: Path) -> None:
    assert workspace._matches(vault, readable, str(MID)) is False
    assert workspace._matches(vault, note, str(MID)) is True


def test_regenerate_and_export_refuse_it_as_a_note(vault: Path, readable: Path) -> None:
    rel = readable.relative_to(vault).as_posix()
    with pytest.raises(MM3Error):
        note_path(vault, rel)
    with pytest.raises(MM3Error):
        export_locate(vault, rel)


def test_template_library_never_lists_it(vault: Path, readable: Path) -> None:
    from meetingmaster3.config.settings import Settings
    from meetingmaster3.templates.loader import load_library

    lib = load_library(vault, Settings().vault.templates_subfolder)
    assert all("(Transcript)" not in e.path.name for e in lib.listing())
