"""Find and rewrite links to renamed files across the vault (Phase 15d, ADR-0040).

Used when a meeting is renamed or re-dated: every other note that links to one of the meeting's
files (the note, its companion and readable transcripts, the vault audio copy) gets its links
re-pointed, the way Obsidian does when a file is renamed inside it.

Recognised forms, anywhere in the file (frontmatter included), except inside fenced code blocks
and inline code:

* wikilinks ``[[stem]]``, ``[[stem|alias]]``, ``[[stem#heading]]``, ``[[stem#^block]]``, embeds
  ``![[stem]]``, path-qualified ``[[folder/stem]]``, an explicit ``.md``, and ``\\|`` in tables;
* Markdown links ``[text](folder/stem.md)``, ``[text](<folder/stem.md>)`` and
  ``[text](folder/stem%20x.md#heading "title")``, relative to the linking note or to the vault.

Resolution follows Obsidian: a bare name resolves by file name across the vault (case-insensitive);
when several files share the name, the one in the linking note's folder wins, and otherwise the
link is ambiguous and left alone (with a warning). A path-qualified link resolves by path. A
rewritten link changes only its target; alias, heading, block, embed mark and every other byte
are kept. If the new name is not unique in the vault, the rewritten link is path-qualified so it
cannot resolve to the wrong file.

The scan is bounded (:data:`MAX_FILES`, :data:`MAX_FILE_BYTES`) and does blocking I/O: call it
from a worker thread.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote

from meetingmaster3.markdown.frontmatter import FrontmatterError, split_frontmatter
from meetingmaster3.vault.io import read_text
from meetingmaster3.vault.naming import NOTE_SUFFIX
from meetingmaster3.vault.paths import is_inside

MAX_FILES = 20_000
"""Markdown files examined per scan; the rest are skipped with a warning."""
MAX_FILE_BYTES = 2 * 1024 * 1024
"""Larger Markdown files are not scanned (warning): real notes are far smaller."""

_WIKI_RE = re.compile(
    r"(?P<embed>!?)\[\[(?P<target>[^\[\]|#^\n]*?)(?P<esc>\\?)(?P<rest>(?:#[^\[\]|\n]*)?(?:\\?\|[^\[\]\n]*)?)\]\]"
)
_MD_RE = re.compile(
    r"(?P<embed>!?)\[(?P<text>[^\]\n]*)\]\((?P<ws>[ \t]*)"
    r"(?P<url><[^<>\n]+>|(?:[^()\s]|\([^()\s]*\))+)"
    r"(?P<title>[ \t]+(?:\"[^\"\n]*\"|'[^'\n]*'))?[ \t]*\)"
)
_FENCE_RE = re.compile(r"^[ ]{0,3}(?P<fence>`{3,}|~{3,})", re.M)
_INLINE_CODE_RE = re.compile(r"(?<!`)(?P<ticks>`+)(?!`).+?(?<!`)(?P=ticks)(?!`)", re.S)
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_PCT_SAFE = "/()-_.~!*'"


def _key(name: str) -> str:
    return name.casefold()


def _link_name(rel: str) -> str:
    """How a wikilink names the file at vault-relative ``rel``: Markdown files without
    ``.md``, other files (audio) with their extension."""
    base = posixpath.basename(rel)
    return base.removesuffix(NOTE_SUFFIX) if base.lower().endswith(NOTE_SUFFIX) else base


def _link_path(rel: str) -> str:
    return rel.removesuffix(NOTE_SUFFIX) if rel.lower().endswith(NOTE_SUFFIX) else rel


@dataclass
class VaultIndex:
    """Every file of the vault by link name and by link path (both case-folded)."""

    by_name: dict[str, list[str]] = field(default_factory=dict)
    by_path: dict[str, str] = field(default_factory=dict)

    def add(self, rel: str) -> None:
        self.by_name.setdefault(_key(_link_name(rel)), []).append(rel)
        self.by_path[_key(_link_path(rel))] = rel

    def remove(self, rel: str) -> None:
        names = self.by_name.get(_key(_link_name(rel)), [])
        if rel in names:
            names.remove(rel)
        if self.by_path.get(_key(_link_path(rel))) == rel:
            del self.by_path[_key(_link_path(rel))]

    def named(self, rel: str) -> list[str]:
        return list(self.by_name.get(_key(_link_name(rel)), []))

    def resolve_wiki(self, target: str, source_rel: str) -> tuple[str | None, bool]:
        """``(file, ambiguous)`` for a wikilink target written in ``source_rel``."""
        t = target.strip().lstrip("/")
        if not t:
            return None, False
        key = _key(t.removesuffix(NOTE_SUFFIX) if t.lower().endswith(NOTE_SUFFIX) else t)
        if "/" in t:
            if key in self.by_path:
                return self.by_path[key], False
            local = posixpath.normpath(posixpath.join(posixpath.dirname(source_rel), key))
            if local in self.by_path:
                return self.by_path[local], False
            hits = [rel for k, rel in self.by_path.items() if k.endswith("/" + key)]
            return (hits[0], False) if len(hits) == 1 else (None, len(hits) > 1)
        hits = self.by_name.get(key, [])
        if len(hits) == 1:
            return hits[0], False
        if not hits:
            return None, False
        folder = posixpath.dirname(source_rel)
        near = [h for h in hits if posixpath.dirname(h) == folder]
        return (near[0], False) if len(near) == 1 else (None, True)


def build_index(root: Path, *, limit: int = MAX_FILES * 5) -> tuple[VaultIndex, list[str], bool]:
    """``(index, markdown files, truncated)``. Hidden folders (``.obsidian``, ``.trash``,
    ``.git``) are skipped, and so are symbolic links."""
    index = VaultIndex()
    markdown: list[str] = []
    seen = 0
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and not os.path.islink(Path(dirpath, d))
        )
        folder = Path(dirpath)
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            seen += 1
            if seen > limit:
                return index, markdown, True
            path = folder / name
            if path.is_symlink():
                continue
            rel = path.relative_to(root).as_posix()
            index.add(rel)
            if name.lower().endswith(NOTE_SUFFIX):
                markdown.append(rel)
    if len(markdown) > MAX_FILES:
        markdown, truncated = markdown[:MAX_FILES], True
    return index, markdown, truncated


# -- code regions ---------------------------------------------------------------------------


def code_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges of fenced code blocks and inline code, where links are not links."""
    spans: list[tuple[int, int]] = []
    pos = 0
    plain: list[tuple[int, int]] = []
    while True:
        m = _FENCE_RE.search(text, pos)
        if not m:
            plain.append((pos, len(text)))
            break
        plain.append((pos, m.start()))
        fence = m["fence"]
        close = re.compile(rf"^[ ]{{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*$", re.M)
        line_end = text.find("\n", m.end())
        after = len(text) if line_end < 0 else line_end + 1
        c = close.search(text, after)
        end = len(text) if c is None else c.end()
        spans.append((m.start(), end))
        pos = end
    for a, b in plain:
        spans += [(a + c.start(), a + c.end()) for c in _INLINE_CODE_RE.finditer(text[a:b])]
    return sorted(spans)


