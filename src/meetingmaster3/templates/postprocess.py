"""Clean a model's section answer into a valid section body (pure).

Models add things we did not ask for: reasoning blocks, code fences, a repeated heading,
"Here is the section:" preambles, stray section markers. Everything here is conservative: it
removes wrapping and normalises structure, and never rewrites the content of a line.
"""

from __future__ import annotations

import re

from meetingmaster3.domain.note import LOOSE_MARKER_RE, normalise_body
from meetingmaster3.templates.schema import SectionFormat

EMPTY_BODY = "_Nothing to report._"

_THINK_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.S | re.I)
_OPEN_THINK_RE = re.compile(r"^\s*<(think|thinking|reasoning)>.*", re.S | re.I)
_FENCE_RE = re.compile(r"^\s*```[A-Za-z]*[ \t]*\n(?P<body>.*?)\n?```\s*$", re.S)
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<text>.*?)[ \t#]*$")
_PREAMBLE_RE = re.compile(
    r"^(?:sure|certainly|of course|okay|ok|here(?:'s| is| are))\b[^\n]{0,120}:\s*$", re.I
)
_HTML_COMMENT_MM3_RE = re.compile(r"<!--[^>]*mm3[^>]*-->", re.I)
_BULLET_RE = re.compile(r"^(?P<indent>[ \t]*)(?:[-*+]|\d+[.)])[ \t]+(?P<rest>.*)$")
_CHECKBOX_RE = re.compile(r"^\[(?P<mark>[ xX]?)\][ \t]*(?P<rest>.*)$")
_LOOSE_CHECKBOX_RE = re.compile(r"^[ \t]*\[(?P<mark>[ xX]?)\][ \t]+(?P<rest>.*)$")


def _strip_reasoning(text: str) -> str:
    text = _THINK_RE.sub("", text)
    # An unclosed reasoning block (output cut off by the token limit) leaves nothing usable.
    return "" if _OPEN_THINK_RE.match(text) else text


def _strip_fence(text: str) -> str:
    m = _FENCE_RE.match(text)
    return m.group("body") if m else text


def _strip_leading(lines: list[str], title: str | None) -> list[str]:
    """Drop blank lines, a chatty preamble and a leading heading (any level)."""
    changed = True
    while changed and lines:
        changed = False
        while lines and not lines[0].strip():
            lines.pop(0)
            changed = True
        if lines and _PREAMBLE_RE.match(lines[0].strip()):
            lines.pop(0)
            changed = True
        if lines and (m := _HEADING_RE.match(lines[0].strip())):
            heading = m.group("text").strip().strip("*_").rstrip(":")
            if len(m.group("hashes")) <= 2 or (
                title and heading.casefold() == title.strip().casefold()
            ):
                lines.pop(0)
                changed = True
        if (
            lines
            and title
            and lines[0].strip().strip("*_").rstrip(":").casefold() == (title.strip().casefold())
        ):
            lines.pop(0)  # "**Action Items:**" as a pseudo-heading
            changed = True
    return lines


def _demote(line: str) -> str:
    m = _HEADING_RE.match(line)
    if m and len(m.group("hashes")) <= 2:
        return f"### {m.group('text')}"
    return line


def _task_line(line: str) -> str:
    """A top-level list item as an Obsidian checkbox. Other lines (nested notes under a task,
    prose) are kept."""
    m = _BULLET_RE.match(line)
    if m and m.group("indent"):
        return line
    if m:
        indent, rest = m.group("indent"), m.group("rest")
    elif _LOOSE_CHECKBOX_RE.match(line):
        indent, rest = "", line.strip()
    else:
        return line
    mark = " "
    cb = _CHECKBOX_RE.match(rest)
    if cb:
        mark = "x" if cb.group("mark").lower() == "x" else " "
        rest = cb.group("rest")
    return f"{indent}- [{mark}] {rest}".rstrip()


def _bullet_line(line: str) -> str:
    m = re.match(r"^(?P<indent>[ \t]*)[*+][ \t]+(?P<rest>.*)$", line)
    return f"{m.group('indent')}- {m.group('rest')}" if m else line


def _is_sentinel(lines: list[str]) -> bool:
    """A single "nothing here" sentence (e.g. "No action items were agreed.")."""
    return len(lines) == 1 and not _BULLET_RE.match(lines[0]) and len(lines[0]) < 120


def clean_section(text: str, *, title: str | None = None, fmt: SectionFormat = "markdown") -> str:
    """The section body to store: never empty, never containing an mm3 marker."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _strip_reasoning(text)
    text = _strip_fence(text.strip("\n"))
    text = _HTML_COMMENT_MM3_RE.sub("", text)
    lines = [ln.rstrip() for ln in text.split("\n")]
    lines = [ln for ln in lines if not LOOSE_MARKER_RE.match(ln)]
    lines = _strip_leading(lines, title)
    lines = [_demote(ln) for ln in lines]
    if fmt == "tasks" and not _is_sentinel([ln for ln in lines if ln.strip()]):
        lines = [_task_line(ln) for ln in lines]
    elif fmt == "bullets":
        lines = [_bullet_line(ln) for ln in lines]
    body = normalise_body("\n".join(lines))
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body or EMPTY_BODY
