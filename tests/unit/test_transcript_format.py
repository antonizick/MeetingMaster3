from __future__ import annotations

import uuid

import pytest
from hypothesis import HealthCheck, given, settings

from meetingmaster3.domain.transcript import (
    CompanionTranscript,
    Segment,
    SpeakerMap,
    Transcript,
    Word,
)
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.transcript_format import (
    build_companion,
    parse_transcript,
    rename_speakers,
    render_transcript,
    timestamp,
)

from .strategies import companions, speaker_maps

ROUNDTRIP = settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _sample() -> CompanionTranscript:
    t = Transcript(
        segments=[
            Segment(
                id=0,
                start=1.02,
                end=4.5,
                speaker_label="SPEAKER_00",
                text="Good morning.",
                words=[Word(start=1.02, end=1.4, score=0.97, text="Good"), Word(text="morning.")],
            ),
            Segment(id=1, start=4.6, end=8.0, speaker_label="SPEAKER_00", text="Let's begin."),
            Segment(id=2, start=9.25, end=12.0, speaker_label="SPEAKER_01", text="Sounds good."),
            Segment(id=3, start=3725.0, end=3726.0, speaker_label="SPEAKER_00", text="Bye."),
        ],
        language="en",
        duration=3726.4,
        model="large-v3-turbo",
        diarized=True,
    )
    return build_companion(
        uuid.UUID(int=7),
        "Product Sync",
        t,
        SpeakerMap(names={"SPEAKER_00": "Alice"}),
        note_ref="2026-10-11 - Product Sync",
    )


@ROUNDTRIP
@given(companions())
def test_parse_of_render_is_identity(doc: CompanionTranscript) -> None:
    parsed = parse_transcript(render_transcript(doc))
    assert parsed.doc == doc
    assert parsed.body_matches_data


@ROUNDTRIP
@given(companions())
def test_render_of_parse_is_byte_identical(doc: CompanionTranscript) -> None:
    text = render_transcript(doc)
    parsed = parse_transcript(text)
    assert render_transcript(parsed.doc, parsed) == text


@ROUNDTRIP
@given(companions(), speaker_maps)
def test_rename_keeps_labels_and_data(doc: CompanionTranscript, new: SpeakerMap) -> None:
    text = render_transcript(doc)
    out = rename_speakers(text, new)
    parsed = parse_transcript(out)
    assert parsed.doc.speakers == new
    assert parsed.doc.transcript == doc.transcript  # labels, timings, words unchanged
    assert parsed.body_matches_data
    data_block = text[text.rindex("<!-- mm3:transcript-data") :]
    assert out.endswith(data_block)


def test_layout_and_merging() -> None:
    text = render_transcript(_sample())
    assert "**[00:00:01] Alice:** Good morning. Let's begin.\n" in text  # merged turn
    assert "**[00:00:09] Speaker 2:** Sounds good.\n" in text  # unmapped placeholder
    assert "**[01:02:05] Alice:** Bye.\n" in text
    assert 'mm3-note: "[[2026-10-11 - Product Sync]]"' in text
    assert 'duration: "1:02:06"' in text or "duration: 1:02:06" in text


def test_rename_preserves_user_edits_to_readable_text() -> None:
    text = render_transcript(_sample()).replace("2:** Sounds good.", "2:** Sounds great!")
    parsed = parse_transcript(text)
    assert not parsed.body_matches_data
    out = rename_speakers(text, SpeakerMap(names={"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}))
    assert "**[00:00:09] Bob:** Sounds great!" in out


def test_rename_refused_when_turns_were_restructured() -> None:
    text = render_transcript(_sample()).replace("**[00:00:09] Speaker 2:** Sounds good.\n", "")
    with pytest.raises(MM3Error) as exc:
        rename_speakers(text, SpeakerMap(names={"SPEAKER_01": "Bob"}))
    assert exc.value.code == "transcript_turns_mismatch"
    parsed = parse_transcript(text)
    renamed = parsed.doc.model_copy(update={"speakers": SpeakerMap(names={"SPEAKER_01": "Bob"})})
    out = render_transcript(renamed, parsed, rerender=True)
    assert "**[00:00:09] Bob:** Sounds good." in out


def test_html_in_speech_cannot_close_the_data_comment() -> None:
    doc = _sample()
    seg = doc.transcript.segments[0].model_copy(update={"text": "a --> b <!-- c"})
    t = doc.transcript.model_copy(update={"segments": [seg, *doc.transcript.segments[1:]]})
    text = render_transcript(doc.model_copy(update={"transcript": t}))
    block = text[text.rindex("<!-- mm3:transcript-data") :]
    assert "-->" not in block[:-4]
    assert parse_transcript(text).doc.transcript.segments[0].text == "a --> b <!-- c"


def test_empty_and_undiarized() -> None:
    doc = build_companion(uuid.UUID(int=1), "Quiet", Transcript(), SpeakerMap())
    text = render_transcript(doc)
    assert "_No speech was detected._" in text
    assert parse_transcript(text).doc == doc
    t = Transcript(segments=[Segment(id=0, start=0, end=1, text="Hi")], diarized=False)
    text = render_transcript(build_companion(uuid.UUID(int=1), "Solo", t, SpeakerMap()))
    assert "**[00:00:00] Speaker:** Hi" in text


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda t: t.replace("---\nmm3-version", "mm3-version", 1), "not_an_mm3_transcript"),
        (lambda t: t[: t.rindex("<!-- mm3:transcript-data")], "transcript_data_missing"),
        (lambda t: t.replace('"start":1.02', '"start":"x"'), "transcript_data_invalid"),
        (
            lambda t: t.replace("transcript-data v1", "transcript-data v9"),
            "transcript_data_invalid",
        ),
        (lambda t: t.replace('{"id":0', "{broken"), "transcript_data_invalid"),
        (lambda t: t.replace("mm3-id: ", "mm3-idx: "), "not_an_mm3_note"),
    ],
)
def test_damaged_files_give_clear_errors(mutate: object, code: str) -> None:
    text = render_transcript(_sample())
    with pytest.raises(MM3Error) as exc:
        parse_transcript(mutate(text))  # type: ignore[operator]
    assert exc.value.code == code


def test_crlf_bom_and_unknown_keys_preserved() -> None:
    text = render_transcript(_sample()).replace("\n", "\r\n")
    text = "\ufeff" + text.replace(
        "mm3-version: 1\r\n", "mm3-version: 1\r\naliases: [x]  # mine\r\n"
    )
    parsed = parse_transcript(text)
    assert parsed.bom and parsed.doc.newline == "\r\n"
    assert parsed.doc.extra_properties == {"aliases": ["x"]}
    assert render_transcript(parsed.doc, parsed) == text
    out = rename_speakers(text, SpeakerMap(names={"SPEAKER_01": "Bob"}))
    assert "aliases: [x]  # mine\r\n" in out and out.startswith("\ufeff---\r\n")


def test_timestamp() -> None:
    assert timestamp(0) == "00:00:00"
    assert timestamp(83.9) == "00:01:23"
    assert timestamp(36000) == "10:00:00"
    assert timestamp(-1) == "00:00:00"