def _inside(spans: list[tuple[int, int]], index: int) -> bool:
    return any(a <= index < b for a, b in spans)


# -- edits ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class LinkEdit:
    start: int
    end: int
    old: str
    new: str
    line: int


@dataclass
class LinkingNote:
    """A vault note with links to rewrite."""

    rel: str
    sha: str
    edits: list[LinkEdit]
    new_text: str


@dataclass
class LinkScan:
    notes: list[LinkingNote] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scanned: int = 0

    @property
    def link_count(self) -> int:
        return sum(len(n.edits) for n in self.notes)


def _is_archive(text: str) -> bool:
    try:
        fm, _ = split_frontmatter(text.removeprefix("﻿"))
    except FrontmatterError:
        return False
    return fm is not None and "mm3-archived" in fm.data


def _new_wiki_target(old_target: str, new_rel: str, after: VaultIndex) -> str:
    stripped = old_target.strip()
    lead = old_target[: len(old_target) - len(old_target.lstrip())]
    trail = old_target[len(old_target.rstrip()) :]
    had_md = stripped.lower().endswith(NOTE_SUFFIX)
    unique = len(after.named(new_rel)) == 1
    target = _link_name(new_rel) if "/" not in stripped and unique else _link_path(new_rel)
    if had_md and new_rel.lower().endswith(NOTE_SUFFIX):
        target += NOTE_SUFFIX
    return lead + target + trail


def _new_md_url(
    url: str, raw: str, fragment: str, new_rel: str, source_rel: str, relative: bool
) -> str:
    target = new_rel
    if not raw.lower().endswith(NOTE_SUFFIX) and target.lower().endswith(NOTE_SUFFIX):
        target = target.removesuffix(NOTE_SUFFIX)
    if relative:
        target = posixpath.relpath(target, posixpath.dirname(source_rel) or ".")
    elif raw.startswith("/"):
        target = "/" + target
    target += fragment
    if url.startswith("<"):
        return f"<{target}>"
    if "%" in url or any(c.isspace() for c in target):
        return quote(target, safe=_PCT_SAFE + "#")
    return target


