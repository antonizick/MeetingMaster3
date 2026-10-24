"""Parsers for conversations with AI assistants exported as Markdown.

*Labelled* exports name the speaker of every message: headings (``## User``), bold or plain
prefixes (``**You:**``, ``Grok:``, ``ChatGPT said:``), or a person's name followed by a colon
that repeats. Markdown inside a message is kept; export chrome ("Copy", "Share", ``2 / 2``
counters) is dropped.

*Unlabelled* exports (Grok voice mode) are paragraphs separated by blank lines with nothing to
say who spoke. :func:`parse_unlabelled` drops UI artefacts, collapses the growing prefixes that
speech-to-text leaves behind (the same utterance repeated, each copy longer), then assigns roles
with a scored heuristic and a two-state Viterbi pass that allows runs (an answer may span
several paragraphs). Every turn carries the posterior probability of its role as its confidence,
so the preview can highlight the doubtful ones.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

from meetingmaster3.importing.model import ImportedConversation, ImportedTurn, Role, unreadable

USER_WORDS = frozenset({"user", "you", "me", "human", "i", "prompt", "question"})
ASSISTANT_WORDS = frozenset(
    {
        "assistant", "ai", "bot", "model", "answer", "response",
        "grok", "chatgpt", "gpt", "claude", "gemini", "bard", "copilot", "perplexity",
        "llama", "mistral", "deepseek", "pi", "meta",
    }
)  # fmt: skip
NOT_SPEAKERS = frozenset(
    {
        "note", "notes", "example", "step", "warning", "tip", "important", "summary", "output",
        "input", "result", "source", "sources", "update", "edit", "ps", "pros", "cons", "option",
        "problem", "solution", "q", "a", "why", "how", "what", "context", "goal", "status",
    }
)  # fmt: skip
"""Words that start "Label: text" lines inside a message without naming a speaker."""
GENERIC_ASSISTANT = frozenset({"assistant", "ai", "bot", "model", "answer", "response"})
CHROME = re.compile(
    r"^(?:\d+\s*/\s*\d+|copy|copy code|share|edit|retry|regenerate|like|dislike|"
    r"thought for \d+(?:\.\d+)?\s*s(?:econds?)?|read aloud|show more|show less)\.?$",
    re.I,
)

_HEADING = re.compile(r"^#{1,6}\s+(?P<name>[^#\n]{1,60}?)\s*:?\s*#*\s*$")
_BOLD = re.compile(r"^\*\*(?P<name>[^*\n]{1,60}?)\s*(?::\*\*|\*\*\s*:?)\s*(?P<text>.*)$")
_PLAIN = re.compile(r"^(?P<name>[A-Za-z][\w .'-]{0,39}?)\s*:\s*(?P<text>.*)$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_TITLE = re.compile(r"^#\s+(?P<title>.+?)\s*#*\s*$")


def _role_of(name: str) -> Role | None:
    key = name.casefold().strip(" *:").removesuffix(" said").strip()
    first = key.split()[0] if key.split() else ""
    if key in USER_WORDS:
        return "user"
    if key in ASSISTANT_WORDS or first in ASSISTANT_WORDS - GENERIC_ASSISTANT:
        return "assistant"
    return None


def display_name(name: str, role: Role | None) -> str:
    """The speaker's name as the export gives it: "Grok" and "Claude" are kept; generic role
    words become "" (the importer then uses the configured default)."""
    clean = " ".join(name.strip(" *:").split())
    clean = re.sub(r"\s+said$", "", clean, flags=re.I)
    if role == "user" and clean.casefold() in USER_WORDS:
        return ""
    if role == "assistant" and clean.casefold() in GENERIC_ASSISTANT:
        return ""
    return clean


# -- labelled ----------------------------------------------------------------------------------


@dataclass
class _Marker:
    line: int
    name: str
    text: str
    role: Role | None


def _candidates(lines: list[str]) -> list[_Marker]:
    out = []
    fenced = False
    for i, raw in enumerate(lines):
        line = raw.strip()
        if _FENCE.match(line):
            fenced = not fenced
            continue
        if fenced or not line:
            continue
        for pattern in (_HEADING, _BOLD, _PLAIN):
            m = pattern.match(line)
            if m:
                name = m["name"].strip()
                text = m.groupdict().get("text") or ""
                out.append(_Marker(i, name, text.strip(), _role_of(name)))
                break
    return out


def _markers(lines: list[str]) -> list[_Marker]:
    """The speaker markers of a labelled export (empty when it has none)."""
    found = _candidates(lines)
    roles = [m for m in found if m.role is not None]
    counts = Counter(m.name.casefold() for m in found if m.role is None and len(m.name) <= 40)
    custom = {
        n for n, c in counts.items() if c >= 2 and len(n.split()) <= 3 and n not in NOT_SPEAKERS
    }
    # A repeated "Name:" is a speaker only alongside role words or a second repeated name, so a
    # document with two "Note:" lines is not a conversation.
    if not roles and len(custom) < 2:
        return []
    keep = [m for m in found if m.role is not None or m.name.casefold() in custom]
    if len(keep) < 2:
        return []
    for m in keep:
        if m.role is None:
            m.role = "other"
    return keep


def labelled_score(text: str) -> float:
    lines = text.splitlines()
    markers = _markers(lines)
    if len(markers) < 2:
        return 0.0
    return min(1.0, len(markers) / 4)


def _body(lines: list[str]) -> str:
    kept = [ln.rstrip() for ln in lines if not CHROME.match(ln.strip())]
    return "\n".join(kept).strip("\n")


def find_title(lines: list[str]) -> str | None:
    for line in lines:
        if not line.strip():
            continue
        m = _TITLE.match(line.strip())
        if m and _role_of(m["title"]) is None:
            return m["title"].strip()
        return None
    return None


def parse_labelled(text: str, filename: str) -> ImportedConversation:
    lines = text.splitlines()
    markers = _markers(lines)
    if len(markers) < 2:
        raise unreadable("No speaker labels were found in that conversation.")
    title = find_title(lines[: markers[0].line])
    turns: list[ImportedTurn] = []
    for i, m in enumerate(markers):
        end = markers[i + 1].line if i + 1 < len(markers) else len(lines)
        body = _body(([m.text] if m.text else []) + lines[m.line + 1 : end])
        if not body:
            continue
        role = m.role
        name = display_name(m.name, role) if role in ("user", "assistant") else m.name
        if turns and turns[-1].speaker == name and turns[-1].role == role:
            prev = turns.pop()
            body = prev.text + "\n\n" + body
        turns.append(ImportedTurn(speaker=name, role=role, text=body))
    if not turns:
        raise unreadable("The conversation's messages are empty.")
    return ImportedConversation(turns, title, None, "chat-markdown")


# -- unlabelled --------------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_DISFLUENCY = re.compile(r"\b(?:um+|uh+|erm+|hmm+|mm+|uh-huh)\b", re.I)
_STUTTER = re.compile(r"\b(\w+),? \1\b", re.I)
_USER_OPENING = re.compile(
    r"^(?:okay|ok|so|um|uh|yeah|yes|no|well|interesting|wow|sorry|alright|all right|"
    r"hmm|hey|hi|and|but|also|wait|right|fair|cool|great|thanks|thank you)\b",
    re.I,
)
_FIRST_PERSON = re.compile(r"\b(?:i|i'm|i've|i'd|i'll|my|me|mine|myself)\b", re.I)
_SECOND_PERSON = re.compile(r"\b(?:you'd|you'll|you've|your|yours|you're)\b", re.I)
_ASKS_ASSISTANT = re.compile(
    r"\b(?:can you|could you|would you|do you|are you|tell me|correct me|what's|what is|"
    r"how do|how does|how will|is it|is that|does that|should i|can i|will i)\b",
    re.I,
)
_TOOL_STATUS = re.compile(
    r"^(?:checking|looking (?:up|into|at)|pulling up|searching|fetching|browsing|reading|"
    r"let me (?:check|verify|look|search|pull|confirm|find|see what)|one moment|"
    r"give me a (?:second|moment) to (?:check|look))\b",
    re.I,
)
_MARKDOWN = re.compile(r"`|\*\*|^\s*(?:[-*+]|\d+[.)])\s|^#{1,6}\s|\[[^\]]+\]\(", re.M)
_NUMBERS = re.compile(r"\d[\d,.]*\s*(?:%|percent|euros?|dollars?|gb|mb|ms)|[$€£]\s*\d", re.I)

USER_START = 0.8
"""Prior that a conversation's first paragraph is the user's."""
STAY = {"user": 0.12, "assistant": 0.45}
"""Probability that the next paragraph has the same role (answers often span paragraphs; a
user's consecutive paragraphs are rare once growing prefixes are collapsed)."""


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def is_growing_prefix(shorter: str, longer: str) -> bool:
    """``shorter`` is an earlier, cut-off copy of ``longer`` (speech-to-text repeats an utterance
    as it grows), ignoring punctuation, case and small recognition changes."""
    a, b = _tokens(shorter), _tokens(longer)
    if not a or len(a) >= len(b):
        return False
    head = b[: len(a)]
    if a == head:
        return True
    if len(a) < 4:
        return False
    return SequenceMatcher(None, a, head, autojunk=False).ratio() >= 0.85


def collapse_prefixes(paragraphs: list[str]) -> tuple[list[str], int]:
    """Drop every paragraph that the next one repeats and extends; returns the rest and the
    number dropped."""
    out: list[str] = []
    dropped = 0
    for p in paragraphs:
        while out and is_growing_prefix(out[-1], p):
            out.pop()
            dropped += 1
        out.append(p)
    return out, dropped


def is_tool_status(text: str) -> bool:
    """A short "Checking current numbers." line an assistant says before a lookup."""
    return len(text) <= 80 and bool(_TOOL_STATUS.match(text)) and not _DISFLUENCY.search(text)


def user_score(text: str) -> float:
    """Evidence (log-odds) that a paragraph is the user's speech rather than the assistant's
    prose: disfluencies, stutters, conversational openings, first person and questions to the
    assistant for the user; em dashes, Markdown, length, figures and "you/your" for the
    assistant."""
    n = len(text)
    s = 0.0
    fillers = len(_DISFLUENCY.findall(text))
    s += min(3.0 * fillers, 7.5)
    s += min(1.5 * len(_STUTTER.findall(text)), 3.0)
    if _USER_OPENING.match(text):
        s += 1.0
    s += min(0.35 * len(_FIRST_PERSON.findall(text)), 2.0)
    s += min(0.8 * len(_ASKS_ASSISTANT.findall(text)), 1.6)
    if is_tool_status(text):
        s -= 6.0
    s -= min(1.4 * text.count("—"), 4.2)
    if _MARKDOWN.search(text):
        s -= 2.5
    s -= min(0.4 * len(_SECOND_PERSON.findall(text)), 2.0)
    s -= min(0.5 * len(_NUMBERS.findall(text)), 2.0)
    s -= min(0.6 * text.count(";"), 1.2)
    if n > 300 and not fillers:
        s -= 1.5 + min((n - 300) / 400, 2.0)
    return s


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(x, 30.0), -30.0)))


