"""Hypothesis strategies for notes, sections and transcripts."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from hypothesis import assume
from hypothesis import strategies as st
from pydantic import ValidationError

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.note import LOOSE_MARKER_RE, NOTE_KEYS, Note, Section, TextBlock
from meetingmaster3.domain.transcript import (
    CompanionTranscript,
    Segment,
    SpeakerMap,
    Transcript,
    Word,
)

# Text that stresses the formats: unicode, CR/LF mixes, Markdown and YAML syntax.
_SPECIALS = [
    "\n",
    "\r\n",
    "\r",
    "\n\n",
    "  ",
    "\t",
    "---",
    "...",
    "# Heading",
    "## Sub",
    "- item",
    "- **Tags:** #x",
    "<!-- comment -->",
    "-->",
    "[[Link]]",
    "key: value",
    "#tag",
    "> quote",
    "```",
    "~~~",
    "|",
    "*",
    "\u2028",
    "\x85",
    "\ufeff",
    "é",
    "日本語",
    "🙂",
    "%%",
    "\x00",
]
_chunk = st.one_of(st.text(max_size=12), st.sampled_from(_SPECIALS))
raw_text = st.lists(_chunk, max_size=8).map("".join)
"""Arbitrary text with a bias toward the characters that break naive parsers."""


def _no_markers(text: str) -> bool:
    return LOOSE_MARKER_RE.search(text) is None


user_text = raw_text.filter(_no_markers)
line_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters="\r\n"), max_size=30
)

section_ids = st.from_regex(r"\A[a-z0-9][a-z0-9-]{0,15}\Z")


@st.composite
def sections(draw: st.DrawFn, section_id: str | None = None) -> Section:
    sid = section_id or draw(section_ids)
    title = draw(line_text)
    body = draw(user_text)
    try:
        return Section(id=sid, title=title, body_markdown=body)
    except ValidationError:
        assume(False)
        raise  # pragma: no cover


names = line_text.filter(lambda s: s.split() != [])
datetimes = st.datetimes(
    min_value=dt.datetime(1990, 1, 1),
    max_value=dt.datetime(2099, 12, 31),
    timezones=st.one_of(
        st.none(),
        st.just(dt.UTC),
        st.integers(-12 * 60, 14 * 60).map(lambda m: dt.timezone(dt.timedelta(minutes=m))),
    ),
)
labels = st.from_regex(r"\ASPEAKER_[0-9]{2}\Z") | st.from_regex(r"\A[A-Za-z0-9_-]{1,10}\Z")
speaker_maps = st.dictionaries(labels, names, max_size=4).map(lambda d: SpeakerMap(names=d))
optional_line = st.none() | line_text
link_targets = st.none() | line_text.filter(lambda s: not any(c in s for c in "[]|"))


@st.composite
def metas(draw: st.DrawFn) -> MeetingMeta:
    return MeetingMeta(
        id=draw(st.uuids(version=4)),
        title=draw(line_text),
        date=draw(st.none() | datetimes),
        participants=draw(st.lists(line_text, max_size=4)),
        tags=draw(st.lists(line_text, max_size=4)),
        location=draw(optional_line),
        template_id=draw(optional_line),
        backend=draw(optional_line),
        model=draw(optional_line),
        generated_at=draw(st.none() | datetimes),
        audio_ref=draw(link_targets),
        transcript_ref=draw(link_targets),
        speakers=draw(speaker_maps),
    )


yaml_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False),
    st.text(max_size=20),
    st.sampled_from(["yes", "No", "null", "~", "1.0", "0o17", "[[x]]", "a: b", "#c", "- d"]),
    st.dates(),
)
yaml_values: st.SearchStrategy[Any] = st.recursive(
    yaml_scalars,
    lambda inner: (
        st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=8), inner, max_size=3)
    ),
    max_leaves=8,
)
extra_keys = st.text(min_size=1, max_size=12).filter(lambda k: k not in NOTE_KEYS)


@st.composite
def notes(draw: st.DrawFn) -> Note:
    ids = draw(st.lists(section_ids, unique=True, max_size=4))
    blocks: list[TextBlock | Section] = [TextBlock(text=draw(user_text))]
    for sid in ids:
        blocks.append(draw(sections(sid)))
        blocks.append(TextBlock(text=draw(user_text)))
    return Note(
        meta=draw(metas()),
        extra_properties=draw(st.dictionaries(extra_keys, yaml_values, max_size=3)),
        format_version=draw(st.integers(1, 3)),
        blocks=blocks,
        newline=draw(st.sampled_from(["\n", "\r\n"])),
    )


finite = st.floats(min_value=0, max_value=1e6, allow_nan=False, allow_infinity=False)


@st.composite
def transcripts(draw: st.DrawFn) -> Transcript:
    diarized = draw(st.booleans())
    n = draw(st.integers(0, 6))
    segs = []
    for i in range(n):
        start = draw(finite)
        segs.append(
            Segment(
                id=i,
                start=start,
                end=start + draw(finite),
                speaker_label=draw(labels) if diarized else None,
                text=draw(raw_text),
                words=draw(
                    st.lists(
                        st.builds(
                            Word,
                            start=st.none() | finite,
                            end=st.none() | finite,
                            text=raw_text,
                            score=st.none() | st.floats(0, 1),
                        ),
                        max_size=3,
                    )
                ),
            )
        )
    return Transcript(
        segments=segs,
        language=draw(st.none() | st.sampled_from(["en", "de", "fr"])),
        duration=draw(st.none() | finite),
        model=draw(optional_line),
        diarized=diarized,
    )


@st.composite
def companions(draw: st.DrawFn) -> CompanionTranscript:
    return CompanionTranscript(
        meeting_id=uuid.UUID(int=draw(st.integers(0, 2**128 - 1))),
        title=draw(line_text),
        note_ref=draw(link_targets),
        transcript=draw(transcripts()),
        speakers=draw(speaker_maps),
        extra_properties=draw(
            st.dictionaries(
                st.text(min_size=1, max_size=8).filter(
                    lambda k: not k.startswith("mm3") and k not in ("duration", "language")
                ),
                yaml_values,
                max_size=2,
            )
        ),
        newline=draw(st.sampled_from(["\n", "\r\n"])),
    )
