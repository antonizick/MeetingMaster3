"""YAML frontmatter: parse, and render while preserving what the user wrote.

Parsing keeps the raw text of every top-level key (including comments that follow it), so a
re-render reuses the original bytes for each key whose value did not change and only re-emits
the keys that did. Unknown keys and their order are therefore preserved exactly. MM3 writes
values in Obsidian's style: flow lists (``tags: [a, b]``), ISO-8601 datetimes, and quoted
wikilinks (``"[[Note]]"``).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Any

import yaml

from meetingmaster3.errors import MM3Error

_OPEN_RE = re.compile(r"---[ \t]*\r?\n")
_CLOSE_RE = re.compile(r"^---[ \t]*(?:\r?\n|$)", re.M)
_NON_PRINTABLE = re.compile(
    r"[^\t\n\r\x20-\x7e\xa0-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]|[\x85\u2028\u2029\ufeff]"
)
_FLOW_UNSAFE = re.compile(r"[,\[\]{}]")
_YAML12_NON_STRING = re.compile(
    r"^(?:[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?|0o[0-7]+|0x[0-9a-fA-F]+"
    r"|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN)|true|True|TRUE|false|False|FALSE|null|Null|NULL|~)$"
)
"""Scalars that YAML 1.2 readers (Obsidian) treat as non-strings even where PyYAML would not."""


class FrontmatterError(MM3Error):
    def __init__(self, message: str):
        super().__init__(
            "frontmatter_invalid",
            f"The note's frontmatter could not be read: {message}.",
            "Fix the YAML between the '---' lines (Obsidian's Properties view shows the problem).",
        )


@dataclass(frozen=True)
class ParsedFrontmatter:
    data: dict[str, Any]
    raw: str
    """The whole block, fences included, exactly as in the file."""
    open_fence: str
    close_fence: str
    prefix: str
    """Lines before the first key (comments, blank lines)."""
    chunks: dict[str, str] | None
    """Raw text per top-level key, or ``None`` if the YAML could not be split safely."""


def split_frontmatter(text: str) -> tuple[ParsedFrontmatter | None, str]:
    """Return ``(frontmatter, body)``. A file without a ``---`` block has no frontmatter."""
    m = _OPEN_RE.match(text)
    if not m:
        return None, text
    close = _CLOSE_RE.search(text, m.end())
    if not close:
        return None, text
    yaml_text = text[m.end() : close.start()]
    try:
        data = yaml.safe_load(yaml_text) if yaml_text.strip() else {}
    except yaml.YAMLError as exc:
        raise FrontmatterError(str(exc).splitlines()[0]) from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise FrontmatterError("it is not a set of 'key: value' properties")
    if not all(isinstance(k, str) for k in data):
        raise FrontmatterError("every property name must be text")
    prefix, chunks = _split_chunks(yaml_text, data)
    fm = ParsedFrontmatter(
        data=data,
        raw=text[: close.end()],
        open_fence=m.group(),
        close_fence=close.group(),
        prefix=prefix,
        chunks=chunks,
    )
    return fm, text[close.end() :]


def _line_start(text: str, index: int) -> int:
    return text.rfind("\n", 0, index) + 1


def _split_chunks(yaml_text: str, data: dict[str, Any]) -> tuple[str, dict[str, str] | None]:
    """Split the YAML into one raw chunk per top-level key, verified by re-parsing each."""
    if not data:
        return yaml_text, {}
    try:
        node = yaml.compose(yaml_text, Loader=yaml.SafeLoader)
    except yaml.YAMLError:  # pragma: no cover - already parsed successfully above
        return "", None
    if not isinstance(node, yaml.MappingNode) or node.flow_style:
        return "", None
    starts = [_line_start(yaml_text, k.start_mark.index) for k, _ in node.value]
    if len(starts) != len(data) or len(set(starts)) != len(starts):
        return "", None  # duplicate keys or several keys on one line
    bounds = [*starts, len(yaml_text)]
    chunks: dict[str, str] = {}
    for key, a, b in zip(data, bounds, bounds[1:], strict=False):
        chunk = yaml_text[a:b]
        try:
            parsed = yaml.safe_load(chunk)
        except yaml.YAMLError:
            return "", None
        if (
            not isinstance(parsed, dict)
            or list(parsed) != [key]
            or not same(parsed[key], data[key])
        ):
            return "", None
        chunks[key] = chunk
    return yaml_text[: starts[0]], chunks


def same(a: Any, b: Any) -> bool:
    """Strict structural equality: types must match too (``True`` is not ``1``) and mapping
    order matters, because either difference changes the YAML text."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return list(a) == list(b) and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    return bool(a == b)


def _double_quoted(s: str) -> str:
    out = json.dumps(s, ensure_ascii=False)
    return _NON_PRINTABLE.sub(lambda m: f"\\u{ord(m.group()):04x}", out)


