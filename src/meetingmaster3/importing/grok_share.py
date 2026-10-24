"""Grok share links (Phase 15l, spec R32): the link → its share id, and the share's JSON → an
:class:`ImportedConversation` (pure, no I/O; :mod:`meetingmaster3.importing.fetch` downloads it).

A share link (``https://x.com/i/grok/share/<id>``, ``https://grok.com/share/<id>``) is only
ever reduced to its id: the app builds the one request URL itself (no generic URL fetcher, so
no SSRF surface). The JSON (``GET https://grok.com/rest/app-chat/share_links/<id>``, an
undocumented endpoint) has ``responses`` (each with ``responseId``, ``parentResponseId``,
``sender``, ``message``, ``createTime``, ``partial``) and ``conversation`` (``title``,
``createTime``). Every message carries its sender and time, so speakers are exact and the
transcript is timed from the first message (ADR-0052, Phase 15l implementation).
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from meetingmaster3.errors import MM3Error
from meetingmaster3.importing.chat import is_growing_prefix
from meetingmaster3.importing.model import ImportedConversation, ImportedTurn, Role

FORMAT_ID = "grok-share"
ASSISTANT_NAME = "Grok"
E_IMPORT_URL_UNSUPPORTED = "E_IMPORT_URL_UNSUPPORTED"
MARKDOWN_HINT = (
    "Paste a Grok share link (https://x.com/i/grok/share/… or https://grok.com/share/…), or "
    "export the conversation to Markdown and upload the file instead."
)

HOSTS = {
    "x.com": "/i/grok/share/",
    "www.x.com": "/i/grok/share/",
    "twitter.com": "/i/grok/share/",
    "www.twitter.com": "/i/grok/share/",
    "grok.com": "/share/",
    "www.grok.com": "/share/",
}
"""Accepted hosts (exact, ASCII, lower case) and the path before the share id."""
SHARE_ID = re.compile(r"[A-Za-z0-9_-]{8,200}")
MAX_LINK = 2048
_LINK = re.compile(
    r"\A(?:(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://)?(?P<host>[^/?#]*)(?P<path>[^?#]*)"
    r"(?:\?[^#]*)?(?:#.*)?\Z",
    re.S,
)


def unsupported_link(reason: str = "That is not a Grok share link.") -> MM3Error:
    return MM3Error(E_IMPORT_URL_UNSUPPORTED, reason, MARKDOWN_HINT, status_code=422)


def parse_share_url(text: str) -> str:
    """The share id of a Grok share link. Anything else raises ``E_IMPORT_URL_UNSUPPORTED``
    without any network request: other hosts, ``http://``, user info, ports, other paths,
    encoded characters, an id outside ``[A-Za-z0-9_-]{8,200}``. A query or fragment is dropped."""
    link = (text or "").strip()
    if link.startswith("<") and link.endswith(">"):
        link = link[1:-1].strip()
    if not link or len(link) > MAX_LINK or any(c.isspace() or c == "\\" for c in link):
        raise unsupported_link()
    m = _LINK.match(link)
    if m is None:  # pragma: no cover - the pattern matches any string without whitespace
        raise unsupported_link()
    scheme = (m["scheme"] or "https").lower()
    if scheme != "https":
        raise unsupported_link("Only https:// Grok share links can be imported.")
    host = m["host"]
    if "@" in host or ":" in host:
        raise unsupported_link("That link has a user name or a port; paste the plain share link.")
    prefix = HOSTS.get(host.lower()) if host.isascii() else None
    if prefix is None:
        raise unsupported_link(
            "Only Grok share links (x.com, twitter.com or grok.com) can be imported."
        )
    path = m["path"]
    if not path.startswith(prefix):
        raise unsupported_link()
    share_id = path[len(prefix) :].removesuffix("/")
    if not SHARE_ID.fullmatch(share_id):
        raise unsupported_link("That Grok share link does not end in a valid share id.")
    return share_id


def looks_like_share_url(text: str) -> bool:
    """Whether ``text`` is meant as a link (for ``mm3 import``: a link, not a file name)."""
    t = text.strip().lower()
    return t.startswith(("https://", "http://", "<http")) or any(
        t.startswith(h + p) for h, p in HOSTS.items()
    )


# -- the share's JSON ----------------------------------------------------------------------------


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    response_id: str = Field(alias="responseId")
    parent_response_id: str | None = Field(default=None, alias="parentResponseId")
    sender: str = ""
    message: str | None = ""
    create_time: dt.datetime | None = Field(default=None, alias="createTime")
    partial: bool | None = False


class _Conversation(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    title: str | None = None
    create_time: dt.datetime | None = Field(default=None, alias="createTime")


class _Share(BaseModel):
    model_config = ConfigDict(extra="ignore")

    responses: list[_Response]
    conversation: _Conversation | None = None


SENDER_ROLES: dict[str, Role] = {"human": "user", "user": "user", "assistant": "assistant"}
GENERIC_TITLES = frozenset(
    {
        "",
        "chat",
        "conversation",
        "discussion",
        "discussion request",
        "grok",
        "grok conversation",
        "new chat",
        "new conversation",
        "untitled",
        "voice chat",
        "voice conversation",
    }
)
"""Titles Grok gives a conversation that say nothing about it (the first user sentence wins)."""
TITLE_WORDS = 10
_OPENING = re.compile(
    r"^(?:(?:um+|uh+|erm+|so|okay|ok|well|hey|hi|hello|grok|and|yeah|alright|right)\b[\s,.!-]*)+",
    re.I,
)
_SENTENCE = re.compile(r"(?<=[.!?])\s")


def unavailable(message: str) -> MM3Error:
    """Grok answered, but not with a share we can read (the endpoint is undocumented)."""
    return MM3Error(
        "E_IMPORT_SHARE_UNAVAILABLE",
        message,
        "Grok may have changed how share links work. Export the conversation to Markdown and "
        "upload the file instead.",
        status_code=502,
    )


def is_share_json(text: str) -> bool:
    """A Grok share's JSON (for detection: ``{"responses": [{"sender": …}, …], …}``)."""
    if not text.lstrip().startswith("{"):
        return False
    try:
        data = json.loads(text)
    except ValueError:
        return False
    responses = data.get("responses") if isinstance(data, dict) else None
    return (
        isinstance(responses, list)
        and bool(responses)
        and all(isinstance(r, dict) and "sender" in r for r in responses[:20])
    )


