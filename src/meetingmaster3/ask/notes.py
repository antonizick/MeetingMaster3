"""Answer notes in the vault (Phase 15j, R31): render, write, find and delete.

An answer is written once, atomically, to ``<vault>/<ask.answers_subfolder>/YYYY-MM-DD HHMM -
<short question>.md`` and never overwritten (a counter is added on collision). Its frontmatter has
``mm3-kind: answer`` and an ``mm3-answer-id`` but **no** ``mm3-id``, so nothing that looks for
meetings (the picker, re-link, upgrade, the search index) takes it for one. The meetings it used
are ``[[wikilinks]]`` in ``mm3-sources`` and in the body, so Obsidian's backlinks show the answer
from each meeting, and renaming a meeting (R28) rewrites them like any other link.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from meetingmaster3.ask.pipeline import AskResult, MeetingResult, PersonRow, TableRow
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.frontmatter import (
    FrontmatterError,
    render_frontmatter,
    split_frontmatter,
)
from meetingmaster3.markdown.transcript_format import timestamp
from meetingmaster3.vault.io import atomic_write_text, read_text
from meetingmaster3.vault.naming import NOTE_SUFFIX, sanitize_title, with_counter
from meetingmaster3.vault.paths import confine, ensure_folder, is_inside

_TAG_RE = re.compile(r"<(?=[A-Za-z!/?])")
ANSWER_KIND = "answer"
ANSWER_TAG = "mm3/answer"
SHORT_QUESTION_CHARS = 60
TITLE_CHARS = 120
HEAD_BYTES = 8192
MAX_SCAN_FILES = 5000


def short_question(question: str, limit: int = SHORT_QUESTION_CHARS) -> str:
    """The question cut at a word boundary, for the file name."""
    text = " ".join(question.split()).rstrip("?!. ")
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    return text[: cut if cut > limit // 2 else limit].rstrip(" ,;:")


def answer_stem(asked: dt.datetime, question: str) -> str:
    return f"{asked:%Y-%m-%d %H%M} - {sanitize_title(short_question(question))}"


def safe_text(text: str) -> str:
    """One line of model or user text for the note: whitespace collapsed and HTML tags defused
    (Obsidian renders raw HTML in a note)."""
    return _TAG_RE.sub("&lt;", " ".join(text.split()))


def _cell(text: str) -> str:
    """Text safe inside a Markdown table cell (Obsidian needs ``\\|`` even inside links)."""
    return safe_text(text).replace("|", "\\|") or "-"


def meeting_url(base_url: str, mm3_id: str, note_path: str | None, at: float | None = None) -> str:
    """A MeetingMaster3 link to the meeting (and a moment of its recording)."""
    url = f"{base_url}/meetings/{quote(mm3_id, safe='')}"
    if note_path:
        url += f"?path={quote(note_path, safe='')}"
    if at is not None:
        url += f"#t={int(at)}"
    return url


def render_table(rows: list[TableRow]) -> str:
    lines = [
        "| Date | Meeting | Attendees | Took part in the topic | Stated role |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        roles = "; ".join(f"{name}: {role}" for name, role in r.roles)
        depth = "" if r.relevance == "yes" else " (briefly)"
        lines.append(
            f"| {r.date or '-'} | [[{r.stem}]]{depth} | {_cell(', '.join(r.attendees))} | "
            f"{_cell(', '.join(r.spoke))} | {_cell(roles)} |"
        )
    return "\n".join(lines)


def render_people(people: list[PersonRow]) -> str:
    lines = ["| Person | Meetings | Stated role |", "|---|---|---|"]
    for p in people:
        lines.append(f"| {_cell(p.name)} | {p.meetings} | {_cell('; '.join(p.roles))} |")
    return "\n".join(lines)


def _source_line(m: MeetingResult, base_url: str) -> str:
    depth = "in depth" if m.relevance == "yes" else "briefly"
    line = f"- [[{m.stem}]] · {m.date or 'no date'} · {depth}"
    if m.finding:
        line += f": {safe_text(m.finding)}"
    moments = [
        f"[{timestamp(q.start_s)}]({meeting_url(base_url, m.mm3_id, m.note_path, q.start_s)})"
        for q in m.quotes
        if q.start_s is not None
    ]
    if moments:
        line += f" Moments: {', '.join(dict.fromkeys(moments))}."
    return line


def _duration(seconds: float) -> str:
    s = round(seconds)
    return f"{s // 60} min {s % 60} s" if s >= 60 else f"{s} s"


def render_trace(result: AskResult) -> list[str]:
    t = result.trace
    lines = []
    for plan in t.plans:
        label = "Searches" if plan.round == 0 else "Follow-up searches"
        how = {"model": "", "repaired": " (plan repaired)", "fallback": " (the question itself)"}
        queries = ", ".join(f"“{safe_text(q)}”" for q in plan.queries) or "none new"
        lines.append(f"- {label}{how[plan.source]}: {queries}")
        if plan.date_from or plan.date_to:
            dates = f"{plan.date_from or '…'} to {plan.date_to or '…'}"
            note = " (nothing in them, so all dates were searched)" if plan.dates_dropped else ""
            lines.append(f"  - Dates from the question: {dates}{note}")
    if t.search_reason:
        lines.append(f"- Search: words only ({t.search_reason})")
    relevant = len(result.rows)
    lines.append(
        f"- Meetings read: {t.read} of {t.candidates} found; {relevant} relevant"
        + (f" ({t.follow_up_reason}, so one more round was searched)" if t.follow_up else "")
    )
    if t.capped:
        lines.append(f"- {t.capped}")
    for unread in t.unread:
        lines.append(f"- Not read: {unread}")
    if t.stripped:
        lines.append(f"- Links removed (not among the meetings read): {', '.join(t.stripped)}")
    if t.tables_dropped:
        lines.append("- A table the model drew was replaced by the one built from the files")
    if t.fixed:
        lines.append(f"- Links corrected to the note's name: {', '.join(t.fixed)}")
    if t.previous_question:
        lines.append(f"- Follows up: “{t.previous_question}”")
    where = "on this computer" if result.is_local else "in the cloud"
    tokens = ""
    if t.input_tokens or t.output_tokens:
        tokens = f", {t.input_tokens:,} tokens in, {t.output_tokens:,} out"
    lines.append(
        f"- Model: {result.model} on {result.backend} ({where}); {t.calls} calls, "
        f"{_duration(t.seconds)}{tokens}"
    )
    return lines


def render_answer_note(
    result: AskResult, answer_id: str, base_url: str, *, newline: str = "\n"
) -> str:
    relevant = result.relevant
    data = {
        "mm3-kind": ANSWER_KIND,
        "mm3-answer-id": answer_id,
        "question": result.question,
        "asked": result.started_at.replace(microsecond=0).isoformat(),
        "mm3-backend": result.backend,
        "mm3-model": result.model,
        "mm3-sources": [f"[[{r.stem}]]" for r in result.rows],
        "tags": [ANSWER_TAG],
    }
    full = safe_text(result.question)
    title = full if len(full) <= TITLE_CHARS else short_question(full, TITLE_CHARS) + " …"
    parts = [render_frontmatter(data, newline=newline).rstrip("\n"), f"# {title}"]
    if title != full:
        parts.append(f"> [!question] Question\n> {full}")
    parts += ["## Answer", result.answer.strip()]
    if result.rows:
        deep = sum(1 for r in result.rows if r.relevance == "yes")
        parts += [
            "## Meetings",
            f"{len(result.rows)} meeting{'' if len(result.rows) == 1 else 's'} discuss this "
            f"({deep} in depth, {len(result.rows) - deep} briefly). The table is built from the "
            "meeting files.",
            render_table(result.rows),
        ]
    if result.people:
        parts += ["## People", render_people(result.people)]
    if relevant:
        parts += ["## Sources", "\n".join(_source_line(m, base_url) for m in relevant)]
    parts += ["## How this was answered", "\n".join(render_trace(result))]
    return newline.join(f"{p}{newline}" for p in parts if p).replace(
        f"{newline}{newline}{newline}", f"{newline}{newline}"
    )


@dataclass(frozen=True)
class SavedAnswer:
    path: Path
    relative: str


def answers_folder(root: Path, subfolder: str) -> Path:
    return ensure_folder(root, subfolder or "MM3 Answers/")


def write_answer_note(
    root: Path, subfolder: str, result: AskResult, answer_id: str, base_url: str, limit: int = 100
) -> SavedAnswer:
    """Write the note under a free name (``… (2).md`` on collision); never overwrites."""
    folder = answers_folder(root, subfolder)
    stem = answer_stem(result.started_at, result.question)
    text = render_answer_note(result, answer_id, base_url)
    for n in range(1, limit + 1):
        path = folder / f"{with_counter(stem, n)}{NOTE_SUFFIX}"
        if path.exists():
            continue
        try:
            atomic_write_text(path, text, vault_root=root)
        except MM3Error as exc:
            if exc.code == "vault_file_exists":
                continue
            raise
        return SavedAnswer(path, path.relative_to(root).as_posix())
    raise MM3Error(
        "E_ASK_NAME",
        "No free file name for the answer note.",
        "Delete or rename some answers in the answers folder.",
        status_code=409,
    )


def read_answer_id(path: Path) -> str | None:
    """The ``mm3-answer-id`` of a vault file, or ``None`` if it is not an answer note."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(HEAD_BYTES).decode("utf-8", errors="replace")
        fm, _ = split_frontmatter(head.removeprefix("﻿"))
    except (OSError, FrontmatterError):
        return None
    if fm is None or not isinstance(fm.data, dict) or fm.data.get("mm3-kind") != ANSWER_KIND:
        return None
    value = fm.data.get("mm3-answer-id")
    return str(value) if value else None