def _plain_ok(s: str, *, flow: bool) -> bool:
    if not s or s != s.strip() or _NON_PRINTABLE.search(s) or "\n" in s or "\r" in s:
        return False
    if (flow and _FLOW_UNSAFE.search(s)) or _YAML12_NON_STRING.match(s):
        return False
    try:
        loaded = yaml.safe_load(f"k: [{s}]" if flow else f"k: {s}")
    except yaml.YAMLError:
        return False
    expected: Any = [s] if flow else s
    return isinstance(loaded, dict) and same(loaded.get("k"), expected)


def scalar(value: Any, *, flow: bool = False) -> str:
    """One YAML scalar in MM3's style, or raise ``TypeError`` for non-scalars."""
    if value is None:
        return "null" if flow else ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return yaml.safe_dump(value, default_flow_style=True).removesuffix("\n...\n").strip()
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, str):
        if value.startswith("[[") or not _plain_ok(value, flow=flow):
            return _double_quoted(value)
        return value
    raise TypeError(type(value).__name__)


def wikilink(target: str) -> str:
    return f"[[{target}]]"


def parse_wikilink(value: Any) -> str | None:
    """``"[[Target|alias]]"`` or ``"[[Target]]"`` or ``"Target"`` → ``"Target"``."""
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip()
    if v.startswith("[[") and v.endswith("]]"):
        v = v[2:-2].split("|", 1)[0]
    return v.strip() or None


def _emit_mm3_style(key: str, value: Any, newline: str) -> str:
    k = scalar(key)
    if isinstance(value, list):
        if all(not isinstance(v, list | dict) for v in value):
            return f"{k}: [{', '.join(scalar(v, flow=True) for v in value)}]{newline}"
        raise TypeError("nested list")
    if isinstance(value, dict):
        if not value:
            return f"{k}: {{}}{newline}"
        if all(isinstance(sk, str) and not isinstance(sv, list | dict) for sk, sv in value.items()):
            lines = [f"{k}:"] + [
                f"  {scalar(sk)}: {scalar(sv)}".rstrip() for sk, sv in value.items()
            ]
            return newline.join(lines) + newline
        raise TypeError("nested mapping")
    return f"{k}: {scalar(value)}".rstrip() + newline


def _flow(value: Any) -> str:
    """JSON-like YAML flow syntax with every string double-quoted and escaped."""
    if isinstance(value, dict):
        return (
            "{" + ", ".join(f"{_double_quoted(str(k))}: {_flow(v)}" for k, v in value.items()) + "}"
        )
    if isinstance(value, list):
        return "[" + ", ".join(_flow(v) for v in value) + "]"
    if isinstance(value, str):
        return _double_quoted(value)
    return scalar(value, flow=True)


def emit_key(key: str, value: Any, newline: str = "\n") -> str:
    """Render one top-level property. Falls back to PyYAML for shapes MM3's emitter does not
    handle, and verifies the result parses back to the same value."""
    candidates: list[str] = []
    with contextlib.suppress(TypeError):
        candidates.append(_emit_mm3_style(key, value, newline))
    dumped = yaml.safe_dump(
        {key: value}, allow_unicode=True, default_flow_style=False, sort_keys=False, width=1000
    )
    candidates.append(dumped.replace("\n", newline))
    with contextlib.suppress(TypeError):
        candidates.append(f"{_double_quoted(key)}: {_flow(value)}{newline}")
    for text in candidates:
        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if isinstance(loaded, dict) and list(loaded) == [key] and same(loaded[key], value):
            return text
    raise MM3Error(  # pragma: no cover - PyYAML round-trips every safe_load-able value
        "frontmatter_unrepresentable",
        f"The property {key!r} cannot be written as YAML.",
        "Simplify the property value.",
    )


def render_frontmatter(
    data: dict[str, Any], *, newline: str = "\n", base: ParsedFrontmatter | None = None
) -> str:
    """Render ``data`` (in its key order) as a frontmatter block.

    With ``base``, the original block is returned verbatim when nothing changed, and otherwise
    every key whose value is unchanged keeps its original raw text (comments included).
    """
    if base is not None and list(data) == list(base.data) and same(data, base.data):
        return base.raw
    if base is not None and base.chunks is not None:
        out = base.open_fence + base.prefix
        for key, value in data.items():
            if key in base.data and same(value, base.data[key]):
                chunk = base.chunks[key]
                out += chunk if chunk.endswith("\n") else chunk + newline
            else:
                out += emit_key(key, value, newline)
        close = base.close_fence if base.close_fence.endswith("\n") else base.close_fence + newline
        return out + close
    return (
        "---"
        + newline
        + "".join(emit_key(k, v, newline) for k, v in data.items())
        + "---"
        + newline
    )