def rewrite_links(
    text: str,
    source_rel: str,
    renames: Mapping[str, str],
    before: VaultIndex,
    after: VaultIndex,
) -> tuple[str, list[LinkEdit], list[str]]:
    """``(new text, edits, warnings)`` for one file. ``renames`` maps old to new vault-relative
    paths; ``before``/``after`` index the vault before and after the rename."""
    spans = code_spans(text)
    edits: list[LinkEdit] = []
    warnings: list[str] = []
    old_names = {_key(_link_name(o)) for o in renames}

    for m in _WIKI_RE.finditer(text):
        if _inside(spans, m.start()):
            continue
        target = m["target"]
        name = _key(posixpath.basename(target.strip()))
        name = name.removesuffix(NOTE_SUFFIX) if name.endswith(NOTE_SUFFIX) else name
        if name not in old_names:
            continue
        resolved, ambiguous = before.resolve_wiki(target, source_rel)
        if ambiguous:
            warnings.append(
                f"{source_rel}: the link [[{target.strip()}]] could mean several files, so it "
                "was left alone."
            )
            continue
        if resolved is None or resolved not in renames:
            continue
        new_target = _new_wiki_target(target, renames[resolved], after)
        if new_target != target:
            a, b = m.start("target"), m.end("target")
            edits.append(LinkEdit(a, b, target, new_target, text.count("\n", 0, a) + 1))

    for m in _MD_RE.finditer(text):
        if _inside(spans, m.start()):
            continue
        url = m["url"]
        inner = url[1:-1] if url.startswith("<") else url
        raw = inner if url.startswith("<") else unquote(inner)
        if _SCHEME_RE.match(raw):
            continue
        path, hash_, frag = raw.partition("#")
        fragment = hash_ + frag
        base = _key(posixpath.basename(path))
        base = base.removesuffix(NOTE_SUFFIX) if base.endswith(NOTE_SUFFIX) else base
        if not path or base not in old_names:
            continue
        resolved, relative = _resolve_md(path, source_rel, renames)
        if resolved is None:
            continue
        new_url = _new_md_url(url, path, fragment, renames[resolved], source_rel, relative)
        if new_url != url:
            a, b = m.start("url"), m.end("url")
            edits.append(LinkEdit(a, b, url, new_url, text.count("\n", 0, a) + 1))

    edits.sort(key=lambda e: e.start)
    out, pos = [], 0
    for e in edits:
        out += [text[pos : e.start], e.new]
        pos = e.end
    out.append(text[pos:])
    return "".join(out), edits, warnings


def _resolve_md(path: str, source_rel: str, renames: Mapping[str, str]) -> tuple[str | None, bool]:
    """``(renamed file, relative?)`` a Markdown link path points at: relative to the linking
    note first, then to the vault root."""
    by_key = {_key(o): o for o in renames}
    for relative, candidate in (
        (True, posixpath.normpath(posixpath.join(posixpath.dirname(source_rel), path))),
        (False, posixpath.normpath(path.lstrip("/"))),
    ):
        if relative and path.startswith("/"):
            continue
        for c in (candidate, candidate + NOTE_SUFFIX):
            if _key(c) in by_key:
                return by_key[_key(c)], relative
    return None, False


def _mentions(text: str, names: Iterable[str]) -> bool:
    folded = text.casefold()
    return any(n in folded or quote(n, safe=_PCT_SAFE) in folded for n in names)


def scan_backlinks(
    root: Path,
    renames: Mapping[str, str],
    *,
    exclude: Iterable[str] = (),
    index: tuple[VaultIndex, list[str], bool] | None = None,
) -> LinkScan:
    """Every vault note (outside ``exclude`` and MM3 archives) that links to a file in
    ``renames`` (vault-relative old → new), with the rewritten text."""
    before, markdown, truncated = index if index is not None else build_index(root)
    after = VaultIndex({k: list(v) for k, v in before.by_name.items()}, dict(before.by_path))
    for old in renames:
        after.remove(old)
    for new in renames.values():
        after.add(new)
    scan = LinkScan()
    if truncated:
        scan.warnings.append(
            f"The vault has more than {MAX_FILES} notes; only the first {MAX_FILES} were "
            "searched for links."
        )
    skipped: list[str] = []
    skip = {_key(e) for e in exclude} | {_key(o) for o in renames}
    names = {_key(_link_name(o)) for o in renames}
    for rel in markdown:
        if _key(rel) in skip:
            continue
        path = root / rel
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                skipped.append(rel)
                continue
            if not is_inside(root, path):
                continue
            text = read_text(path)
        except (OSError, UnicodeDecodeError):
            continue
        scan.scanned += 1
        if not _mentions(text, names) or _is_archive(text):
            continue
        new_text, edits, warnings = rewrite_links(text, rel, renames, before, after)
        scan.warnings += warnings
        if edits:
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            scan.notes.append(LinkingNote(rel, sha, edits, new_text))
    if skipped:
        scan.warnings.append(
            f"{len(skipped)} very large note(s) were not searched for links: "
            + ", ".join(skipped[:5])
            + ("…" if len(skipped) > 5 else "")
        )
    for new in renames.values():
        others = [r for r in after.named(new) if r != new]
        if others:
            scan.warnings.append(
                f"Another file is also called '{_link_name(new)}' ({others[0]}): links to the "
                "meeting are written with their folder so they stay unambiguous."
            )
    return scan
