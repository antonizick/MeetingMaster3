"""Golden files in tests/fixtures/notes/ (see tests/fixtures/README.md).

Regenerate the generated pair with ``MM3_UPDATE_GOLDEN=1 uv run pytest tests/unit/test_golden.py``
and review the diff before committing.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path

import pytest

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.note import Section
from meetingmaster3.domain.transcript import Segment, SpeakerMap, Transcript, Word
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.note_writer import build_note, render_note
from meetingmaster3.markdown.sections import replace_section
from meetingmaster3.markdown.transcript_format import (
    build_companion,
    parse_transcript,
    render_transcript,
)
from meetingmaster3.vault.io import read_text

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "notes"
STEM = "2026-10-11 - Product Sync"
SPEAKERS = SpeakerMap(names={"SPEAKER_00": "Alice Chen", "SPEAKER_01": "Bob Okafor"})
MEETING_ID = uuid.UUID("3f2b8c1e-7d4a-4e9b-a6c2-5b1d0e8f9a71")


def sample_note_text() -> str:
    meta = MeetingMeta(
        id=MEETING_ID,
        title="Product Sync",
        date=dt.datetime(2026, 10, 11, 14, 0),
        participants=["Alice Chen", "Bob Okafor", "Charlie Diaz"],
        tags=["meeting", "product"],
        location="Zoom",
        template_id="executive-summary",
        backend="ollama",
        model="qwen3:8b",
        generated_at=dt.datetime(2026, 10, 11, 15, 2, 11),
        transcript_ref=f"{STEM}.transcript",
        speakers=SPEAKERS,
    )
    sections = [
        Section(
            id="summary",
            title="Summary",
            body_markdown=(
                "The team agreed to ship the onboarding redesign on 2026-10-20 behind a feature "
                "flag. Analytics instrumentation is the main open dependency [00:04:12]."
            ),
        ),
        Section(
            id="ai-recommendations",
            title="AI Recommendations",
            body_markdown="- Confirm the analytics owner before the release date is announced.",
        ),
        Section(
            id="decisions",
            title="Decisions Made",
            body_markdown=(
                "- **Ship onboarding v2 behind a flag on 2026-10-20.** Rationale: limits risk "
                "while support is staffed for launch week. (Alice Chen)"
            ),
        ),
        Section(
            id="action-items",
            title="Action Items",
            body_markdown=(
                "- [ ] Bob Okafor: add funnel events to the new flow. Due: 2026-10-16\n"
                "- [ ] Owner: unassigned: draft the support macro. Due: not stated"
            ),
        ),
    ]
    return render_note(build_note(meta, sections, extra_properties={"aliases": ["Product Sync"]}))


def sample_transcript_text() -> str:
    t = Transcript(
        segments=[
            Segment(
                id=0,
                start=0.84,
                end=4.1,
                speaker_label="SPEAKER_00",
                text=" Okay, let's get started with the onboarding redesign.",
                words=[
                    Word(start=0.84, end=1.2, score=0.91, text="Okay,"),
                    Word(start=1.3, end=1.52, score=0.95, text="let's"),
                ],
            ),
            Segment(
                id=1,
                start=4.3,
                end=7.9,
                speaker_label="SPEAKER_00",
                text=" I think we can ship it on the twentieth.",
            ),
            Segment(
                id=2,
                start=8.4,
                end=12.75,
                speaker_label="SPEAKER_01",
                text=" Only if the funnel events are in. I can take that.",
            ),
            Segment(
                id=3,
                start=13.1,
                end=15.0,
                speaker_label="SPEAKER_02",
                text=" Support will need a macro too.",
            ),
        ],
        language="en",
        duration=2537.4,
        model="large-v3-turbo",
        diarized=True,
    )
    return render_transcript(
        build_companion(MEETING_ID, "Product Sync", t, SPEAKERS, note_ref=STEM)
    )


@pytest.mark.parametrize(
    ("name", "make"),
    [(f"{STEM}.md", sample_note_text), (f"{STEM}.transcript.md", sample_transcript_text)],
)
def test_generated_golden_files(name: str, make: object) -> None:
    path = FIXTURES / name
    text = make()  # type: ignore[operator]
    if os.environ.get("MM3_UPDATE_GOLDEN") == "1":
        path.write_text(text, encoding="utf-8", newline="")
    assert read_text(path) == text


def test_golden_pair_links_both_ways() -> None:
    note = parse_note(read_text(FIXTURES / f"{STEM}.md"))
    companion = parse_transcript(read_text(FIXTURES / f"{STEM}.transcript.md"))
    assert note.ok
    assert note.note.meta.transcript_ref == f"{STEM}.transcript"
    assert companion.doc.note_ref == STEM
    assert companion.doc.meeting_id == note.note.meta.id
    assert [s.id for s in note.note.sections][-1] == "ai-recommendations"


def test_user_edited_fixture_round_trips_and_regenerates_safely() -> None:
    text = read_text(FIXTURES / "user-edited.md")
    parsed = parse_note(text)
    assert parsed.ok
    assert render_note(parsed.note, base=parsed) == text
    assert parsed.note.extra_properties["status"] == "reviewed"
    assert "My follow-up" in parsed.note.interstitial_text[0]
    out = replace_section(text, "summary", "A regenerated summary.")
    before, after = (
        text.split("<!-- mm3:section:summary -->")[0],
        text.split("<!-- /mm3:section:summary -->")[1],
    )
    assert out.startswith(before) and out.endswith(after)
    assert "A regenerated summary." in out


def test_damaged_fixture_reports_errors_and_keeps_text() -> None:
    text = read_text(FIXTURES / "damaged-markers.md")
    parsed = parse_note(text)
    assert [(e.kind, e.section_ids) for e in parsed.marker_errors] == [
        ("unclosed", ("summary",)),
        ("misnested", ("summary",)),
    ]
    assert [s.id for s in parsed.note.sections] == ["action-items"]
    assert render_note(parsed.note, base=parsed) == text
