"""Template library management for the UI: favourite, duplicate, create, edit, delete, reset.

Templates are plain Markdown files in the vault's templates folder (the user may edit them in
Obsidian at any time), so every change here is a careful, atomic text edit: marking a favourite
touches only the ``favorite:`` line, and nothing is destroyed without an archive copy in
``<templates folder>/Archive/``. Built-in templates are only ever read from the package.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from meetingmaster3.errors import MM3Error
from meetingmaster3.templates.loader import (
    TemplateEntry,
    TemplateLibrary,
    builtin_dir,
    builtin_files,
    install_builtins,
    load_library,
    record_installed,
    vault_templates_dir,
)
from meetingmaster3.templates.schema import TemplateIssue, parse_template
from meetingmaster3.vault.io import atomic_write_text, read_text
from meetingmaster3.vault.paths import ensure_folder, is_inside

ARCHIVE_FOLDER = "Archive"
FILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()-]{0,120}\.md$")
_FENCE = re.compile(r"^---[ \t]*\r?$")

SKELETON = """---
mm3-template: 1
id: {id}
name: {name}
description: Describe what this template is for.
tags: []
favorite: false
sections:
  - {{id: summary, title: Summary, kind: narrative}}
  - {{id: action-items, title: Action Items, kind: extraction, format: tasks}}
params: {{temperature: null, max_tokens_per_section: 800, ai_recommendations: false}}
---
Your own template. Format: docs/dev-guide/template-format.md in the MeetingMaster3 repository.

<!-- mm3:prompt:_system -->
You write clear, accurate meeting notes. Use only what was said in the meeting.

<!-- mm3:prompt:summary -->
Write 2-4 sentences that say what the meeting was for and what was concluded.