def resolve_answer(root: Path, relative: str | None, answer_id: str) -> Path | None:
    """The answer note: at its recorded place if it is still the same answer, else found by its
    ``mm3-answer-id`` anywhere in the vault (moved or renamed in Obsidian, like ADR-0047)."""
    if relative:
        try:
            path = confine(root, relative)
        except MM3Error:
            path = None
        if path is not None and path.is_file() and read_answer_id(path) == answer_id:
            return path
    return find_answer(root, answer_id)


def find_answer(root: Path, answer_id: str, max_files: int = MAX_SCAN_FILES) -> Path | None:
    seen = 0
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(names):
            if not name.endswith(NOTE_SUFFIX):
                continue
            seen += 1
            if seen > max_files:
                return None
            path = Path(folder) / name
            if read_answer_id(path) == answer_id:
                return path
    return None


def delete_answer_note(root: Path, path: Path, answer_id: str) -> bool:
    """Delete the note if it is inside the vault and is this answer. False if it was not there."""
    if not is_inside(root, path) or not path.is_file():
        return False
    if read_answer_id(path) != answer_id:
        raise MM3Error(
            "E_ASK_NOT_ANSWER",
            "That file is not this answer's note, so it was not deleted.",
            "",
            status_code=409,
        )
    path.unlink()
    return True


def note_body(path: Path) -> str:
    return read_text(path)


def new_answer_id() -> str:
    return str(uuid.uuid4())
