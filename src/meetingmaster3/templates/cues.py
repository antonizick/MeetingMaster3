"""Task cues: commitment, request and suggestion sentences found in a transcript (pure).

Small local models miss tasks in long transcripts and tend to make whoever said "we should..."
the owner of the task. Two deterministic aids address that (ADR-0017):

* :func:`task_cues` finds candidate sentences, tagged by kind, which the prompt of every task
  section lists for the model to check;
* :func:`guard_owners` checks the model's owners afterwards: a task whose named owner only
  *suggested* or *declined* it, and never committed to it or was asked to do it, becomes
  **Unassigned**. It never assigns anyone and never touches an owner with supporting evidence.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from meetingmaster3.llm.budget import Turn

CueKind = Literal["commits", "asks", "suggests", "declines"]

KIND_LABELS: dict[CueKind, str] = {
    "commits": "commits to it",
    "asks": "asks someone",
    "suggests": "suggestion: no owner unless someone takes it on",
    "declines": "declines: not the owner",
}

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_COMMIT_RE = re.compile(
    r"\b(i'll|i will|i'm going to|i am going to|i can (?:do|take|have|send|look|get)|"
    r"i'm on it|will do)\b",
    re.I,
)
_ASK_RE = re.compile(r"\b(can you|could you|would you|will you|please)\b", re.I)
_SUGGEST_RE = re.compile(
    r"\b(we should|we need to|we must|someone should|somebody should|needs to|"
    r"needs? to be|has to be|let's make sure|find an owner|take (?:it|that) offline)\b",
    re.I,
)
_NEGATION_RE = re.compile(r"\b(not|cannot|can't|won't|don't|doesn't|isn't|never)\b", re.I)
MAX_TASK_CUES = 60


@dataclass(frozen=True)
class Cue:
    speaker: str
    kind: CueKind
    sentence: str
    stamp: str = ""
    """``[mm:ss]`` (empty when the turn has no time)."""

    def render(self) -> str:
        prefix = f"{self.stamp} " if self.stamp else ""
        return f"{prefix}{self.speaker} ({KIND_LABELS[self.kind]}): {self.sentence}"


def classify(sentence: str) -> CueKind | None:
    negated = bool(_NEGATION_RE.search(sentence))
    if _COMMIT_RE.search(sentence):
        return "declines" if negated else "commits"
    if _ASK_RE.search(sentence):
        return "asks"
    if _SUGGEST_RE.search(sentence):
        return "suggests"
    return None


def task_cues(turns: Sequence[Turn], stamp: object = None) -> list[Cue]:
    """Candidate task sentences, in transcript order (at most :data:`MAX_TASK_CUES`).
    ``stamp(turn)`` formats a turn's time (default: none)."""
    out: list[Cue] = []
    for t in turns:
        for sentence in _SENTENCE_RE.split(t.text):
            kind = classify(sentence)
            if kind is not None:
                text = stamp(t) if callable(stamp) else ""
                out.append(Cue(t.speaker, kind, sentence.strip(), str(text)))
    return out[:MAX_TASK_CUES]


_FOLLOW_UP_RE = re.compile(
    r"\b(send|sending|sent|email|e-mail|mail|share|forward|schedule|book|set up|setup|"
    r"follow up|follow-up|get back|reach out|call|text|ping|sync|meet|review|check|look into|"
    r"find out|prepare|draft|write|update|finali[sz]e|post|publish|submit|confirm|decide|"
    r"approve|order|buy|fix|deploy|test|investigate|organi[sz]e|arrange|invite|introduce|"
    r"connect|put together|pull together|compile|get (?:you|him|her|them|it|that) |"
    r"let (?:you|him|her|them) know|keep (?:you|him|her|them) (?:posted|updated|"
    r"informed|in the loop))\b",
    re.I,
)


def follow_up_cues(cues: Sequence[Cue]) -> list[Cue]:
    """The candidates that name follow-up work (send, schedule, review...), for templates whose
    meetings are informal conversations (``params.task_candidates: relevant``, ADR-0039): there,
    most "I'll ..." sentences are conversation ("I'll put it that way") and only these are
    worth showing to the model."""
    return [c for c in cues if _FOLLOW_UP_RE.search(c.sentence)]


# -- owner guard ------------------------------------------------------------------------------

_OWNER_RE = re.compile(r"^(?P<pre>- \[[ xX]\] \*\*)(?P<owner>[^*:\n]{1,80})(?P<post>:\*\*)")
_WORD_RE = re.compile(r"[a-z][a-z'-]{3,}")
# fmt: off
_STOP = frozenset((
    "about", "after", "also", "before", "could", "from", "have", "into", "just", "like", "make",
    "need", "needs", "really", "should", "some", "someone", "somebody", "something", "than",
    "that", "their", "them", "then", "there", "they", "this", "though", "will", "with", "would",
    "your", "yours", "what", "when", "where", "which", "while", "able", "sure", "yeah", "okay",
))
# fmt: on
OVERLAP = 0.25
UNASSIGNED = "Unassigned"


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in _WORD_RE.findall(text.casefold()) if w not in _STOP}


def _overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _same_person(owner: str, speaker: str) -> bool:
    o, s = owner.casefold().strip(), speaker.casefold().strip()
    return o == s or o == s.split()[0] or s == o.split()[0]


def _mentions(sentence: str, person: str) -> bool:
    first = person.split()[0]
    return bool(re.search(rf"\b{re.escape(first)}\b", sentence, re.I))


def guard_owners(body: str, cues: Sequence[Cue]) -> tuple[str, list[str]]:
    """Unassign tasks whose owner only suggested or declined them. Returns the new body and the
    task lines that were changed."""
    changed: list[str] = []
    lines = body.split("\n")
    for i, line in enumerate(lines):
        m = _OWNER_RE.match(line)
        if not m or m.group("owner").strip().casefold() == UNASSIGNED.casefold():
            continue
        owner = m.group("owner").strip()
        task = _words(line[m.end() :])
        supported = any(
            _overlap(task, _words(c.sentence)) >= OVERLAP
            and (
                (c.kind == "commits" and _same_person(owner, c.speaker))
                or (c.kind == "asks" and _mentions(c.sentence, owner))
            )
            for c in cues
        )
        if supported:
            continue
        contradicted = any(
            c.kind in ("suggests", "declines")
            and _same_person(owner, c.speaker)
            and _overlap(task, _words(c.sentence)) >= OVERLAP
            for c in cues
        )
        if contradicted:
            lines[i] = f"{m.group('pre')}{UNASSIGNED}{m.group('post')}{line[m.end() :]}"
            changed.append(line)
    return "\n".join(lines), changed