def _thread(responses: list[_Response]) -> tuple[list[_Response], int]:
    """The conversation as shown: from the root along ``parentResponseId``, taking the latest
    child where there are several (regenerated answers, edited messages). Returns the thread and
    the number of skipped alternatives. A share without parent links (or with only a cycle) is
    read in time order."""
    order = {r.response_id: i for i, r in enumerate(responses)}

    def key(r: _Response) -> tuple[float, int]:
        stamp = r.create_time.timestamp() if r.create_time else float("-inf")
        return stamp, order[r.response_id]

    roots = [r for r in responses if r.parent_response_id not in order]
    if not roots or len(roots) == len(responses):
        return sorted(responses, key=key), 0
    children: dict[str, list[_Response]] = {}
    for r in responses:
        if r.parent_response_id in order:
            children.setdefault(r.parent_response_id or "", []).append(r)
    skipped = len(roots) - 1
    node: _Response | None = max(roots, key=key)
    thread: list[_Response] = []
    seen: set[str] = set()
    while node is not None and node.response_id not in seen:
        seen.add(node.response_id)
        thread.append(node)
        kids = children.get(node.response_id, [])
        skipped += max(0, len(kids) - 1)
        node = max(kids, key=key) if kids else None
    return thread, skipped


def _seconds(t: dt.datetime, t0: dt.datetime) -> float:
    if (t.tzinfo is None) != (t0.tzinfo is None):
        t, t0 = t.replace(tzinfo=None), t0.replace(tzinfo=None)
    return max(0.0, round((t - t0).total_seconds(), 3))


