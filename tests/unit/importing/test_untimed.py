"""Untimed transcripts (Phase 15k, R32): companion and readable transcript round trips, no clocks
anywhere, and the prompt for one template (golden file
``tests/fixtures/assembler/default-notes-untimed.txt``; regenerate with
``MM3_UPDATE_GOLDEN=1``)."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.transcript import Segment, SpeakerMap, Transcript
from meetingmaster3.exporting import transcript_to_text
from meetingmaster3.markdown import readable_transcript
from meetingmaster3.markdown.transcript_format import (
    build_companion,
    parse_transcript,
    rename_speakers,
    render_transcript,
)
from meetingmaster3.review.workspace import transcript_view
from meetingmaster3.search.chunking import chunk_transcript
from meetingmaster3.templates import assembler
from meetingmaster3.templates.loader import load_library

GOLDEN = Path(__file__).parents[2] / "fixtures" / "assembler" / "default-notes-untimed.txt"
TODAY = dt.date(2026, 10, 24)
TURNS = [
    ("SPEAKER_00", "Can you help me plan a drip irrigation system for forty raised beds?"),
    ("SPEAKER_01", "Yes. Start with a pressure regulator and a filter after the tap."),
    ("SPEAKER_01", "Then split the beds into four zones of ten, each with its own valve."),
    ("SPEAKER_00", "Okay, I'll buy the regulator this weekend."),
]
NAMES = SpeakerMap(names={"SPEAKER_00": "Nick", "SPEAKER_01": "Grok"})


def untimed() -> Transcript:
    segments = [
        Segment(id=i, start=0.0, end=0.0, speaker_label=label, text=text)
        for i, (label, text) in enumerate(TURNS)
    ]
    return Transcript(segments=segments, diarized=True, timed=False)


def companion_text() -> str:
    doc = build_companion(uuid.UUID(int=7), "Garden irrigation", untimed(), NAMES, note_ref="n")
    return render_transcript(doc)


def test_companion_has_no_clocks_and_round_trips() -> None:
    text = companion_text()
    assert "**Nick:** Can you help me plan" in text
    assert "**Grok:** Yes. Start with a pressure regulator" in text
    assert "[00:00:00]" not in text and "duration:" not in text
    assert '"timed":false' in text
    parsed = parse_transcript(text)
    assert parsed.doc.transcript == untimed()
    assert parsed.body_matches_data
    assert [v.name for v in parsed.visible_turns] == ["Nick", "Grok", "Nick"]
    assert render_transcript(parsed.doc, parsed) == text  # byte-identical re-render


def test_renaming_a_speaker_in_an_untimed_companion() -> None:
    renamed = rename_speakers(companion_text(), NAMES.with_name("SPEAKER_01", "Assistant"))
    assert "**Assistant:** Yes. Start" in renamed and "**Grok:**" not in renamed
    assert parse_transcript(renamed).body_matches_data


def test_timed_companions_do_not_gain_the_flag() -> None:
    timed = untimed().model_copy(update={"timed": True})
    text = render_transcript(build_companion(uuid.UUID(int=8), "T", timed, NAMES))
    assert "timed" not in text and "**[00:00:00] Nick:**" in text
    assert parse_transcript(text).doc.transcript.timed


def test_readable_transcript_without_clocks_one_paragraph_per_segment() -> None:
    doc = parse_transcript(companion_text()).doc
    body = readable_transcript.render_body(doc)
    assert "00:00" not in body
    grok = body.split("Grok</mark>")[1].split("<mark")[0]
    assert grok.count("\n\n") >= 2  # the two answers stay separate paragraphs


def test_text_export_review_view_and_search_have_no_times() -> None:
    text = companion_text()
    assert transcript_to_text(text).startswith("Nick\nCan you help me plan")
    view = transcript_view(parse_transcript(text).doc)
    assert not view.timed and view.duration is None
    chunked = chunk_transcript(text, chunk_tokens=350, overlap=50)
    assert chunked.passages and all(p.start_s is None for p in chunked.passages)


def render_prompts() -> str:
    template = load_library().get("default-notes")
    meta = MeetingMeta(title="Garden irrigation", date=dt.datetime(2026, 10, 20, 0, 0))
    named = NAMES.apply(untimed())
    facts = assembler.MeetingFacts.from_meta(meta, named)
    turns = assembler.transcript_turns(named)
    context = assembler.context_block(assembler.format_turns(turns))
    cues = assembler.task_cues(turns)
    parts = ["=== SYSTEM ===", assembler.system_prompt(template, facts, TODAY)]
    for section in template.sections:
        prompt = assembler.section_prompt(template, section, context, cues=cues)
        parts += [f"=== SECTION {section.id} ===", prompt[len(context) :].lstrip("\n")]
    parts += ["=== CONTEXT ===", context]
    return "\n".join(parts) + "\n"


def test_golden_prompt_for_an_untimed_transcript() -> None:
    text = render_prompts()
    if os.environ.get("MM3_UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(text, encoding="utf-8")
    assert text == GOLDEN.read_text(encoding="utf-8")
    assert "Nick: Can you help me plan" in text and "[00:00]" not in text
    assert "has no timestamps" in text and "- Length:" not in text


def test_untimed_sections_lose_clock_references() -> None:
    from meetingmaster3.templates.postprocess import clean_section

    raw = "- **Zones:** [00:12] four zones [mm:ss]\n- Ask [1:02:03\u20131:05:00] later"
    assert clean_section(raw, timed=False) == "- **Zones:** four zones\n- Ask later"
    assert clean_section("- a [00:12]") == "- a [00:12]"  # timed notes keep their references
