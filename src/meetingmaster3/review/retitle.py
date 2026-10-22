"""Rename and re-date a meeting after it was written (Phase 15d, spec R28, ADR-0040).

One operation changes a meeting's title, date and (optionally) time everywhere:

* the note: ``title``, ``date``, ``mm3-transcript`` and ``mm3-audio`` properties, the H1, the
  ``Date & Time`` and ``Transcript`` header lines (each only if it is still what MM3 wrote);
* the companion transcript: ``mm3-note`` and its ``# Transcript: …`` heading;
* the readable transcript: regenerated from the companion under the new name;
* the archives of this meeting (renamed with the same stamps; link properties updated, bodies
  kept as they were);
* the vault audio copy (renamed);
* links in every other vault note (backed up first), via :mod:`meetingmaster3.vault.links`;
* the database (``jobs``, ``recent_meetings``) and the job's ``written.json``.

The ``mm3-id``, the sections, the transcript text, the speakers and the user's own text never
change. Prose that mentions the old title or date is only pointed out.

:func:`plan_retitle` reads and writes nothing but the plan. :func:`apply_retitle` writes a
journal and backups to app data first (``<data>/rename-backups/<stamp>-<mm3-id>/``), then
writes the new files, re-points the database (the commit point) and finally removes the old
names. :func:`recover_renames` finishes an interrupted rename after the commit point and rolls
one back before it.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import errno
import hashlib
import json
import logging
import os
import re
import shutil
import threading
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from meetingmaster3.domain.transcript import clean_name
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.frontmatter import (
    FrontmatterError,
    parse_wikilink,
    render_frontmatter,
    split_frontmatter,
    wikilink,
)
from meetingmaster3.markdown.note_parser import BOM, NoteParseError, ParsedNote, parse_note
from meetingmaster3.markdown.note_writer import TRANSCRIPT_LINE_PREFIX
from meetingmaster3.markdown.readable_transcript import render_readable
from meetingmaster3.markdown.transcript_format import TITLE_PREFIX, parse_transcript
from meetingmaster3.storage.db import Database
from meetingmaster3.templates.regenerate import find_companion
from meetingmaster3.vault.archive import ARCHIVE_FOLDER
from meetingmaster3.vault.changes import vault_changed
from meetingmaster3.vault.io import atomic_write_text, read_text
from meetingmaster3.vault.links import LinkScan, scan_backlinks
from meetingmaster3.vault.naming import (
    NOTE_SUFFIX,
    TRANSCRIPT_SUFFIX,
    note_stem,
    readable_names,
)
from meetingmaster3.vault.paths import confine, ensure_folder, expand_folder_template, is_inside
from meetingmaster3.vault.readable import find_readable

log = logging.getLogger(__name__)

BACKUPS_DIR = "rename-backups"
JOURNAL = "journal.json"
MANIFEST = "manifest.json"
WRITTEN_FILE = "written.json"
MAX_TITLE = 200

E_INVALID = "E_RETITLE_INVALID"
E_NOTHING = "E_RETITLE_NOTHING"
E_TARGET_EXISTS = "E_RETITLE_TARGET_EXISTS"
E_NOTE_CHANGED = "E_NOTE_CHANGED"

Keep = Literal["keep"]
KEEP: Keep = "keep"
Role = Literal["note", "companion", "readable", "archive", "audio", "link"]

_lock = threading.Lock()
"""One rename at a time per process (the web app and a CLI run each recover the other's)."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _invalid(message: str, hint: str = "") -> MM3Error:
    return MM3Error(E_INVALID, message, hint, status_code=422)


def _changed(what: str) -> MM3Error:
    return MM3Error(
        E_NOTE_CHANGED,
        f"{what} changed since the preview was made (in Obsidian, by sync or in another tab).",
        "Preview the new title and date again.",
        status_code=409,
    )


# -- the plan ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Change:
    """One visible change inside a file, for the preview."""

    label: str
    before: str
    after: str


@dataclass
class FileChange:
    role: Role
    old_rel: str
    new_rel: str
    old_sha: str
    new_text: str | None
    """``None`` for a file that only moves (the audio copy)."""
    changes: list[Change] = field(default_factory=list)

    @property
    def moved(self) -> bool:
        return self.old_rel != self.new_rel

    @property
    def new_sha(self) -> str:
        return self.old_sha if self.new_text is None else _sha(self.new_text.encode("utf-8"))

    def summary(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "old": self.old_rel,
            "new": self.new_rel,
            "moved": self.moved,
            "changes": [asdict(c) for c in self.changes],
        }


@dataclass
class RetitlePlan:
    mm3_id: str
    root: Path
    old_title: str
    new_title: str
    old_date: dt.datetime | None
    new_date: dt.datetime
    old_stem: str
    new_stem: str
    old_folder: str
    new_folder: str
    files: list[FileChange]
    links: list[FileChange]
    link_count: int
    scanned: int
    warnings: list[str]
    blocked: list[str]
    note_sha: str
    has_companion: bool

    @property
    def note(self) -> FileChange:
        return next(f for f in self.files if f.role == "note")

    @property
    def empty(self) -> bool:
        return not any(f.moved or f.changes for f in self.files)

    @property
    def digest(self) -> str:
        """Identifies the plan's inputs and outputs: a preview and its apply must agree."""
        parts = [
            f"{f.role}\0{f.old_rel}\0{f.old_sha}\0{f.new_rel}\0{f.new_sha}"
            for f in self.files + self.links
        ]
        return _sha("\n".join(sorted(parts)).encode("utf-8"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mm3_id": self.mm3_id,
            "old_title": self.old_title,
            "new_title": self.new_title,
            "old_date": self.old_date.isoformat() if self.old_date else None,
            "new_date": self.new_date.isoformat(),
            "old_stem": self.old_stem,
            "new_stem": self.new_stem,
            "old_folder": self.old_folder,
            "new_folder": self.new_folder,
            "files": [f.summary() for f in self.files],
            "links": [f.summary() for f in self.links],
            "link_count": self.link_count,
            "linking_notes": len(self.links),
            "scanned": self.scanned,
            "warnings": self.warnings,
            "blocked": self.blocked,
            "empty": self.empty,
            "digest": self.digest,
        }


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _shown(when: dt.datetime) -> str:
    """The date as the note header shows it (``note_writer.render_header``)."""
    return f"{when:%Y-%m-%d}" if when.time() == dt.time(0) else f"{when:%Y-%m-%d %H:%M}"


def clean_title(title: str) -> str:
    text = clean_name(title)
    if not text:
        raise _invalid("The title cannot be empty.", "Type the meeting's title.")
    if len(text) > MAX_TITLE:
        raise _invalid(f"The title is longer than {MAX_TITLE} characters.", "Shorten it.")
    return text


def new_datetime(
    old: dt.datetime | None, date: dt.date | None, time: dt.time | Keep | None
) -> dt.datetime:
    """The new ``date`` value: ``time`` ``"keep"`` keeps the old time, ``None`` means unknown
    (midnight, shown without a time)."""
    day = date or (old.date() if old else None)
    if day is None:
        raise _invalid("This meeting has no date yet.", "Give it a date (YYYY-MM-DD).")
    if time == KEEP:
        clock = old.time().replace(microsecond=0) if old else dt.time(0)
    else:
        clock = (time or dt.time(0)).replace(second=0, microsecond=0)
    return dt.datetime.combine(day, clock)


def _date_value(raw: Any, when: dt.datetime) -> Any:
    """The new ``date`` property in the shape the old one had (date, datetime or text)."""
    midnight = when.time() == dt.time(0)
    if isinstance(raw, str):
        return when.date().isoformat() if len(raw.strip()) <= 10 and midnight else when.isoformat()
    if isinstance(raw, dt.date) and not isinstance(raw, dt.datetime) and midnight:
        return when.date()
    return when


def _split(text: str) -> tuple[str, Any, str]:
    """``(bom, frontmatter, body)``."""
    bom = BOM if text.startswith(BOM) else ""
    try:
        fm, body = split_frontmatter(text[len(bom) :])
    except FrontmatterError:
        fm, body = None, text[len(bom) :]
    return bom, fm, body


def _relink(
    text: str, keys: Iterable[str], targets: dict[str, str], changes: list[Change], label: str
) -> str:
    """``text`` with each of ``keys`` whose wikilink target is in ``targets`` re-pointed. Every
    other byte of the frontmatter is kept (ADR-0011)."""
    bom, fm, body = _split(text)
    if fm is None:
        return text
    data = dict(fm.data)
    for key in keys:
        old = parse_wikilink(data.get(key))
        if old is not None and old in targets and targets[old] != old:
            data[key] = wikilink(targets[old])
            changes.append(Change(f"{label} property {key}", old, targets[old]))
    if data == fm.data:
        return text
    newline = "\r\n" if "\r\n" in fm.raw else "\n"
    return bom + render_frontmatter(data, newline=newline, base=fm) + body


def _note_text(
    text: str,
    parsed: ParsedNote,
    new_title: str,
    new_date: dt.datetime,
    targets: dict[str, str],
    old_readable: str | None,
    changes: list[Change],
    warnings: list[str],
) -> str:
    meta = parsed.note.meta
    bom, fm, body = _split(text)
    if fm is None:  # pragma: no cover - parse_note needs frontmatter
        raise _invalid("This note has no properties.")
    data = dict(fm.data)
    if new_title != meta.title:
        data["title"] = new_title
        changes.append(Change("property title", meta.title, new_title))
    if meta.date != new_date:
        data["date"] = _date_value(data.get("date"), new_date)
        changes.append(Change("property date", str(fm.data.get("date", "")), str(data["date"])))
    newline = "\r\n" if "\r\n" in fm.raw else "\n"
    head = bom + render_frontmatter(data, newline=newline, base=fm)
    head = _relink(head, ("mm3-transcript", "mm3-audio"), targets, changes, "note")

    lines = body.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].startswith("# "):
        h1 = lines[i].rstrip("\r")
        cr = lines[i][len(h1) :]
        if h1[2:].strip() == meta.title and new_title != meta.title:
            lines[i] = f"# {new_title}{cr}"
            changes.append(Change("heading", h1, f"# {new_title}"))
        elif new_title != meta.title:
            warnings.append(
                "The note's heading is not the old title (it was edited), so it was left as is."
            )
        i += 1
        while i < len(lines) and lines[i].startswith("- **"):
            line = lines[i].rstrip("\r")
            cr = lines[i][len(line) :]
            if line.startswith("- **Date & Time:**") and meta.date != new_date:
                expected = f"- **Date & Time:** {_shown(meta.date)}" if meta.date else None
                if line == expected:
                    lines[i] = f"- **Date & Time:** {_shown(new_date)}{cr}"
                    changes.append(Change("header line", line, lines[i].rstrip("\r")))
                else:
                    warnings.append("The note's Date & Time line was edited, so it was left as is.")
            elif (
                line.startswith(TRANSCRIPT_LINE_PREFIX)
                and old_readable is not None
                and old_readable in targets
            ):
                new_line = line.replace(f"[[{old_readable}|", f"[[{targets[old_readable]}|", 1)
                new_line = new_line.replace(f"[[{old_readable}]]", f"[[{targets[old_readable]}]]")
                if new_line != line:
                    lines[i] = new_line + cr
                    changes.append(Change("header line", line, new_line))
            i += 1
    return head + "\n".join(lines)


def _companion_text(
    text: str, new_title: str, targets: dict[str, str], changes: list[Change]
) -> str:
    text = _relink(text, ("mm3-note",), targets, changes, "transcript")
    bom, fm, body = _split(text)
    m = re.search(r"^# (?P<t>.*?)(?P<cr>\r?)$", body, re.M)
    if m and m["t"].startswith(TITLE_PREFIX) and m["t"] != TITLE_PREFIX + new_title:
        new_h1 = f"# {TITLE_PREFIX}{new_title}"
        changes.append(Change("heading", f"# {m['t']}", new_h1))
        body = body[: m.start()] + new_h1 + m["cr"] + body[m.end() :]
        return bom + (fm.raw if fm else "") + body
    return text


def _mentions(parsed: ParsedNote, needles: list[str]) -> list[str]:
    out = []
    for needle in needles:
        hits = [
            s.title or s.id
            for s in parsed.note.sections
            if needle.casefold() in s.body_markdown.casefold()
        ]
        count = sum(
            s.body_markdown.casefold().count(needle.casefold()) for s in parsed.note.sections
        )
        if count:
            out.append(
                f"{count} mention{'s' if count != 1 else ''} of '{needle}' inside sections "
                f"({', '.join(hits[:4])}): edit or regenerate them if needed."
            )
    return out


def _exists_as_other(target: Path, source: Path) -> bool:
    """A file is at ``target`` and it is not ``source`` itself (a case-only rename)."""
    if not os.path.lexists(target):
        return False
    try:
        return not (source.exists() and os.path.samefile(source, target))
    except OSError:
        return True


def _target_folder(
    root: Path, parsed: ParsedNote, note: Path, template: str, when: dt.date
) -> tuple[Path, str]:
    """``(folder, warning)``: the new date's output folder if the note sits in the old date's
    one, else the note's own folder."""
    old = parsed.note.meta.date
    if old is None:
        return note.parent, ""
    try:
        expected = confine(root, expand_folder_template(template, old.date()))
        new = confine(root, expand_folder_template(template, when))
    except MM3Error:
        return note.parent, ""
    if note.parent.resolve() != expected:
        if new != expected:
            return note.parent, (
                f"The note is not in the folder for its date ({_rel(root, expected) or '/'}), so "
                f"its files stay in {_rel(root, note.parent) or 'the vault root'}."
            )
        return note.parent, ""
    return new, ""


def plan_retitle(
    root: Path,
    note: Path,
    *,
    title: str | None = None,
    date: dt.date | None = None,
    time: dt.time | Keep | None = KEEP,
    output_subfolder: str = "Meetings/{yyyy}/",
    scan_links: bool = True,
) -> RetitlePlan:
    """Everything a rename would change. Reads the vault; writes nothing."""
    try:
        note = confine(root, note.relative_to(root) if note.is_absolute() else note)
    except ValueError as exc:
        raise _invalid("That note is not in the vault.") from exc
    if note.is_symlink() or not note.is_file():
        raise _invalid("That note is not a file in the vault.")
    text = read_text(note)
    try:
        parsed = parse_note(text)
    except (NoteParseError, MM3Error) as exc:
        raise MM3Error(
            E_INVALID,
            f"This note cannot be renamed: {getattr(exc, 'message', exc)}",
            "Fix its properties in Obsidian first.",
            status_code=409,
        ) from exc
    meta = parsed.note.meta
    mm3_id = str(meta.id)
    warnings: list[str] = []
    blocked: list[str] = []
    new_title = clean_title(title) if title is not None else meta.title
    new_dt = new_datetime(meta.date, date, time)
    old_stem = note.name.removesuffix(NOTE_SUFFIX)
    new_stem = note_stem(new_dt.date(), new_title)
    folder, moved_warning = _target_folder(root, parsed, note, output_subfolder, new_dt.date())
    if moved_warning:
        warnings.append(moved_warning)
    if os.path.lexists(folder) and not folder.is_dir():
        blocked.append(f"{_rel(root, folder)} exists in the vault but is not a folder.")

    targets: dict[str, str] = {old_stem: new_stem}
    files: list[FileChange] = []

    # companion
    found = find_companion(note, parsed)
    companion_doc = None
    comp_new: Path | None = None
    if found is None:
        warnings.append(
            "This note has no companion transcript, so only the note (and its archives) are "
            "renamed."
        )
    else:
        comp_path, _ = found
        comp_new = folder / (new_stem + TRANSCRIPT_SUFFIX)
        old_link = comp_path.name.removesuffix(NOTE_SUFFIX)
        targets[old_link] = comp_new.name.removesuffix(NOTE_SUFFIX)

    # readable transcript
    readable = find_readable(note, mm3_id)
    readable_new: Path | None = None
    if readable is not None:
        for name in readable_names(new_stem):
            candidate = folder / name
            if not _exists_as_other(candidate, readable):
                readable_new = candidate
                break
        if readable_new is None:
            blocked.append(f"Every name for the readable transcript of '{new_stem}' is taken.")
            readable_new = readable
        targets[readable.name.removesuffix(NOTE_SUFFIX)] = readable_new.name.removesuffix(
            NOTE_SUFFIX
        )

    # vault audio copy
    audio_old: Path | None = None
    audio_new: Path | None = None
    if meta.audio_ref:
        candidate = root / meta.audio_ref
        if candidate.is_file() and not candidate.is_symlink() and is_inside(root, candidate):
            name = candidate.name
            if name.startswith(old_stem) and name.endswith(".opus"):
                audio_old = candidate
                audio_new = candidate.with_name(new_stem + name[len(old_stem) :])
                targets[meta.audio_ref] = _rel(root, audio_new)

    # the note
    note_changes: list[Change] = []
    old_readable_link = readable.name.removesuffix(NOTE_SUFFIX) if readable else None
    new_note_text = _note_text(
        text, parsed, new_title, new_dt, targets, old_readable_link, note_changes, warnings
    )
    note_new = folder / (new_stem + NOTE_SUFFIX)
    files.append(
        FileChange(
            "note",
            _rel(root, note),
            _rel(root, note_new),
            _sha(text.encode()),
            new_note_text,
            note_changes,
        )
    )

    if found is not None and comp_new is not None:
        comp_path, _ = found
        comp_text = read_text(comp_path)
        comp_changes: list[Change] = []
        new_comp_text = _companion_text(comp_text, new_title, targets, comp_changes)
        companion_doc = parse_transcript(new_comp_text).doc
        files.append(
            FileChange(
                "companion",
                _rel(root, comp_path),
                _rel(root, comp_new),
                _sha(comp_text.encode()),
                new_comp_text,
                comp_changes,
            )
        )

    if readable is not None and readable_new is not None:
        r_text = read_text(readable)
        r_changes: list[Change] = []
        if companion_doc is not None and comp_new is not None:
            new_r = render_readable(
                companion_doc,
                note_link=new_stem,
                transcript_link=comp_new.name.removesuffix(NOTE_SUFFIX),
            )
            if new_r != r_text:
                r_changes.append(Change("whole file", "", "regenerated from the transcript"))
        else:
            new_r = _relink(r_text, ("mm3-note", "mm3-transcript"), targets, r_changes, "readable")
        files.append(
            FileChange(
                "readable",
                _rel(root, readable),
                _rel(root, readable_new),
                _sha(r_text.encode()),
                new_r,
                r_changes,
            )
        )

    if audio_old is not None and audio_new is not None:
        files.append(
            FileChange(
                "audio", _rel(root, audio_old), _rel(root, audio_new), _file_sha(audio_old), None
            )
        )

    # archives
    archive_dir = note.parent / ARCHIVE_FOLDER
    if archive_dir.is_dir() and not archive_dir.is_symlink():
        for path in sorted(archive_dir.iterdir()):
            name = path.name
            if (
                not name.endswith(NOTE_SUFFIX)
                or not name.casefold().startswith((old_stem + ".").casefold())
                or path.is_symlink()
                or not path.is_file()
            ):
                continue
            a_text = read_text(path)
            _, fm, _ = _split(a_text)
            if fm is None or "mm3-archived" not in fm.data:
                continue
            owner = fm.data.get("mm3-id") or fm.data.get("mm3-archived-id")
            if str(owner) != mm3_id:
                continue
            a_changes: list[Change] = []
            new_a = _relink(
                a_text,
                ("mm3-archived-from", "mm3-transcript", "mm3-audio"),
                targets,
                a_changes,
                "archive",
            )
            new_path = folder / ARCHIVE_FOLDER / (new_stem + name[len(old_stem) :])
            files.append(
                FileChange(
                    "archive",
                    _rel(root, path),
                    _rel(root, new_path),
                    _sha(a_text.encode()),
                    new_a,
                    a_changes,
                )
            )

    files = [f for f in files if f.role == "note" or f.moved or f.new_sha != f.old_sha]

    # collisions
    seen: dict[str, str] = {}
    for f in files:
        key = f.new_rel.casefold()
        if key in seen and seen[key] != f.old_rel:
            blocked.append(f"Two files would both be called {f.new_rel}.")
        seen[key] = f.old_rel
        if f.moved and _exists_as_other(root / f.new_rel, root / f.old_rel):
            blocked.append(f"{f.new_rel} already exists. Choose another title or date.")
        try:
            confine(root, f.new_rel)
        except MM3Error:
            blocked.append(f"{f.new_rel} would be outside the vault.")

    # warnings about the content
    needles = []
    if new_title != meta.title:
        needles.append(meta.title)
    if meta.date is not None and meta.date.date() != new_dt.date():
        needles += [f"{meta.date:%Y-%m-%d}", f"{meta.date:%m-%d}"]
    warnings += _mentions(parsed, [n for n in needles if n])
    if parsed.marker_errors:
        warnings.append(
            "Some section markers are damaged (R11). The rename does not touch sections, so "
            "they stay as they are."
        )

    links: list[FileChange] = []
    link_count = scanned = 0
    renames = {f.old_rel: f.new_rel for f in files if f.moved}
    if scan_links and renames:
        scan: LinkScan = scan_backlinks(root, renames, exclude=[f.old_rel for f in files])
        warnings += scan.warnings
        scanned, link_count = scan.scanned, scan.link_count
        for n in scan.notes:
            links.append(
                FileChange(
                    "link",
                    n.rel,
                    n.rel,
                    n.sha,
                    n.new_text,
                    [Change(f"line {e.line}", e.old, e.new) for e in n.edits],
                )
            )

    return RetitlePlan(
        mm3_id=mm3_id,
        root=root,
        old_title=meta.title,
        new_title=new_title,
        old_date=meta.date,
        new_date=new_dt,
        old_stem=old_stem,
        new_stem=new_stem,
        old_folder=_rel(root, note.parent),
        new_folder=_rel(root, folder) if is_inside(root, folder) else str(folder),
        files=files,
        links=links,
        link_count=link_count,
        scanned=scanned,
        warnings=list(dict.fromkeys(warnings)),
        blocked=list(dict.fromkeys(blocked)),
        note_sha=_sha(text.encode()),
        has_companion=found is not None,
    )


# -- the journal -------------------------------------------------------------------------------

Phase = Literal["prepared", "committed"]


@dataclass
class RetitleResult:
    note_rel: str
    note_sha: str
    backup: str
    outcome: Literal["completed", "rolled back"]
    warnings: list[str] = field(default_factory=list)


def backups_root(data_dir: Path) -> Path:
    return data_dir / BACKUPS_DIR


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    with contextlib.suppress(OSError):
        os.chmod(path, 0o700)
    return path


def _write_json(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(
        path, json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", overwrite=True
    )


def _job_written(jobs_root: Path, job_id: str | None) -> Path | None:
    if not job_id:
        return None
    path = jobs_root / job_id / WRITTEN_FILE
    return path if path.is_file() else None


def _find_job(db: Database, jobs_root: Path, mm3_id: str, note_abs: str) -> str | None:
    row = db.fetchone(
        "SELECT job_id FROM recent_meetings WHERE note_path = ? AND job_id IS NOT NULL", (note_abs,)
    )
    if row is not None and db.fetchone("SELECT id FROM jobs WHERE id = ?", (row["job_id"],)):
        return str(row["job_id"])
    for job in db.fetchall("SELECT id FROM jobs ORDER BY created_at DESC LIMIT 500"):
        written = jobs_root / job["id"] / WRITTEN_FILE
        try:
            if written.is_file() and json.loads(written.read_text("utf-8")).get("mm3_id") == mm3_id:
                return str(job["id"])
        except (OSError, ValueError):
            continue
    return None


def _db_state(db: Database, jobs_root: Path, journal: dict[str, Any], side: str) -> dict[str, Any]:
    """The DB rows and ``written.json`` of one side (``before``/``after``) of a rename."""
    root = Path(journal["root"])
    files = {f["role"]: f for f in journal["files"]}
    key = "old_rel" if side == "before" else "new_rel"
    note_abs = str(root / files["note"][key])
    comp = files.get("companion")
    title = journal["old_title" if side == "before" else "new_title"]
    when = journal["old_date" if side == "before" else "new_date"]
    return {
        "note_path": note_abs,
        "transcript_path": str(root / comp[key]) if comp else None,
        "readable_rel": files["readable"][key] if "readable" in files else None,
        "title": title,
        "date": when[:10] if when else None,
        "time": when[11:16] if when and when[11:16] != "00:00" else None,
    }


def _apply_db(db: Database, jobs_root: Path, journal: dict[str, Any], side: str) -> None:
    """Put the database and ``written.json`` in the ``side`` state. Idempotent."""
    want = _db_state(db, jobs_root, journal, side)
    other = _db_state(db, jobs_root, journal, "after" if side == "before" else "before")
    mm3_id = journal["mm3_id"]
    job_id = journal.get("job_id")
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM recent_meetings WHERE note_path = ?", (other["note_path"],)
        ).fetchone()
        if row is not None and want["note_path"] != other["note_path"]:
            conn.execute(
                "INSERT INTO recent_meetings (note_path, transcript_path, mm3_id, title, date,"
                " last_opened, job_id) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (note_path) DO"
                " UPDATE SET transcript_path = excluded.transcript_path, title = excluded.title,"
                " date = excluded.date, mm3_id = excluded.mm3_id",
                (
                    want["note_path"],
                    want["transcript_path"] or row["transcript_path"],
                    mm3_id,
                    want["title"],
                    want["date"],
                    row["last_opened"],
                    row["job_id"],
                ),
            )
            conn.execute("DELETE FROM recent_meetings WHERE note_path = ?", (other["note_path"],))
        conn.execute(
            "UPDATE recent_meetings SET title = ?, date = ?,"
            " transcript_path = COALESCE(?, transcript_path) WHERE note_path = ? AND mm3_id = ?",
            (want["title"], want["date"], want["transcript_path"], want["note_path"], mm3_id),
        )
        if job_id:
            job = conn.execute("SELECT settings_json FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if job is not None:
                try:
                    settings = json.loads(job["settings_json"] or "{}")
                except ValueError:
                    settings = {}
                if isinstance(settings, dict):
                    settings.update(
                        title=want["title"], meeting_date=want["date"], meeting_time=want["time"]
                    )
                conn.execute(
                    "UPDATE jobs SET title = ?, meeting_date = ?, settings_json = ? WHERE id = ?",
                    (want["title"], want["date"], json.dumps(settings, default=str), job_id),
                )
    written = _job_written(jobs_root, job_id)
    if written is not None:
        try:
            info = json.loads(written.read_text("utf-8"))
        except (OSError, ValueError):
            return
        if info.get("mm3_id") != mm3_id:
            return
        root = Path(journal["root"])
        info["note_path"] = want["note_path"]
        info["note_relative"] = Path(want["note_path"]).relative_to(root).as_posix()
        if want["transcript_path"]:
            info["transcript_path"] = want["transcript_path"]
            info["transcript_relative"] = Path(want["transcript_path"]).relative_to(root).as_posix()
        if want["readable_rel"]:
            info["readable_relative"] = want["readable_rel"]
        info["title"] = want["title"]
        atomic_write_text(written, json.dumps(info) + "\n", overwrite=True)


def _write_text_file(root: Path, rel: str, text: str) -> None:
    path = confine(root, rel)
    ensure_folder(root, Path(rel).parent)
    atomic_write_text(path, text, overwrite=True, vault_root=root)


def _link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError as exc:
        if exc.errno not in (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV):
            raise
        shutil.copy2(src, dst)


def _same(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _case_only(f: dict[str, Any], old: Path, new: Path) -> bool:
    """A case-only rename on a case-insensitive file system: both names are one file. (A
    hard link made for the audio copy is also "one file", but its names differ by more.)"""
    return (
        f["old_rel"] != f["new_rel"]
        and f["old_rel"].casefold() == f["new_rel"].casefold()
        and (_same(old, new))
    )


Step = Callable[[str], None]


def _write_files(root: Path, backup: Path, journal: dict[str, Any], step: Step) -> None:
    for f in journal["files"]:
        old, new = confine(root, f["old_rel"]), confine(root, f["new_rel"])
        if f["binary"]:
            if not os.path.lexists(new):
                ensure_folder(root, Path(f["new_rel"]).parent)
                _link_or_copy(old, new)
            step(f"wrote {f['new_rel']}")
            continue
        text = read_text(backup / "new" / f["new_rel"])
        if f["old_rel"] == f["new_rel"]:
            if _file_sha(old) != f["old_sha"]:
                raise _changed(f["old_rel"])
            atomic_write_text(old, text, overwrite=True, vault_root=root)
        elif _case_only(f, old, new):
            os.rename(old, new)
            atomic_write_text(new, text, overwrite=True, vault_root=root)
        else:
            ensure_folder(root, Path(f["new_rel"]).parent)
            atomic_write_text(new, text, overwrite=False, vault_root=root)
        step(f"wrote {f['new_rel']}")


def _remove_old(root: Path, journal: dict[str, Any], warnings: list[str], step: Step) -> None:
    for f in journal["files"]:
        if f["old_rel"] == f["new_rel"]:
            continue
        old, new = root / f["old_rel"], root / f["new_rel"]
        if not os.path.lexists(old) or not os.path.lexists(new) or _case_only(f, old, new):
            continue
        if old.is_symlink() or not is_inside(root, old):
            continue
        try:
            if _file_sha(old) != f["old_sha"]:
                warnings.append(f"{f['old_rel']} was changed during the rename, so it was kept.")
                continue
            old.unlink()
        except OSError as exc:
            warnings.append(f"{f['old_rel']} could not be removed ({exc.strerror}); delete it.")
            continue
        step(f"removed {f['old_rel']}")


def _roll_back(
    root: Path, backup: Path, journal: dict[str, Any], db: Database, jobs_root: Path
) -> None:
    for f in reversed(journal["files"]):
        old, new = root / f["old_rel"], root / f["new_rel"]
        if f["binary"]:
            if os.path.lexists(new) and f["old_rel"] != f["new_rel"]:
                if os.path.lexists(old):
                    if _same(old, new) or _file_sha(new) == f["old_sha"]:
                        new.unlink()
                elif _file_sha(new) == f["old_sha"]:
                    os.rename(new, old)
            continue
        saved = backup / "files" / f["old_rel"]
        if f["old_rel"] == f["new_rel"] or _case_only(f, old, new):
            if os.path.lexists(new) and _file_sha(new) == f["new_sha"] and saved.is_file():
                atomic_write_text(new, read_text(saved), overwrite=True, vault_root=root)
                if f["old_rel"] != f["new_rel"]:
                    os.rename(new, old)
            continue
        if os.path.lexists(new) and _file_sha(new) == f["new_sha"]:
            new.unlink()
        if not os.path.lexists(old) and saved.is_file():
            _write_text_file(root, f["old_rel"], read_text(saved))
    _apply_db(db, jobs_root, journal, "before")


def _finish(backup: Path, journal: dict[str, Any], outcome: str) -> None:
    manifest = backup / MANIFEST
    try:
        data = json.loads(manifest.read_text("utf-8"))
    except (OSError, ValueError):
        data = {}
    data.update(outcome=outcome, finished_at=dt.datetime.now().isoformat(timespec="seconds"))
    _write_json(manifest, data)
    with contextlib.suppress(FileNotFoundError):
        (backup / JOURNAL).unlink()
    shutil.rmtree(backup / "new", ignore_errors=True)


def apply_retitle(
    plan: RetitlePlan,
    *,
    data_dir: Path,
    db: Database,
    jobs_root: Path,
    expected_digest: str | None = None,
    step: Step | None = None,
) -> RetitleResult:
    """Carry out ``plan``. ``expected_digest`` is the digest the user previewed. ``step`` is
    called after each step (tests use it to simulate a crash)."""
    tick: Step = step or (lambda _s: None)
    if plan.blocked:
        raise MM3Error(E_TARGET_EXISTS, plan.blocked[0], "Choose another title or date.", 409)
    if plan.empty:
        raise MM3Error(E_NOTHING, "The title and date are unchanged.", "", status_code=422)
    if expected_digest is not None and expected_digest != plan.digest:
        raise _changed("The meeting's files or the notes linking to it")
    with _lock:
        recover_renames(data_dir, db, jobs_root)
        root = plan.root
        for f in plan.files + plan.links:
            path = confine(root, f.old_rel)
            if path.is_symlink() or not path.is_file() or _file_sha(path) != f.old_sha:
                raise _changed(f.old_rel)
            if f.moved and _exists_as_other(root / f.new_rel, path):
                raise MM3Error(E_TARGET_EXISTS, f"{f.new_rel} already exists.", "", 409)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = _private_dir(backups_root(data_dir) / f"{stamp}-{plan.mm3_id}")
        entries = []
        for f in plan.files + plan.links:
            binary = f.new_text is None
            if not binary:
                saved = backup / "files" / f.old_rel
                _private_dir(saved.parent)
                shutil.copyfile(root / f.old_rel, saved)
                new = backup / "new" / f.new_rel
                _private_dir(new.parent)
                atomic_write_text(new, f.new_text or "", overwrite=True)
            entries.append(
                {
                    "role": f.role,
                    "old_rel": f.old_rel,
                    "new_rel": f.new_rel,
                    "old_sha": f.old_sha,
                    "new_sha": f.new_sha,
                    "binary": binary,
                    "changes": [asdict(c) for c in f.changes],
                }
            )
        note_abs = str(root / plan.note.old_rel)
        journal: dict[str, Any] = {
            "version": 1,
            "phase": "prepared",
            "mm3_id": plan.mm3_id,
            "root": str(root),
            "jobs_root": str(jobs_root),
            "job_id": _find_job(db, jobs_root, plan.mm3_id, note_abs),
            "old_title": plan.old_title,
            "new_title": plan.new_title,
            "old_date": plan.old_date.isoformat() if plan.old_date else None,
            "new_date": plan.new_date.isoformat(),
            "started_at": dt.datetime.now().isoformat(timespec="seconds"),
            "files": entries,
        }
        journal["db_before"] = _db_state(db, jobs_root, journal, "before")
        journal["db_after"] = _db_state(db, jobs_root, journal, "after")
        _write_json(
            backup / MANIFEST,
            {
                **journal,
                "phase": None,
                "outcome": "in progress",
                "backups": "files/ holds every changed text file as it was",
            },
        )
        _write_json(backup / JOURNAL, journal)
        tick("journal")
        warnings = list(plan.warnings)
        try:
            _write_files(root, backup, journal, tick)
            _apply_db(db, jobs_root, journal, "after")
            tick("database")
        except Exception:  # a real error: undo now (a crash is recovered at the next start)
            try:
                _roll_back(root, backup, journal, db, jobs_root)
                _finish(backup, journal, "rolled back")
            except Exception:  # pragma: no cover - left for recovery at the next start
                log.exception(
                    "rename %s could not be rolled back; recovery will retry", plan.mm3_id
                )
            raise
        journal["phase"] = "committed"
        _write_json(backup / JOURNAL, journal)
        tick("committed")
        _remove_old(root, journal, warnings, tick)
        _finish(backup, journal, "completed")
    vault_changed()  # the old names are gone too: the search index follows the move
    note_new = root / plan.note.new_rel
    return RetitleResult(
        note_rel=plan.note.new_rel,
        note_sha=_file_sha(note_new),
        backup=str(backup),
        outcome="completed",
        warnings=warnings,
    )


@dataclass(frozen=True)
class Recovery:
    mm3_id: str
    outcome: Literal["completed", "rolled back", "failed"]
    title: str
    backup: str
    message: str


def recover_renames(data_dir: Path, db: Database, jobs_root: Path | None = None) -> list[Recovery]:
    """Finish (after the commit point) or roll back (before it) every interrupted rename."""
    folder = backups_root(data_dir)
    if not folder.is_dir():
        return []
    done: list[Recovery] = []
    for journal_path in sorted(folder.glob(f"*/{JOURNAL}")):
        backup = journal_path.parent
        try:
            journal = json.loads(journal_path.read_text("utf-8"))
            root = Path(journal["root"])
            jobs = Path(journal.get("jobs_root") or jobs_root or data_dir / "jobs")
            if journal["phase"] == "committed":
                _apply_db(db, jobs, journal, "after")
                warnings: list[str] = []
                _remove_old(root, journal, warnings, lambda _s: None)
                _finish(backup, journal, "completed")
                outcome: Literal["completed", "rolled back", "failed"] = "completed"
                message = (
                    f"An interrupted rename of '{journal['old_title']}' to "
                    f"'{journal['new_title']}' was completed."
                )
            else:
                _roll_back(root, backup, journal, db, jobs)
                _finish(backup, journal, "rolled back")
                outcome = "rolled back"
                message = (
                    f"An interrupted rename of '{journal['old_title']}' was undone: the meeting "
                    "keeps its old title and date."
                )
            log.warning("rename recovery: %s", message)
        except (OSError, ValueError, KeyError, MM3Error) as exc:
            outcome = "failed"
            message = (
                f"An interrupted rename could not be recovered ({exc}). The backups and the "
                f"journal are in {backup}."
            )
            log.error("rename recovery failed for %s: %s", backup, exc)
            journal = {"mm3_id": "", "new_title": ""}
        done.append(
            Recovery(
                journal.get("mm3_id", ""),
                outcome,
                journal.get("new_title", ""),
                str(backup),
                message,
            )
        )
    return done