def title_from(text: str) -> str | None:
    """A short title from the user's first message: its first sentence, without the opening
    fillers and greetings, cut to about ten words."""
    first = _SENTENCE.split(" ".join(text.split()), maxsplit=1)[0]
    first = _OPENING.sub("", first).strip(" ,.!?-")
    words = first.split()
    if not words:
        return None
    short = " ".join(words[:TITLE_WORDS]).rstrip(",;:")
    if len(words) > TITLE_WORDS:
        short += "…"
    return short[0].upper() + short[1:]


def _local(t: dt.datetime | None) -> dt.datetime | None:
    if t is None:
        return None
    return t.astimezone() if t.tzinfo is not None else t


def parse_share_data(data: Any) -> ImportedConversation:
    """The share's decoded JSON → conversation. Raises ``E_IMPORT_SHARE_UNAVAILABLE`` for a
    different shape."""
    try:
        share = _Share.model_validate(data)
    except ValidationError as exc:
        raise unavailable("Grok's answer is not a conversation MeetingMaster3 can read.") from exc
    warnings: list[str] = []
    thread, skipped = _thread(share.responses)
    if skipped:
        warnings.append(
            f"Skipped {skipped} alternative {'reply' if skipped == 1 else 'replies'} (regenerated "
            "answers or edited messages); the latest version of each was kept."
        )
    kept: list[tuple[_Response, Role]] = []
    partial = unknown = 0
    for r in thread:
        role = SENDER_ROLES.get(r.sender.strip().lower())
        if r.partial:
            partial += 1
        elif role is None:
            unknown += 1
        elif (r.message or "").strip():
            kept.append((r, role))
    if partial:
        warnings.append(f"Skipped {partial} unfinished {'reply' if partial == 1 else 'replies'}.")
    if unknown:
        warnings.append(f"Skipped {unknown} message(s) from an unknown sender.")
    timed = bool(kept) and all(r.create_time is not None for r, _ in kept)
    if kept and not timed:
        warnings.append("Some messages have no time, so the transcript has no timestamps.")
    t0 = kept[0][0].create_time if timed else None
    turns: list[ImportedTurn] = []
    merged = 0
    for r, role in kept:
        text = (r.message or "").strip()
        start = _seconds(r.create_time, t0) if t0 is not None and r.create_time else None
        if turns and start is not None and turns[-1].start is not None:
            start = max(start, turns[-1].start)
        prev = turns[-1] if turns else None
        if prev is not None and role == "user" == prev.role and is_growing_prefix(prev.text, text):
            # Voice mode repeats an utterance as it grows: keep the full text at the time of the
            # first copy, when the person started speaking.
            turns[-1] = ImportedTurn("", "user", text, prev.start)
            merged += 1
            continue
        turns.append(ImportedTurn(ASSISTANT_NAME if role == "assistant" else "", role, text, start))
    if merged:
        warnings.append(f"Merged {merged} repeated partial voice transcription(s).")
    if timed:
        turns = [
            ImportedTurn(t.speaker, t.role, t.text, t.start, nxt.start)
            for t, nxt in itertools.pairwise(turns)
        ] + turns[-1:]
    conv = share.conversation or _Conversation()
    title = (conv.title or "").strip()
    if " ".join(title.casefold().split()) in GENERIC_TITLES:
        first_user = next((t.text for t in turns if t.role == "user"), "")
        title = title_from(first_user) or title
    started = _local(conv.create_time or (kept[0][0].create_time if kept else None))
    return ImportedConversation(turns, title or None, started, FORMAT_ID, warnings)


def parse_share(text: str, filename: str) -> ImportedConversation:
    """Parser interface (``text, filename``): a share's JSON as text."""
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise unavailable("Grok did not answer with a conversation (not JSON).") from exc
    return parse_share_data(data)
