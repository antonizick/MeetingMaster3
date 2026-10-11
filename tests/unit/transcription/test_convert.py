from __future__ import annotations

from typing import Any

from meetingmaster3.transcription.convert import (
    clean_segments,
    finite,
    split_by_speaker,
    talk_time,
    to_transcript,
)
from meetingmaster3.transcription.engine import SpeakerTurn


def words(*spec: tuple[str, float, float, str | None]) -> list[dict[str, Any]]:
    return [
        {"word": w, "start": s, "end": e, **({"speaker": sp} if sp else {})} for w, s, e, sp in spec
    ]


def test_finite() -> None:
    assert finite("1.5") == 1.5 and finite(2) == 2.0
    assert finite(float("nan")) is None and finite(float("inf")) is None
    assert finite(None) is None and finite("x") is None


def test_clean_segments_drops_chars_and_nans() -> None:
    raw = [
        {
            "start": -0.2,
            "end": float("nan"),
            "text": " Hi",
            "chars": [{"char": "H"}],
            "avg_logprob": -0.1,
            "words": [{"word": "Hi", "start": float("nan"), "score": 0.5, "speaker": "S1"}],
            "speaker": "SPEAKER_00",
        }
    ]
    [seg] = clean_segments(raw)
    assert seg == {
        "start": 0.0,
        "end": 0.0,
        "text": " Hi",
        "words": [{"word": "Hi", "start": None, "end": None, "score": 0.5, "speaker": "S1"}],
        "speaker": "SPEAKER_00",
        "avg_logprob": -0.1,
    }


def test_to_transcript_normalises_and_numbers_segments() -> None:
    segs = [
        {"start": 0.0, "end": 1.0, "text": "   "},  # empty: dropped
        {"start": 1.0, "end": 0.5, "text": " Hello \n there ", "speaker": "SPEAKER_01",
         "words": [{"word": " Hello", "start": 1.0, "end": 1.2, "score": float("nan")},
                   {"word": "  ", "start": 1.2}]},
        {"start": 2.0, "end": 3.0, "text": "Bad label", "speaker": "not ok!"},
    ]  # fmt: skip
    t = to_transcript(segs, language="en", duration=3.0004, model="small", diarized=True)
    assert [s.id for s in t.segments] == [0, 1]
    first = t.segments[0]
    assert first.text == "Hello there" and first.end == 1.0  # end clamped to start
    assert first.speaker_label == "SPEAKER_01"
    assert [w.text for w in first.words] == ["Hello"] and first.words[0].score is None
    assert t.segments[1].speaker_label is None  # invalid label refused
    assert t.duration == 3.0 and t.diarized
    undiarized = to_transcript(segs, language=None, duration=None, model=None, diarized=False)
    assert undiarized.speaker_labels == [] and not undiarized.diarized


def test_split_by_speaker_splits_and_smooths_jitter() -> None:
    seg = {
        "start": 0.0,
        "end": 5.0,
        "text": "Is it ready? Yes it is.",
        "speaker": "A",
        "words": words(
            ("Is", 0.0, 0.2, "A"),
            ("it", 0.2, 0.4, "B"),  # 0.2 s blip between A runs: jitter
            ("ready?", 0.4, 0.9, "A"),
            ("Yes", 2.0, 2.3, "B"),
            ("it", 2.3, 2.4, None),  # no speaker: inherits B
            ("is.", 2.4, 2.8, "B"),
        ),
    }
    out = split_by_speaker([seg])
    assert [(s["speaker"], s["text"], s["start"], s["end"]) for s in out] == [
        ("A", "Is it ready?", 0.0, 0.9),
        ("B", "Yes it is.", 2.0, 2.8),
    ]
    assert all("_speaker" not in w for s in out for w in s["words"])


def test_split_by_speaker_keeps_single_speaker_and_wordless_segments() -> None:
    same = {"start": 0, "end": 1, "text": "a b", "speaker": "A",
            "words": words(("a", 0, 0.5, "A"), ("b", 0.5, 1, "A"))}  # fmt: skip
    bare = {"start": 1, "end": 2, "text": "no words"}
    assert split_by_speaker([same, bare]) == [same, bare]


def test_split_keeps_real_short_interjections() -> None:
    seg = {"start": 0, "end": 3, "text": "so then yes right", "speaker": "A",
           "words": words(("so", 0, 0.3, "A"), ("then", 0.3, 0.6, "A"),
                          ("yes", 1.0, 1.6, "B"), ("right", 2.0, 2.4, "A"))}  # fmt: skip
    out = split_by_speaker([seg])
    assert [s["speaker"] for s in out] == ["A", "B", "A"]  # 0.6 s "yes" is not jitter


def test_split_without_spaces_for_cjk() -> None:
    seg = {"start": 0, "end": 2, "text": "はいいいえ", "speaker": "A",
           "words": words(("はい", 0, 0.5, "A"), ("いいえ", 1, 2, "B"))}  # fmt: skip
    assert [s["text"] for s in split_by_speaker([seg], "ja")] == ["はい", "いいえ"]


def test_talk_time() -> None:
    turns = [SpeakerTurn(0, 2, "A"), SpeakerTurn(2, 7, "B"), SpeakerTurn(7, 8, "A")]
    assert talk_time(turns) == {"B": 5.0, "A": 3.0}
    assert list(talk_time(turns)) == ["B", "A"]
