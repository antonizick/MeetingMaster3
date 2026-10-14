"""Prompt assembly: golden snapshots per built-in template, transcript formatting and facts.

Regenerate the snapshots after an intended prompt change with
``MM3_UPDATE_GOLDEN=1 uv run pytest tests/unit/templates/test_assembler.py`` and review the diff.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.transcript import Segment, SpeakerMap, Transcript
from meetingmaster3.llm.budget import Turn
from meetingmaster3.templates import assembler
from meetingmaster3.templates.loader import builtin_files, load_library

GOLDEN = Path(__file__).parents[2] / "fixtures" / "assembler"
TODAY = dt.date(2026, 10, 11)
LINES = [
    (0.0, "SPEAKER_00", "Thanks for joining. Today we decide on the vendor."),
    (
        6.5,
        "SPEAKER_01",
        "I compared both offers. Vendor A is cheaper, Vendor B has better support.",
    ),
    (15.2, "SPEAKER_01", "I'd go with B."),
    (19.0, "SPEAKER_02", "Can we afford B? We should check with finance."),
    (26.4, "SPEAKER_00", "Let's go with B. Ana, can you send the contract to legal by Friday?"),
    (33.0, "SPEAKER_01", "Yes, I'll send it to legal tomorrow."),
]


def fixture_meeting() -> tuple[MeetingMeta, Transcript]:
    segments = [
        Segment(id=i, start=s, end=s + 5, speaker_label=lbl, text=t)
        for i, (s, lbl, t) in enumerate(LINES)
    ]
    transcript = Transcript(segments=segments, language="en", duration=40.0, diarized=True)
    names = SpeakerMap(names={"SPEAKER_00": "Sam Lee", "SPEAKER_01": "Ana Costa"})
    meta = MeetingMeta(
        title="Vendor Choice",
        date=dt.datetime(2026, 10, 7, 9, 30),
        participants=["Sam Lee", "Ana Costa"],
        location="Room 4",
    )
    return meta, names.apply(transcript)


def render_prompts(template_id: str) -> str:
    template = load_library().get(template_id)
    meta, named = fixture_meeting()
    facts = assembler.MeetingFacts.from_meta(meta, named)
    turns = assembler.transcript_turns(named)
    context = assembler.context_block(assembler.format_turns(turns))
    cues = assembler.task_cues(turns)
    parts = ["=== SYSTEM ===", assembler.system_prompt(template, facts, TODAY)]
    for section in template.sections:
        prompt = assembler.section_prompt(template, section, context, cues=cues)
        assert prompt.startswith(context)  # the shared prefix (prompt cache, ADR-0017)
        parts += [f"=== SECTION {section.id} ===", prompt[len(context) :].lstrip("\n")]
    parts += ["=== CONTEXT ===", context]
    return "\n".join(parts) + "\n"


@pytest.mark.parametrize("template_id", [p.stem for p in builtin_files()])
def test_golden_prompts(template_id: str) -> None:
    text = render_prompts(template_id)
    path = GOLDEN / f"{template_id}.txt"
    if os.environ.get("MM3_UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert path.is_file(), f"missing golden file {path}; run with MM3_UPDATE_GOLDEN=1"
    assert text == path.read_text(encoding="utf-8")


def test_transcript_format_and_placeholders() -> None:
    _, named = fixture_meeting()
    text = assembler.format_turns(assembler.transcript_turns(named))
    lines = text.split("\n")
    assert lines[0] == "[00:00] Sam Lee: Thanks for joining. Today we decide on the vendor."
    # Consecutive segments of one speaker form one turn.
    assert lines[1].startswith("[00:06] Ana Costa: I compared both offers.")
    assert lines[1].endswith("I'd go with B.")
    assert lines[2].startswith("[00:19] Speaker 3: Can we afford B?")  # unnamed stays unnamed


def test_hours_format() -> None:
    turns = [Turn("A", "start", 5.0), Turn("B", "late", 3725.0)]
    assert assembler.format_turns(turns) == "[0:00:05] A: start\n[1:02:05] B: late"
    assert assembler.clock(59.9) == "00:59" and assembler.clock(None) == "00:00"


def test_non_diarized_and_foreign_language_facts() -> None:
    t = Transcript(
        segments=[Segment(id=0, start=0, end=1, text="Hola")], language="es", diarized=False
    )
    named = SpeakerMap().apply(t)
    facts = assembler.MeetingFacts.from_meta(MeetingMeta(title="X"), named)
    block = assembler.meeting_block(facts, TODAY)
    assert "Speakers were not separated" in block
    assert "- Spoken language: es" in block
    assert "- Date: not recorded" in block
    assert assembler.format_turns(assembler.transcript_turns(named)) == "[00:00] Speaker: Hola"


def test_regeneration_prompt_parts() -> None:
    template = load_library().get("executive-summary")
    section = template.sections[0]
    prompt = assembler.section_prompt(
        template, section, "CTX", previous="Old body.", feedback="Shorter please."
    )
    assert "<previous_version>\nOld body.\n</previous_version>" in prompt
    assert "What the user wants changed:\nShorter please." in prompt
    no_feedback = assembler.section_prompt(template, section, "CTX", previous="Old body.")
    assert "Write an improved version" in no_feedback


def test_task_candidates_policy() -> None:
    """ADR-0039: with ``params.task_candidates: relevant`` (Default Notes) the candidates are split
    into those naming follow-up work (likely tasks) and the rest (maybe only conversation);
    every other template keeps one list and the strict wording."""
    cues = assembler.task_cues([
        Turn("Ann", "I'll send the plan on Friday.", 5.0),
        Turn("Ben", "I'll put it that way.", 9.0),
        Turn("Ann", "I'll finish the migration script.", 12.0),
    ])  # fmt: skip
    library = load_library()
    strict = library.get("action-focused")
    section = strict.section("action-items")
    assert section is not None
    prompt = assembler.section_prompt(strict, section, "ctx", cues=cues)
    assert "must appear once, however small" in prompt and "<maybe>" not in prompt
    assert "send the plan" in prompt and "put it that way" in prompt

    relevant = library.get("default-notes")
    section = relevant.section("action-items")
    assert section is not None
    prompt = assembler.section_prompt(relevant, section, "ctx", cues=cues)
    likely = prompt.split("<candidates>")[1].split("</candidates>")[0]
    maybe = prompt.split("<maybe>")[1].split("</maybe>")[0]
    assert "send the plan" in likely and "migration script" in likely
    assert "put it that way" in maybe and "put it that way" not in likely
    assert "must appear once" not in prompt and "work to be done after the meeting" in prompt
