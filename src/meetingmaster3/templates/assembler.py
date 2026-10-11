"""Prompt assembly: template + meeting facts + transcript → chat messages (pure, no I/O).

Layout (ADR-0017): the system message (global rules, the template's ``_system`` block, meeting
facts, today's date) and the start of the user message (the transcript or the map-reduce notes)
are identical for every section of a note, so a local model can reuse its prompt cache; only the
section-specific tail differs. See ``docs/dev-guide/template-format.md`` §7.
"""

from __future__ import annotations

import datetime as dt
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.transcript import Transcript, group_turns
from meetingmaster3.llm.budget import Turn
from meetingmaster3.templates.schema import Template, TemplateSection

GLOBAL_RULES = """\
You are MeetingMaster3, a meticulous chief of staff who writes meeting notes from transcripts.

Rules that always apply:
1. Use only what is in the transcript (or the meeting notes you are given). Never invent people, \
owners, dates, numbers, decisions or quotes. If something was not said, leave it out or say so.
2. Owners: the owner of a task is the person who said they will do it ("I'll...", "I can...") \
or who was asked and agreed. Someone who only raised an issue, suggested it ("we should...", \
"someone should...") or reported on other people's work is not the owner: write "Unassigned". \
Deadlines: give them exactly as said ("Friday", "end of Q3") or write "not stated"; do not \
convert them into calendar dates.
3. Attribute statements, proposals and commitments to the person who made them, using the \
speaker names exactly as given. "Speaker 1", "Speaker 2" and "Speaker" are unnamed people: keep \
those labels and never guess a real name for them.
4. Be concise and specific. No filler ("the team discussed various topics"), no greetings, no \
praise, no meta-commentary about the transcript or about yourself.
5. You may add a timestamp such as [12:34] after an item to point to where it was said. Use only \
timestamps that appear in the transcript.
6. The transcript comes from automatic speech recognition and may contain misheard words. Prefer \
the meaning that fits the context, and never build a conclusion on a single garbled word.
7. Write in the language of the instructions (English), even if the meeting was in another \
language, unless the instructions say otherwise."""

OUTPUT_RULES = """\
Output rules: return only the content of the "{title}" section, in Markdown. Do not repeat the \
heading, do not add a title, do not wrap the answer in a code block, and do not add any \
introduction or closing remark."""

TRANSCRIPT_OPEN = "<transcript>"
TRANSCRIPT_CLOSE = "</transcript>"
NOTES_OPEN = "<meeting_notes>"
NOTES_CLOSE = "</meeting_notes>"


def clock(seconds: float | None, *, hours: bool = False) -> str:
    """``mm:ss`` (or ``h:mm:ss`` when ``hours``) for a time in seconds, floored."""
    total = math.floor(max(seconds or 0.0, 0.0))
    if hours or total >= 3600:
        return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"
    return f"{total // 60:02d}:{total % 60:02d}"


def transcript_turns(transcript: Transcript) -> list[Turn]:
    """Speaker turns of a *named* transcript (``speaker_name`` set) as budget turns."""
    turns = []
    for t in group_turns(transcript):
        name = t.segments[0].speaker_name or "Speaker"
        text = t.text
        if text:
            turns.append(Turn(speaker=name, text=text, start=t.start))
    return turns


def format_turns(turns: Sequence[Turn], *, hours: bool | None = None) -> str:
    """``[mm:ss] Name: text`` lines (``[h:mm:ss]`` once the meeting passes an hour)."""
    if hours is None:
        hours = any((t.start or 0.0) >= 3600 for t in turns)
    lines = []
    for t in turns:
        stamp = f"[{clock(t.start, hours=hours)}] " if t.start is not None else ""
        lines.append(f"{stamp}{t.speaker}: {t.text}")
    return "\n".join(lines)


@dataclass(frozen=True)
class MeetingFacts:
    title: str
    date: dt.datetime | None
    participants: tuple[str, ...]
    speakers: tuple[str, ...]
    """Names as they appear in the transcript, including placeholders."""
    location: str | None = None
    language: str | None = None
    duration: float | None = None
    diarized: bool = True

    @classmethod
    def from_meta(cls, meta: MeetingMeta, transcript: Transcript) -> MeetingFacts:
        speakers = list(
            dict.fromkeys(s.speaker_name for s in transcript.segments if s.speaker_name)
        )
        return cls(
            title=meta.title,
            date=meta.date,
            participants=tuple(meta.participants),
            speakers=tuple(speakers),
            location=meta.location,
            language=transcript.language,
            duration=transcript.duration,
            diarized=transcript.diarized,
        )


def _date_text(when: dt.datetime | dt.date) -> str:
    if isinstance(when, dt.datetime) and when.time() != dt.time(0):
        return f"{when:%A %Y-%m-%d %H:%M}"
    return f"{when:%A %Y-%m-%d}"