def assign_roles(paragraphs: list[str]) -> list[tuple[Role, float]]:
    """``(role, posterior probability of that role)`` per paragraph (forward-backward over a
    two-state chain whose emissions come from :func:`user_score`)."""
    if not paragraphs:
        return []
    states: tuple[Role, Role] = ("user", "assistant")
    emit = []
    for p in paragraphs:
        pu = min(max(_sigmoid(user_score(p)), 1e-4), 1 - 1e-4)
        emit.append((pu, 1 - pu))

    def trans(a: int, b: int) -> float:
        stay = STAY[states[a]]
        return stay if a == b else 1 - stay

    n = len(paragraphs)
    fwd = [[0.0, 0.0] for _ in range(n)]
    fwd[0] = [USER_START * emit[0][0], (1 - USER_START) * emit[0][1]]
    for t in range(1, n):
        for b in range(2):
            fwd[t][b] = emit[t][b] * sum(fwd[t - 1][a] * trans(a, b) for a in range(2))
        total = sum(fwd[t]) or 1.0
        fwd[t] = [v / total for v in fwd[t]]
    bwd = [[1.0, 1.0] for _ in range(n)]
    for t in range(n - 2, -1, -1):
        for a in range(2):
            bwd[t][a] = sum(trans(a, b) * emit[t + 1][b] * bwd[t + 1][b] for b in range(2))
        total = sum(bwd[t]) or 1.0
        bwd[t] = [v / total for v in bwd[t]]
    out: list[tuple[Role, float]] = []
    for t in range(n):
        post = [fwd[t][k] * bwd[t][k] for k in range(2)]
        total = sum(post) or 1.0
        pu = post[0] / total
        out.append(("user", pu) if pu >= 0.5 else ("assistant", 1 - pu))
    return out