<!-- mm3:prompt:action-items -->
List every task someone committed to, one per line, with the owner and any deadline.
"""


@dataclass(frozen=True)
class SaveResult:
    ok: bool
    issues: tuple[TemplateIssue, ...] = ()
    file: str = ""


# -- frontmatter line editing -------------------------------------------------------------------


def _frontmatter_bounds(lines: list[str]) -> tuple[int, int]:
    """Indexes of the opening and closing ``---`` lines."""
    if not lines or not _FENCE.match(lines[0]):
        raise MM3Error("E_TEMPLATE_INVALID", "The template has no frontmatter.", "", 422)
    for i in range(1, len(lines)):
        if _FENCE.match(lines[i]):
            return 0, i
    raise MM3Error("E_TEMPLATE_INVALID", "The template's frontmatter is not closed.", "", 422)


def set_frontmatter_value(text: str, key: str, value: str) -> str:
    """Replace the top-level ``key: …`` line (or add it before the closing fence). Every other
    byte of the file stays as it was."""
    lines = text.splitlines(keepends=True)
    _, end = _frontmatter_bounds(lines)
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    pattern = re.compile(rf"^{re.escape(key)}:(?:[ \t].*)?\r?$")
    for i in range(1, end):
        if pattern.match(lines[i].rstrip("\n")):
            lines[i] = f"{key}: {value}{newline}"
            return "".join(lines)
    lines.insert(end, f"{key}: {value}{newline}")
    return "".join(lines)


def set_favorite_text(text: str, favorite: bool) -> str:
    return set_frontmatter_value(text, "favorite", "true" if favorite else "false")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48].strip("-")
    return slug or "template"


# -- the manager --------------------------------------------------------------------------------


class TemplateManager:
    def __init__(self, vault_root: Path, subfolder: str, manifest_path: Path) -> None:
        self.vault_root = vault_root
        self.subfolder = subfolder
        self.manifest_path = manifest_path

    # -- lookup -----------------------------------------------------------------------------

    def library(self) -> TemplateLibrary:
        return load_library(self.vault_root, self.subfolder)

    def folder(self, *, create: bool = False) -> Path:
        return vault_templates_dir(self.vault_root, self.subfolder, create=create)

    def _check_name(self, file_name: str) -> str:
        if not FILE_NAME_RE.match(file_name) or file_name.startswith("_"):
            raise MM3Error(
                "E_TEMPLATE_NOT_FOUND",
                "That is not a template file name.",
                "Template files are .md files directly inside the templates folder.",
                status_code=404,
            )
        return file_name

    def builtin_names(self) -> set[str]:
        return {p.name for p in builtin_files()}

    def entry(self, file_name: str) -> TemplateEntry:
        """The library entry for a file name, preferring the vault's copy."""
        self._check_name(file_name)
        found = [e for e in self.library().entries if e.path.name == file_name]
        found.sort(key=lambda e: e.source != "vault")  # the vault's copy first
        if not found:
            raise MM3Error(
                "E_TEMPLATE_NOT_FOUND",
                f"There is no template file {file_name!r}.",
                "Reload the template list.",
                status_code=404,
            )
        return found[0]

    def vault_path(self, file_name: str) -> Path:
        """The vault file for ``file_name``; a built-in not yet in the vault is installed
        first (copied, never overwriting)."""
        self._check_name(file_name)
        path = self.folder() / file_name
        if not path.is_file() and file_name in self.builtin_names():
            install_builtins(self.vault_root, self.subfolder, self.manifest_path)
        if not path.is_file() or not is_inside(self.vault_root, path):
            raise MM3Error(
                "E_TEMPLATE_NOT_FOUND",
                f"There is no template file {file_name!r} in the vault.",
                "Reload the template list.",
                status_code=404,
            )
        return path

    def read(self, file_name: str) -> str:
        path = self.folder() / self._check_name(file_name)
        if path.is_file() and is_inside(self.vault_root, path):
            return read_text(path)
        shipped = builtin_dir() / file_name
        if shipped.is_file():
            return read_text(shipped)
        raise MM3Error("E_TEMPLATE_NOT_FOUND", f"No template file {file_name!r}.", "", 404)

    # -- changes ----------------------------------------------------------------------------

    def _write(self, path: Path, text: str, *, overwrite: bool) -> None:
        atomic_write_text(path, text, overwrite=overwrite, vault_root=self.vault_root)

    def set_favorite(self, file_name: str, favorite: bool) -> None:
        path = self.vault_path(file_name)
        text = read_text(path)
        updated = set_favorite_text(text, favorite)
        if updated != text:
            self._write(path, updated, overwrite=True)

    def _other_ids(self, except_file: str | None) -> set[str]:
        return {
            e.id
            for e in self.library().entries
            if e.id and e.source == "vault" and e.path.name != except_file
        }

    def save(self, file_name: str, text: str) -> SaveResult:
        """Validate and write an edited template. Nothing is written when there is an error;
        the issues carry line numbers for the editor."""
        report = parse_template(text, source=file_name)
        issues = list(report.issues)
        if report.template_id and report.template_id in self._other_ids(file_name):
            issues.append(
                TemplateIssue(
                    "duplicate_template_id",
                    f"Another template file already uses the id '{report.template_id}'.",
                )
            )
        if any(i.severity == "error" for i in issues) or report.template is None:
            return SaveResult(False, tuple(issues), file_name)
        path = self.folder() / self._check_name(file_name)
        if not path.is_file():
            self.vault_path(file_name)  # installs a built-in that was only in the package
        self._write(path, text, overwrite=True)
        return SaveResult(True, tuple(i for i in issues if i.severity == "warning"), file_name)

    def _free_name(self, stem: str, template_id_base: str) -> tuple[str, str]:
        folder = self.folder(create=True)
        taken = self._other_ids(None) | {
            e.id for e in self.library().entries if e.source == "builtin" and e.id
        }
        n = 1
        while True:
            suffix = "" if n == 1 else f"-{n}"
            new_id = f"{template_id_base}{suffix}"[:64].strip("-")
            file = f"{stem}{'' if n == 1 else f' ({n})'}.md"
            if new_id not in taken and not (folder / file).exists():
                return new_id, file
            n += 1

    def duplicate(self, file_name: str) -> str:
        """Copy a template under a new id and the name ``<name> (copy)``; returns the new file."""
        source_text = self.read(file_name)
        report = parse_template(source_text, source=file_name)
        if report.template is None:
            raise MM3Error(
                "E_TEMPLATE_INVALID",
                "An invalid template cannot be duplicated.",
                "Fix it first, or delete it.",
                status_code=422,
            )
        t = report.template
        new_id, new_file = self._free_name(f"{t.name} (copy)".replace("/", "-"), f"{t.id}-copy")
        text = set_frontmatter_value(source_text, "id", new_id)
        text = set_frontmatter_value(text, "name", json.dumps(f"{t.name} (copy)"))
        text = set_favorite_text(text, False)
        self.folder(create=True)
        self._write(self.folder() / new_file, text, overwrite=False)
        return new_file

    def create(self, name: str) -> str:
        """Start a new template from the skeleton; returns the file name."""
        name = " ".join(name.split())[:100]
        if not name:
            raise MM3Error("E_TEMPLATE_INVALID", "Give the template a name.", "", 422)
        new_id, new_file = self._free_name(re.sub(r"[/\\:*?\"<>|]", "-", name), slugify(name))
        self.folder(create=True)
        self._write(
            self.folder() / new_file,
            SKELETON.format(id=new_id, name=json.dumps(name)),
            overwrite=False,
        )
        return new_file

    def _archive(self, path: Path) -> Path:
        folder = ensure_folder(self.vault_root, f"{self.subfolder.rstrip('/')}/{ARCHIVE_FOLDER}")
        stamp = f"{dt.datetime.now():%Y%m%d-%H%M%S}"
        n = 1
        while True:
            target = folder / f"{path.stem}.{stamp}{'' if n == 1 else f'-{n}'}.md"
            if not os.path.lexists(target):
                break
            n += 1
        atomic_write_text(target, read_text(path), vault_root=self.vault_root)
        return target

    def delete(self, file_name: str) -> Path:
        """Remove a custom template (an archive copy is kept). Built-ins are reset, not deleted."""
        path = self.vault_path(file_name)
        entry = self.entry(file_name)
        builtin_ids = {e.id for e in self.library().entries if e.source == "builtin"}
        if file_name in self.builtin_names() or (entry.id and entry.id in builtin_ids):
            raise MM3Error(
                "E_TEMPLATE_BUILTIN",
                "Built-in templates cannot be deleted.",
                "Use “Reset to default” to restore the shipped version.",
                status_code=409,
            )
        archived = self._archive(path)
        path.unlink()
        return archived

    def reset_builtin(self, file_name: str) -> Path | None:
        """Restore the shipped version of a built-in template. The user's copy, if different,
        is archived first. Returns the archive path (``None`` when nothing needed archiving)."""
        if file_name not in self.builtin_names():
            raise MM3Error(
                "E_TEMPLATE_BUILTIN",
                "Only built-in templates can be reset.",
                "Custom templates have no default to return to.",
                status_code=409,
            )
        shipped = (builtin_dir() / file_name).read_bytes()
        self.folder(create=True)
        path = self.folder() / file_name
        archived: Path | None = None
        if path.is_file():
            if path.read_bytes() != shipped:
                archived = self._archive(path)
            self._write(path, shipped.decode("utf-8"), overwrite=True)
        else:
            self._write(path, shipped.decode("utf-8"), overwrite=False)
        record_installed(self.manifest_path, file_name, shipped)
        return archived
