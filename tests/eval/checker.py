"""Score a generated note against a synthetic meeting's expectations (Phase 09 eval).

Checks: required sections present and in order, AI Recommendations last, markers valid
(the note parses back), every expected decision and action captured (with the right owner),
no invented owners, open questions captured. Matching is by keyword groups: an item matches a
line when every group has at least one alternative in the line (case-insensitive).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.note import AI_RECOMMENDATIONS_ID
from meetingmaster3.domain.transcript import Segment, SpeakerMap, Transcript
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.sections import scan_sections
from meetingmaster3.templates.postprocess import count_paragraphs
from meetingmaster3.templates.schema import Template

MEETINGS_DIR = Path(__file__).parent / "meetings"
OWNER_RE = re.compile(r"\*\*(?P<owner>[^*:]{1,80}):\*\*")
BULLET_RE = re.compile(r"^[-*+]\s")
"""A Markdown list item; a bold line such as ``**Owner**`` (a group heading) is not one."""
CHECKBOX_RE = re.compile(r"^- \[[ xX]\] ")
ACTION_IDS = ("action-items",)
DECISION_IDS = ("decisions",)
QUESTION_IDS = ("open-questions", "deferred-decisions", "risks", "blockers")


@dataclass
class Meeting:
    name: str
    title: str
    date: dt.datetime
    speakers: dict[str, str]
    transcript: Transcript
    expected: dict[str, Any]
    templates: list[str] | None = None
    """Template ids this meeting is meant for (type-specific meetings); ``None`` = any."""

    @property
    def names(self) -> list[str]:
        return list(self.speakers.values())

    def meta(self) -> MeetingMeta:
        return MeetingMeta(title=self.title, date=self.date, participants=self.names)

    def named(self) -> Transcript:
        return SpeakerMap(names=self.speakers).apply(self.transcript)


def load_meeting(path: Path) -> Meeting:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    turns = data["turns"]
    segments = []
    for i, (start, label, text) in enumerate(turns):
        end = turns[i + 1][0] if i + 1 < len(turns) else start + 5
        segments.append(
            Segment(id=i, start=float(start), end=float(end), speaker_label=label, text=text)
        )
    transcript = Transcript(
        segments=segments, language="en", duration=float(turns[-1][0]) + 5, diarized=True
    )
    date = data["date"]
    if not isinstance(date, dt.datetime):
        date = dt.datetime.fromisoformat(str(date))
    return Meeting(
        path.stem,
        data["title"],
        date,
        data["speakers"],
        transcript,
        data["expected"],
        templates=data.get("templates"),
    )


def load_meetings() -> list[Meeting]:
    return [load_meeting(p) for p in sorted(MEETINGS_DIR.glob("*.yaml"))]


def _matches(line: str, groups: list[list[str]]) -> bool:
    low = line.casefold()
    return all(any(alt.casefold() in low for alt in group) for group in groups)


def _owner(line: str) -> str | None:
    m = OWNER_RE.search(line)
    return m.group("owner").strip() if m else None


def _is_unassigned(owner: str | None) -> bool:
    return owner is None or owner.casefold() in {"unassigned", "unknown", "tbd", "owner"}


def _same_person(owner: str, expected: str) -> bool:
    o, e = owner.casefold(), expected.casefold()
    return o == e or o == e.split()[0] or e in o


def _known(owner: str, names: list[str]) -> bool:
    return any(_same_person(owner, n) for n in names) or owner.casefold().startswith("speaker")


@dataclass
class Score:
    meeting: str
    template: str
    checks: dict[str, bool] = field(default_factory=dict)
    found: dict[str, list[str]] = field(default_factory=dict)
    missing: dict[str, list[str]] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    metrics: dict[str, int] = field(default_factory=dict)
    """Reported, never compared with the baseline (they vary from run to run)."""

    @property
    def passed(self) -> bool:
        return all(self.checks.values())

    def ratio(self, kind: str) -> str:
        f, m = len(self.found.get(kind, [])), len(self.missing.get(kind, []))
        return f"{f}/{f + m}"

    def summary(self) -> str:
        flags = " ".join(f"{k}={'ok' if v else 'FAIL'}" for k, v in self.checks.items())
        return (
            f"{self.meeting:<22} {self.template:<20} decisions {self.ratio('decisions'):<5} "
            f"actions {self.ratio('actions'):<5} questions {self.ratio('questions'):<5} {flags}"
        )


def _lines(note_text: str, section_ids: tuple[str, ...]) -> list[str]:
    parsed = parse_note(note_text)
    out: list[str] = []
    for sid in section_ids:
        section = parsed.note.section(sid)
        if section is not None:
            out += [ln.strip() for ln in section.body_markdown.split("\n") if ln.strip()]
    return out


def score_note(
    note_text: str, meeting: Meeting, template: Template, *, strict_questions: bool = False
) -> Score:
    s = Score(meeting.name, template.id)
    parsed = parse_note(note_text)
    s.checks["markers_valid"] = parsed.ok and scan_sections(note_text).ok
    ids = [sec.id for sec in parsed.note.sections]
    wanted = [sec.id for sec in template.sections]
    s.checks["sections_present"] = ids == wanted
    if ids != wanted:
        s.problems.append(f"sections {ids} != template {wanted}")
    s.checks["ai_recommendations_last"] = not ids or (
        ids[-1] == AI_RECOMMENDATIONS_ID
        if template.params.ai_recommendations
        else AI_RECOMMENDATIONS_ID not in ids
    )
    s.checks["no_empty_sections"] = all(sec.body_markdown.strip() for sec in parsed.note.sections)

    exp = meeting.expected
    has = {sec.id for sec in template.sections}
    # Decisions.
    if has & set(DECISION_IDS):
        lines = _lines(note_text, DECISION_IDS)
        for d in exp.get("decisions", []):
            hit = any(_matches(ln, d["any"]) for ln in lines)
            (s.found if hit else s.missing).setdefault("decisions", []).append(d["id"])
        s.checks["decisions_captured"] = not s.missing.get("decisions")
    # Actions.
    if has & set(ACTION_IDS):
        lines = [ln for ln in _lines(note_text, ACTION_IDS) if CHECKBOX_RE.match(ln)]
        named = [a for a in exp.get("actions", []) if a.get("owner")]
        for a in exp.get("actions", []):
            matching = [ln for ln in lines if _matches(ln, a["any"])]
            if a.get("owner"):
                good = [ln for ln in matching if (o := _owner(ln)) and _same_person(o, a["owner"])]
                if good:
                    s.found.setdefault("actions", []).append(a["id"])
                else:
                    s.missing.setdefault("actions", []).append(a["id"])
                    if matching:
                        s.problems.append(f"action {a['id']}: wrong owner in {matching[0]!r}")
            else:
                exclusive = [
                    ln for ln in matching if not any(_matches(ln, n["any"]) for n in named)
                ]
                assigned = [ln for ln in exclusive if not _is_unassigned(_owner(ln))]
                if assigned:
                    s.problems.append(f"action {a['id']} has an invented owner: {assigned[0]!r}")
                    s.missing.setdefault("actions", []).append(a["id"])
                elif exclusive or a.get("optional"):
                    s.found.setdefault("actions", []).append(a["id"])
                else:
                    s.missing.setdefault("actions", []).append(a["id"])
        s.checks["actions_captured"] = not s.missing.get("actions")
        invented = [
            ln
            for ln in lines
            if (o := _owner(ln)) and not _is_unassigned(o) and not _known(o, meeting.names)
        ]
        s.checks["no_invented_owners"] = not invented and not any(
            "invented owner" in p for p in s.problems
        )
        if invented:
            s.problems.append(f"unknown owner: {invented[0]!r}")
        s.checks["checkbox_format"] = all(
            CHECKBOX_RE.match(ln)
            for ln in _lines(note_text, ACTION_IDS)
            if (BULLET_RE.match(ln) and not ln.startswith("- [")) or "(due:" in ln
        )
    # Questions (informational unless strict).
    if has & set(QUESTION_IDS):
        lines = _lines(note_text, QUESTION_IDS)
        for q in exp.get("open_questions", []):
            hit = any(_matches(ln, q["any"]) for ln in lines)
            (s.found if hit else s.missing).setdefault("questions", []).append(q["id"])
        if strict_questions:
            s.checks["questions_captured"] = not s.missing.get("questions")
    _check_sections(s, parsed, template, exp)
    _check_summaries(s, parsed)
    return s


DETAILED_PARAGRAPHS = (2, 4)
DETAILED_WORDS = (120, 600)
"""Prompt targets are about 150-500 words; the check allows 20 % either way."""
SUCCINCT_MAX_SENTENCES = 6
_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.M)
_HEADING_RE = re.compile(r"^#{1,6}\s", re.M)
_SENTENCE_RE = re.compile(r"[.!?](?:\s|$)")
_NUMBERED_RE = re.compile(r"^#{2,4}\s+\d+[.)]\s+\S", re.M)


def _check_summaries(s: Score, parsed: Any) -> None:
    """Phase 15a (R25): Summary Detailed is 2-4 prose paragraphs of roughly 150-500 words, and
    Summary Succinct stays one short paragraph, shorter than the detailed one."""
    detailed = parsed.note.section("summary-detailed")
    succinct = parsed.note.section("summary")
    if detailed is not None:
        body = detailed.body_markdown
        paragraphs = count_paragraphs(body)
        words = len(body.split())
        s.metrics.update(detailed_paragraphs=paragraphs, detailed_words=words)
        lo, hi = DETAILED_PARAGRAPHS
        s.checks["detailed_paragraphs"] = lo <= paragraphs <= hi
        s.checks["detailed_prose"] = not _LIST_RE.search(body) and not _HEADING_RE.search(body)
        s.checks["detailed_length"] = DETAILED_WORDS[0] <= words <= DETAILED_WORDS[1]
        if not s.checks["detailed_paragraphs"]:
            s.problems.append(f"Summary Detailed has {paragraphs} paragraph(s)")
        if not s.checks["detailed_length"]:
            s.problems.append(f"Summary Detailed has {words} words")
    if succinct is not None:
        body = succinct.body_markdown
        sentences = len(_SENTENCE_RE.findall(body.strip() + " "))
        s.metrics.update(succinct_sentences=sentences, succinct_words=len(body.split()))
        short = count_paragraphs(body) <= 1 and sentences <= SUCCINCT_MAX_SENTENCES
        if detailed is not None:
            short = short and len(body.split()) < len(detailed.body_markdown.split())
        s.checks["succinct_short"] = short
        if not short:
            s.problems.append(f"Summary Succinct is long ({sentences} sentences)")


def _check_sections(s: Score, parsed: Any, template: Template, exp: dict[str, Any]) -> None:
    """Type-specific checks (Phase 13): ``expected.sections`` lists keyword groups that must
    appear in a given section, ``expected.forbidden`` lists words that must not appear anywhere
    in the note body (for example, protected characteristics in interview notes). Entries can
    name the ``templates`` they apply to."""

    def applies(entry: dict[str, Any]) -> bool:
        return template.id in entry.get("templates", [template.id])

    for entry in exp.get("sections", []):
        section = parsed.note.section(entry["section"])
        if section is None or not applies(entry):
            continue
        hit = _matches(section.body_markdown, entry["any"])
        (s.found if hit else s.missing).setdefault("content", []).append(entry["id"])
    if s.found.get("content") or s.missing.get("content"):
        s.checks["type_content"] = not s.missing.get("content")
    # Phase 15e: ``expected.numbered`` bounds the number of ``### N. <Title>`` headings in a
    # section; ``expected.limits`` caps a section's sentences and words.
    for entry in [e for e in exp.get("numbered", []) if applies(e)]:
        section = parsed.note.section(entry["section"])
        count = len(_NUMBERED_RE.findall(section.body_markdown)) if section is not None else 0
        s.metrics[f"{entry['section']}_numbered"] = count
        ok = entry["min"] <= count <= entry["max"]
        s.checks[f"numbered_{entry['id']}"] = ok
        if not ok:
            s.problems.append(f"{entry['section']} has {count} numbered headings")
    for entry in [e for e in exp.get("limits", []) if applies(e)]:
        section = parsed.note.section(entry["section"])
        body = section.body_markdown.strip() if section is not None else ""
        sentences, words = len(_SENTENCE_RE.findall(body + " ")), len(body.split())
        ok = sentences <= entry.get("max_sentences", sentences) and words <= entry.get(
            "max_words", words
        )
        s.checks[f"limit_{entry['id']}"] = ok
        if not ok:
            s.problems.append(f"{entry['section']} has {sentences} sentences, {words} words")
    forbidden = [e for e in exp.get("forbidden", []) if applies(e)]
    if forbidden:
        body = "\n".join(sec.body_markdown for sec in parsed.note.sections).casefold()
        bad = [e["id"] for e in forbidden if any(w.casefold() in body for w in e["any"])]
        s.checks["nothing_forbidden"] = not bad
        s.problems += [f"forbidden content: {i}" for i in bad]
