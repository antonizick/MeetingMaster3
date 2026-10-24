"""Decoding and format detection: :func:`detect_and_parse` picks a parser by content.

Order: an MM3 companion (frontmatter plus its data block), WebVTT (``WEBVTT`` header), SubRip
(numbered cues with ``-->`` times), timestamped lines, a labelled AI conversation, and finally
an unlabelled conversation (any other text). The file extension only breaks ties, so a ``.txt``
holding captions or a ``.md`` holding a timestamped transcript is still read correctly.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import yaml

from meetingmaster3.errors import MM3Error
from meetingmaster3.importing import chat, timestamped
from meetingmaster3.importing.model import (
    MAX_TURNS,
    ImportedConversation,
    Parser,
    empty,
    too_large,
    unreadable,
)

DEFAULT_MAX_MB = 10
TIMESTAMPED_SHARE = 0.25
"""A file is a timestamped transcript when at least this share of its lines start a timed cue."""

PARSERS: dict[str, Parser] = {
    "mm3-companion": timestamped.parse_companion,
    "webvtt": timestamped.parse_vtt,
    "srt": timestamped.parse_srt,
    "timestamped-text": timestamped.parse_timestamped,
    "chat-markdown": chat.parse_labelled,
    "chat-unlabelled": chat.parse_unlabelled,
}
"""Parser id → parser. Phase 15l adds the Grok share-link parser beside these."""

_FRONTMATTER = re.compile(r"\A---[ \t]*\n(?P<yaml>.*?)\n---[ \t]*(?:\n|\Z)", re.S)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def decode(data: bytes, *, max_bytes: int | None = None) -> str:
    """UTF-8 text with the BOM removed and newlines normalised. Binary or oversize input raises
    ``E_IMPORT_UNREADABLE`` / ``E_IMPORT_TOO_LARGE``."""
    limit = max_bytes if max_bytes is not None else DEFAULT_MAX_MB * 1024 * 1024
    if len(data) > limit:
        raise too_large(max(1, limit // (1024 * 1024)))
    if b"\x00" in data:
        raise unreadable("That file is not text (it looks like a binary or audio file).")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise unreadable(
            "That file is not UTF-8 text.",
            "Save it as UTF-8 (most editors offer this under Save As > Encoding) and try again.",
        ) from exc
    text = text.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n")
    if text and len(_CONTROL.findall(text)) > max(8, len(text) // 200):
        raise unreadable("That file is not readable text.")
    if not text.strip():
        raise empty()
    return text


def _front_matter(text: str) -> tuple[dict[str, Any], str]:
    """A leading YAML block (an Obsidian clipping, a note) and the text after it."""
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    try:
        data = yaml.safe_load(m["yaml"])
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return data, text[m.end() :]


def _meta_date(meta: dict[str, Any]) -> dt.datetime | None:
    for key in ("date", "created", "created_at", "exported", "time"):
        value = meta.get(key)
        if isinstance(value, dt.datetime):
            return value
        if isinstance(value, dt.date):
            return dt.datetime.combine(value, dt.time(0))
        if isinstance(value, str):
            try:
                return dt.datetime.fromisoformat(value.strip())
            except ValueError:
                continue
    return None


def detect(text: str, filename: str = "") -> str:
    """The id of the parser for ``text``."""
    ext = filename.rsplit(".", 1)[-1].casefold() if "." in filename else ""
    if timestamped.is_companion(text):
        return "mm3-companion"
    if timestamped.is_vtt(text):
        return "webvtt"
    srt = timestamped.srt_score(text)
    if srt >= 0.5 or (ext == "srt" and srt > 0):
        return "srt"
    if timestamped.timestamped_score(text) >= TIMESTAMPED_SHARE:
        return "timestamped-text"
    if chat.labelled_score(text) > 0:
        return "chat-markdown"
    return "chat-unlabelled"


def detect_and_parse(
    data: bytes, filename: str = "", *, max_bytes: int | None = None
) -> ImportedConversation:
    """Decode ``data``, pick a parser by content and parse. Raises only :class:`MM3Error`."""
    text = decode(data, max_bytes=max_bytes)
    meta: dict[str, Any] = {}
    body = text
    if not timestamped.is_companion(text):
        meta, body = _front_matter(text)
    source = detect(body, filename)
    try:
        conv = PARSERS[source](text if source == "mm3-companion" else body, filename)
    except MM3Error:
        raise
    except (ValueError, IndexError, KeyError, RecursionError) as exc:  # a parser bug on odd input
        raise unreadable(f"That file could not be read ({type(exc).__name__}).") from exc
    if not conv.turns:
        raise empty()
    if len(conv.turns) > MAX_TURNS:
        raise unreadable(f"That file has more than {MAX_TURNS:,} turns.")
    title = conv.title
    meta_title = meta.get("title")
    if isinstance(meta_title, str) and meta_title.strip():
        title = meta_title.strip()
    started = conv.started_at or _meta_date(meta)
    if title != conv.title or started != conv.started_at:
        conv = ImportedConversation(conv.turns, title, started, conv.source_format, conv.warnings)
    return conv