def split_paragraphs(text: str) -> list[str]:
    """Blank-line separated paragraphs, without export chrome. A fenced code block stays in
    one paragraph even if it contains blank lines."""
    paragraphs: list[str] = []
    current: list[str] = []
    fenced = False
    for line in text.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
        if not line.strip() and not fenced:
            if current:
                paragraphs.append("\n".join(current).strip())
                current = []
            continue
        current.append(line.rstrip())
    if current:
        paragraphs.append("\n".join(current).strip())
    return [p for p in paragraphs if p and not CHROME.match(p)]


def parse_unlabelled(text: str, filename: str) -> ImportedConversation:
    lines = text.splitlines()
    title = find_title(lines)
    paragraphs = split_paragraphs(text)
    if title is not None and paragraphs and paragraphs[0].lstrip("# ").strip() == title:
        paragraphs = paragraphs[1:]
    paragraphs, dropped = collapse_prefixes(paragraphs)
    if not paragraphs:
        raise unreadable("No text was found in that file.")
    roles = assign_roles(paragraphs)
    turns: list[ImportedTurn] = []
    pending: tuple[str, float] | None = None  # a tool-status line waiting for its answer
    for p, (role, conf) in zip(paragraphs, roles, strict=True):
        if role == "assistant" and is_tool_status(p) and pending is None:
            pending = (p, conf)
            continue
        if pending is not None:
            if role == "assistant":
                p, conf = pending[0] + "\n\n" + p, min(conf, pending[1])
            else:
                turns.append(ImportedTurn("", "assistant", pending[0], confidence=pending[1]))
            pending = None
        turns.append(ImportedTurn("", role, p, confidence=round(conf, 3)))
    if pending is not None:
        turns.append(ImportedTurn("", "assistant", pending[0], confidence=pending[1]))
    warnings = []
    if dropped:
        copies = "copy of a message was" if dropped == 1 else "copies of messages were"
        warnings.append(f"{dropped} partial {copies} dropped (repeats left by speech-to-text).")
    warnings.append(
        "The file does not say who said what, so the speakers were guessed. Check the "
        "highlighted turns before continuing."
    )
    return ImportedConversation(turns, title, None, "chat-unlabelled", warnings)
