"""Import parsers (Phase 15k): detection, each format, prefix collapsing, the role heuristic and
the errors. Fixtures: tests/fixtures/imports/ (synthetic, CC0)."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from meetingmaster3.domain.transcript import Segment, SpeakerMap, Transcript, Word
from meetingmaster3.errors import MM3Error
from meetingmaster3.importing import detect, detect_and_parse
from meetingmaster3.importing.chat import (
    assign_roles,
    collapse_prefixes,
    is_growing_prefix,
    is_tool_status,
    split_paragraphs,
)
from meetingmaster3.importing.convert import to_transcript
from meetingmaster3.markdown.transcript_format import build_companion, render_transcript

FIXTURES = Path(__file__).parents[2] / "fixtures" / "imports"


def parse(name: str):  # type: ignore[no-untyped-def]
    path = FIXTURES / name
    return detect_and_parse(path.read_bytes(), path.name)


@pytest.mark.parametrize(
    ("name", "fmt"),
    [
        ("chatgpt-style.md", "chat-markdown"),
        ("claude-style.md", "chat-markdown"),
        ("voice-mode-unlabelled.md", "chat-unlabelled"),
        ("timestamped.txt", "timestamped-text"),
        ("mm3-export.txt", "timestamped-text"),
        ("captions.vtt", "webvtt"),
        ("captions.srt", "srt"),
    ],
)
def test_detection_picks_the_parser_by_content(name: str, fmt: str) -> None:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    assert detect(text, name) == fmt
    assert detect(text, "renamed.txt") == fmt  # the extension does not decide
    assert parse(name).source_format == fmt


def test_chatgpt_export_roles_names_markdown_and_chrome() -> None:
    conv = parse("chatgpt-style.md")
    assert conv.title == "Planning a team offsite"
    assert [(t.role, t.speaker) for t in conv.turns] == [
        ("user", ""),
        ("assistant", "ChatGPT"),
        ("user", ""),
        ("assistant", "ChatGPT"),
    ]
    answer = conv.turns[1].text
    assert "1. **Venue:** a country house" in answer  # Markdown kept, not taken as a speaker
    assert "Copy" not in answer.splitlines()
    fenced = conv.turns[3].text
    assert "```text" in fenced and "Remaining: 1,800 EUR" in fenced  # not a "Remaining" speaker
    assert "2 / 2" not in fenced
    assert not conv.timed


def test_claude_export_with_heading_roles() -> None:
    conv = parse("claude-style.md")
    assert [t.role for t in conv.turns] == ["user", "assistant", "user", "assistant"]
    assert conv.turns[1].speaker == "Claude"
    assert conv.turns[1].text.splitlines()[1] == "one lamp turning through the dark —"


def test_custom_names_need_a_second_speaker() -> None:
    two = "Nick: Can we ship Friday?\n\nRosa: Yes, if QA passes.\n\nNick: Great.\n\nRosa: Okay.\n"
    conv = detect_and_parse(two.encode())
    assert conv.source_format == "chat-markdown"
    assert [t.speaker for t in conv.turns] == ["Nick", "Rosa", "Nick", "Rosa"]
    notes = "Note: first point.\n\nSome text.\n\nNote: second point.\n"
    assert detect(notes) == "chat-unlabelled"


def test_timestamped_lines_keep_times_and_merge_a_speaker() -> None:
    conv = parse("timestamped.txt")
    assert conv.timed
    first, bob = conv.turns[0], conv.turns[1]
    assert (first.speaker, first.start, first.end) == ("Alice", 4.0, 11.0)
    assert bob.speaker == "Bob" and bob.start == 11.0 and bob.end == 27.0
    assert (
        bob.text
        == "The build is green. I'll tag it this afternoon. The changelog still needs one entry."
    )


def test_mm3_text_export_with_header_lines() -> None:
    conv = parse("mm3-export.txt")
    assert [(t.speaker, t.start) for t in conv.turns] == [
        ("Alice", 4.0),
        ("Bob", 11.0),
        ("Carol", 62.0),
        ("Alice", 3750.0),
    ]


def test_bold_companion_style_lines_and_sentence_colons() -> None:
    text = (
        "**[00:00:05] Alice:** Hello there.\n**[00:01:10] Bob:** Hi.\n"
        "[00:02:00] Then we all agreed on one thing at the end: ship it\n"
    )
    conv = detect_and_parse(text.encode())
    assert [(t.speaker, t.start) for t in conv.turns][:2] == [("Alice", 5.0), ("Bob", 70.0)]
    last = conv.turns[2]  # more than six words before the colon: a sentence, not a name
    assert last.speaker == "" and last.text == "Then we all agreed on one thing at the end: ship it"


def test_webvtt_voice_tags_and_prefixes() -> None:
    conv = parse("captions.vtt")
    assert [(t.speaker, t.start, t.end) for t in conv.turns] == [
        ("Dana", 1.0, 8.0),
        ("Eli", 8.2, 12.0),
        ("Dana", 12.0, 15.25),
    ]
    assert conv.turns[0].text == "Welcome to the planning session. Today we pick the venue."


def test_srt_with_and_without_names() -> None:
    conv = parse("captions.srt")
    assert [t.speaker for t in conv.turns] == ["Frank", "Gina", ""]
    assert conv.turns[1].text == "Yes, it is finally working."
    assert conv.turns[2].role is None


def test_companion_data_block_is_used_exactly() -> None:
    segments = [
        Segment(id=0, start=1.5, end=4.0, speaker_label="SPEAKER_00", text="Hello.",
                words=[Word(start=1.5, end=2.0, score=0.9, text="Hello.")]),
        Segment(id=1, start=4.2, end=7.0, speaker_label="SPEAKER_01", text="Hi, Ana."),
    ]  # fmt: skip
    transcript = Transcript(segments=segments, duration=7.0, diarized=True, model="x")
    import uuid

    doc = build_companion(uuid.uuid4(), "Sync", transcript, SpeakerMap(names={"SPEAKER_00": "Ana"}))
    conv = detect_and_parse(render_transcript(doc).encode(), "a.transcript.md")
    assert conv.source_format == "mm3-companion" and conv.title == "Sync"
    assert [(t.speaker, t.start, t.end) for t in conv.turns] == [
        ("Ana", 1.5, 4.0),
        ("Speaker 2", 4.2, 7.0),
    ]
    assert conv.turns[0].words[0].text == "Hello."


def test_frontmatter_title_and_date() -> None:
    text = "---\ntitle: Garden chat\ndate: 2026-09-30T18:05:00\n---\nUser: hi\n\nGrok: hello\n"
    conv = detect_and_parse(text.encode())
    assert conv.title == "Garden chat"
    assert conv.started_at is not None and conv.started_at.isoformat() == "2026-09-30T18:05:00"


# -- unlabelled ------------------------------------------------------------------------------


def test_growing_prefixes_collapse_despite_punctuation_changes() -> None:
    assert is_growing_prefix(
        "I would like to discuss a, um, idea and I",
        "I would like to discuss a, um, idea, and I need help.",
    )
    assert not is_growing_prefix("Okay.", "Okay.")  # same length is not "growing"
    assert not is_growing_prefix("Yes, it is.", "No, it is not what you think.")
    kept, dropped = collapse_prefixes(
        ["The", "The, so my plan", "The, so my plan is this.", "Answer."]
    )
    assert kept == ["The, so my plan is this.", "Answer."] and dropped == 2


def test_tool_status_lines() -> None:
    assert is_tool_status("Checking current numbers.")
    assert is_tool_status("Let me verify the local file behavior.")
    assert not is_tool_status("Let me think for a second. Um.")
    assert not is_tool_status("Checking " + "x" * 100)


def test_role_heuristic_accuracy_on_the_voice_mode_fixture() -> None:
    text = (FIXTURES / "voice-mode-unlabelled.md").read_text(encoding="utf-8")
    truth = (FIXTURES / "voice-mode-unlabelled.labels").read_text(encoding="utf-8").strip()
    paragraphs, dropped = collapse_prefixes(split_paragraphs(text))
    assert dropped == 3
    assert "2 / 2" not in paragraphs
    assert len(paragraphs) == len(truth)
    roles = assign_roles(paragraphs)
    correct = sum(r[0].upper() == t for (r, _), t in zip(roles, truth, strict=True))
    assert correct / len(truth) >= 0.95, [
        (i, r) for i, ((r, _), t) in enumerate(zip(roles, truth, strict=True)) if r[0].upper() != t
    ]


def test_unlabelled_turns_join_tool_status_and_carry_confidence() -> None:
    conv = parse("voice-mode-unlabelled.md")
    texts = [t.text for t in conv.turns]
    joined = next(t for t in texts if t.startswith("Checking battery timer options."))
    assert "\n\nYes — battery-powered tap timers" in joined
    assert all(0.5 <= t.confidence <= 1.0 for t in conv.turns)
    assert any("guessed" in w for w in conv.warnings)


def test_to_transcript_for_an_unlabelled_chat() -> None:
    conv = parse("voice-mode-unlabelled.md")
    transcript, speakers = to_transcript(conv, user_name="Nick")
    assert [(s.label, s.role, s.default_name) for s in speakers] == [
        ("SPEAKER_00", "user", "Nick"),
        ("SPEAKER_01", "assistant", "AI"),
    ]
    assert not transcript.timed and transcript.duration is None and transcript.diarized
    assert {(s.start, s.end) for s in transcript.segments} == {(0.0, 0.0)}
    assert [s.id for s in transcript.segments] == list(range(len(conv.turns)))


def test_to_transcript_keeps_detected_assistant_names_and_times() -> None:
    _, speakers = to_transcript(parse("claude-style.md"), user_name="Me")
    assert [s.default_name for s in speakers] == ["Me", "Claude"]
    transcript, speakers = to_transcript(parse("timestamped.txt"), user_name="Me")
    assert [s.default_name for s in speakers] == ["Alice", "Bob", "Carol"]
    assert transcript.timed and transcript.duration == 80.0
    srt, speakers = to_transcript(parse("captions.srt"), user_name="Me")
    assert srt.segments[-1].speaker_label is None  # an unnamed caption stays unattributed


# -- errors ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "E_IMPORT_EMPTY"),
        (b"   \n\n", "E_IMPORT_EMPTY"),
        (b"ID3\x00\x00\x00binary", "E_IMPORT_UNREADABLE"),
        (b"\xff\xfe\xfa not utf-8", "E_IMPORT_UNREADABLE"),
        (
            b"text\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f" * 3,
            "E_IMPORT_UNREADABLE",
        ),
    ],
)
def test_unreadable_input(data: bytes, code: str) -> None:
    with pytest.raises(MM3Error) as info:
        detect_and_parse(data, "x.md")
    assert info.value.code == code


def test_size_limit_and_bom() -> None:
    with pytest.raises(MM3Error) as info:
        detect_and_parse(b"a" * 2048, "x.md", max_bytes=1024)
    assert info.value.code == "E_IMPORT_TOO_LARGE" and info.value.status_code == 413
    conv = detect_and_parse("﻿User: hi\r\n\r\nAI: hello\r\n".encode(), "x.md")
    assert [t.text for t in conv.turns] == ["hi", "hello"]


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=600))
def test_parsers_raise_only_mm3_errors(text: str) -> None:
    try:
        conv = detect_and_parse(text.encode("utf-8", "surrogatepass"), "fuzz.md")
    except MM3Error:
        return
    except UnicodeEncodeError:
        return
    assert conv.turns
    to_transcript(conv, user_name="Me")  # every parse converts


@settings(max_examples=150, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.integers(0, 7200),
            st.sampled_from(["Alice", "Bob", "Dr. Ng", ""]),
            st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), max_size=40),
        ),
        max_size=12,
    ),
    st.sampled_from(["lines", "vtt", "srt"]),
)
def test_timed_formats_never_crash(cues: list[tuple[int, str, str]], fmt: str) -> None:
    def stamp(s: int, sep: str = ".") -> str:
        return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}{sep}000"

    if fmt == "lines":
        text = "\n".join(f"[{stamp(s)[:8]}] {n + ': ' if n else ''}{t}" for s, n, t in cues)
    elif fmt == "vtt":
        text = "WEBVTT\n\n" + "\n\n".join(
            f"{stamp(s)} --> {stamp(s + 1)}\n{'<v ' + n + '>' if n else ''}{t}" for s, n, t in cues
        )
    else:
        text = "\n\n".join(
            f"{i + 1}\n{stamp(s, ',')} --> {stamp(s + 1, ',')}\n{n + ': ' if n else ''}{t}"
            for i, (s, n, t) in enumerate(cues)
        )
    try:
        conv = detect_and_parse(text.encode(), "c.txt")
    except MM3Error:
        return
    to_transcript(conv, user_name="Me")