def meeting_block(facts: MeetingFacts, today: dt.date) -> str:
    lines = ["Meeting facts:", f"- Title: {facts.title}"]
    lines.append(f"- Date: {_date_text(facts.date) if facts.date else 'not recorded'}")
    if facts.duration:
        lines.append(f"- Length: {clock(facts.duration, hours=True)}")
    if facts.location:
        lines.append(f"- Location / context: {facts.location}")
    if facts.participants:
        lines.append(f"- Participants: {', '.join(facts.participants)}")
    if not facts.diarized:
        lines.append(
            '- Speakers were not separated: every turn is labelled "Speaker". Do not attribute '
            "statements to individuals unless the speaker names themselves in the text."
        )
    elif facts.speakers:
        lines.append(f"- Speakers in the transcript: {', '.join(facts.speakers)}")
    if facts.language and facts.language != "en":
        lines.append(f"- Spoken language: {facts.language}")
    lines.append(
        f'- Today\'s date: {_date_text(today)}. Relative deadlines ("Friday", "next week") '
        "refer to the meeting date, not to today."
    )
    return "\n".join(lines)


def system_prompt(template: Template, facts: MeetingFacts, today: dt.date) -> str:
    return "\n\n".join(
        [
            GLOBAL_RULES,
            f'Template "{template.name}":\n{template.system_prompt}',
            meeting_block(facts, today),
        ]
    )


def context_block(transcript_text: str | None = None, notes_text: str | None = None) -> str:
    """The shared start of every section's user message."""
    if notes_text is not None:
        return (
            "The meeting was too long to show in full. These notes were extracted from it, in "
            "order, with timestamps and speakers:\n"
            f"{NOTES_OPEN}\n{notes_text}\n{NOTES_CLOSE}"
        )
    return f"Transcript:\n{TRANSCRIPT_OPEN}\n{transcript_text or ''}\n{TRANSCRIPT_CLOSE}"


def section_instructions(template: Template, section: TemplateSection) -> str:
    prompt = template.prompts.get(section.id)
    if prompt:
        return prompt
    return (
        f'Write the "{section.title}" section of the meeting notes, following the rules above. '
        "Use short bullets where they help."
    )


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_TASK_CUE_RE = re.compile(
    r"\b(i'll|i will|i'm going to|i am going to|i can (?:do|take|have|send|look)|"
    r"we'll|we will|can you|could you|would you|will you|please|"
    r"we should|we need to|someone should|somebody should|needs? to|has to|have to|"
    r"let's make sure|action item|follow up|take (?:it|that) offline)\b",
    re.I,
)
MAX_TASK_CUES = 60


def task_cues(turns: Sequence[Turn], *, hours: bool = False) -> list[str]:
    """Sentences that sound like commitments, requests or "we should" (heuristic, in order).

    Given to the model as candidates for task sections: small models otherwise miss tasks in
    long transcripts, and "we should" lines are the ones that become **Unassigned** tasks."""
    out: list[str] = []
    for t in turns:
        for sentence in _SENTENCE_RE.split(t.text):
            if _TASK_CUE_RE.search(sentence):
                stamp = f"[{clock(t.start, hours=hours)}] " if t.start is not None else ""
                out.append(f"{stamp}{t.speaker}: {sentence.strip()}")
    return out[:MAX_TASK_CUES]


def section_prompt(
    template: Template,
    section: TemplateSection,
    context: str,
    *,
    instructions: str | None = None,
    previous: str | None = None,
    feedback: str | None = None,
    cues: Sequence[str] = (),
) -> str:
    """The user message for one section. ``cues`` (task sections only) are candidate lines
    from :func:`task_cues`."""
    parts = [
        context,
        f'Now write the section "{section.title}".\n\n{section_instructions(template, section)}',
    ]
    if cues and section.format == "tasks":
        parts.append(
            "To help you, these transcript sentences sound like commitments, requests or "
            '"we should". Check each one against the transcript: some are tasks (with an '
            "owner, or Unassigned), some are not tasks at all. Tasks can also appear elsewhere."
            "\n<candidates>\n" + "\n".join(cues) + "\n</candidates>"
        )
    if instructions and instructions.strip():
        parts.append(f"Additional instructions from the user:\n{instructions.strip()}")
    if previous is not None:
        parts.append(
            "This section is being regenerated. The previous version was:\n"
            f"<previous_version>\n{previous.strip()}\n</previous_version>"
        )
        parts.append(
            "What the user wants changed:\n" + feedback.strip()
            if feedback and feedback.strip()
            else "Write an improved version: more accurate, specific and complete."
        )
    parts.append(OUTPUT_RULES.format(title=section.title))
    return "\n\n".join(parts)


def adhoc_section(section_id: str, title: str) -> TemplateSection:
    """A section that the template does not define (a user-added one being regenerated)."""
    return TemplateSection(id=section_id, title=title or section_id, kind="narrative")
