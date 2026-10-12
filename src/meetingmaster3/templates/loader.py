"""Template library: built-in templates, the vault's templates folder and installation.

Vault templates override built-ins with the same id. Invalid templates are listed with their
issues instead of raising. :func:`install_builtins` copies the built-ins into the vault without
ever replacing a file the user changed (see ``docs/dev-guide/template-format.md`` §1).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from meetingmaster3.errors import MM3Error
from meetingmaster3.templates.schema import (
    Template,
    TemplateIssue,
    TemplateReport,
    parse_template_file,
)
from meetingmaster3.vault.io import atomic_write_text
from meetingmaster3.vault.paths import confine, ensure_folder, is_inside

log = logging.getLogger(__name__)

BUILTIN_PACKAGE = "meetingmaster3.starter_templates"
DEFAULT_TEMPLATE_ID = "executive-summary"
MANIFEST_NAME = "templates.installed.json"
E_TEMPLATE_NOT_FOUND = "E_TEMPLATE_NOT_FOUND"
E_TEMPLATE_INVALID = "E_TEMPLATE_INVALID"

Source = Literal["builtin", "vault"]


@dataclass(frozen=True)
class TemplateEntry:
    """One template file in the library, valid or not."""

    source: Source
    path: Path
    report: TemplateReport
    overrides_builtin: bool = False
    issues: tuple[TemplateIssue, ...] = ()
    """Library-level problems (e.g. a duplicate id), in addition to the file's own."""

    @property
    def id(self) -> str | None:
        return self.report.template_id

    @property
    def template(self) -> Template | None:
        return None if self.issues else self.report.template

    @property
    def all_issues(self) -> list[TemplateIssue]:
        return [*self.report.issues, *self.issues]

    @property
    def valid(self) -> bool:
        return self.template is not None and not any(i.severity == "error" for i in self.all_issues)

    def to_dict(self) -> dict[str, Any]:
        t = self.report.template
        return {
            "id": self.id,
            "name": (t.name if t else self.report.name) or self.path.stem,
            "description": t.description if t else "",
            "tags": list(t.tags) if t else [],
            "favorite": bool(t and t.favorite),
            "source": self.source,
            "overrides_builtin": self.overrides_builtin,
            "file": self.path.name,
            "valid": self.valid,
            "sections": [{"id": s.id, "title": s.title, "kind": s.kind} for s in t.sections]
            if t
            else [],
            "issues": [i.to_dict() for i in self.all_issues],
        }


def builtin_dir() -> Path:
    return Path(str(resources.files(BUILTIN_PACKAGE)))


def builtin_files() -> list[Path]:
    return sorted(p for p in builtin_dir().glob("*.md") if _is_template_name(p.name))


def _is_template_name(name: str) -> bool:
    return name.endswith(".md") and not name.startswith((".", "_"))


def vault_templates_dir(vault_root: Path, subfolder: str, *, create: bool = False) -> Path:
    """The templates folder, confined to the vault (S4)."""
    if create:
        return ensure_folder(vault_root, subfolder)
    return confine(vault_root, subfolder)


def _vault_files(folder: Path, vault_root: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    out = []
    for p in sorted(folder.iterdir()):
        if not _is_template_name(p.name) or not p.is_file():
            continue
        if not is_inside(vault_root, p):  # a symlink out of the vault
            log.warning("Ignoring template %s: it resolves outside the vault", p.name)
            continue
        out.append(p)
    return out


@dataclass
class TemplateLibrary:
    """Every template the app can see, keyed by id (vault before built-in)."""

    entries: list[TemplateEntry] = field(default_factory=list)

    def by_id(self) -> dict[str, TemplateEntry]:
        """The effective, valid template for each id."""
        out: dict[str, TemplateEntry] = {}
        for e in self.entries:
            if not e.valid or e.id is None:
                continue
            current = out.get(e.id)
            if current is None or (current.source == "builtin" and e.source == "vault"):
                out[e.id] = e
        return out

    def get(self, template_id: str) -> Template:
        entry = self.by_id().get(template_id)
        if entry is None or entry.template is None:
            broken = [e for e in self.entries if e.id == template_id and not e.valid]
            if broken:
                first = broken[0].all_issues[0] if broken[0].all_issues else None
                raise MM3Error(
                    E_TEMPLATE_INVALID,
                    f"The template '{template_id}' ({broken[0].path.name}) is invalid"
                    + (f": {first}" if first else "."),
                    "Fix the file (see `mm3 templates validate`) or choose another template.",
                    status_code=422,
                )
            raise MM3Error(
                E_TEMPLATE_NOT_FOUND,
                f"There is no template with the id '{template_id}'.",
                f"Available: {', '.join(sorted(self.by_id())) or 'none'}.",
                status_code=404,
            )
        return entry.template

    def listing(self) -> list[TemplateEntry]:
        """Effective templates plus every invalid file; favourites first, then by name."""
        effective = self.by_id()
        shown = [e for e in self.entries if not e.valid or effective.get(e.id or "") is e]

        def key(e: TemplateEntry) -> tuple[int, int, str]:
            t = e.template
            return (
                0 if e.valid else 1,
                0 if t and t.favorite else 1,
                (t.name if t else "").lower(),
            )

        return sorted(shown, key=key)


def load_library(vault_root: Path | None = None, subfolder: str | None = None) -> TemplateLibrary:
    """Load the built-ins and, when a vault is given, its templates folder."""
    entries = [TemplateEntry("builtin", p, parse_template_file(p)) for p in builtin_files()]
    builtin_ids = {e.id for e in entries if e.valid}
    if vault_root is not None and subfolder:
        try:
            folder = vault_templates_dir(vault_root, subfolder)
        except MM3Error as exc:
            log.warning("Templates folder unusable: %s", exc.message)
            folder = None
        if folder is not None:
            vault = [
                TemplateEntry("vault", p, parse_template_file(p))
                for p in _vault_files(folder, vault_root)
            ]
            counts: dict[str, int] = {}
            for e in vault:
                if e.id and e.report.ok:
                    counts[e.id] = counts.get(e.id, 0) + 1
            for e in vault:
                issues: tuple[TemplateIssue, ...] = ()
                if e.id and counts.get(e.id, 0) > 1:
                    issues = (
                        TemplateIssue(
                            "duplicate_template_id",
                            f"Another file in the templates folder also has the id '{e.id}'.",
                        ),
                    )
                entries.append(
                    TemplateEntry(
                        "vault", e.path, e.report, overrides_builtin=e.id in builtin_ids,
                        issues=issues,
                    )
                )  # fmt: skip
    return TemplateLibrary(entries)


def load_builtin(template_id: str) -> Template:
    return load_library().get(template_id)


# -- installation -----------------------------------------------------------------------------


@dataclass(frozen=True)
class InstallResult:
    file: str
    action: Literal["installed", "updated", "unchanged", "kept"]
    """``kept``: the vault copy differs from what MM3 installed, so the user's edit stays."""

    def to_dict(self) -> dict[str, str]:
        return {"file": self.file, "action": self.action}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_manifest(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    files = data.get("files") if isinstance(data, dict) else None
    return {str(k): str(v) for k, v in files.items()} if isinstance(files, dict) else {}


def record_installed(manifest_path: Path, file_name: str, data: bytes) -> None:
    """Record that ``file_name`` now holds exactly the shipped ``data`` (after a reset), so a
    later app update may refresh it while the user has not edited it again."""
    manifest = _read_manifest(manifest_path)
    manifest[file_name] = _sha(data)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        manifest_path,
        json.dumps({"version": 1, "files": manifest}, indent=2, sort_keys=True) + "\n",
        overwrite=True,
    )


def install_builtins(
    vault_root: Path, subfolder: str, manifest_path: Path, *, add_missing: bool = True
) -> list[InstallResult]:
    """Copy the built-in templates into the vault's templates folder.

    A missing file is written (unless ``add_missing`` is false: a built-in the user deleted is
    not brought back by an upgrade). An existing file is replaced only when its bytes equal the
    hash MM3 recorded when it last installed that file (the user never edited it) and the
    shipped version changed. Everything else is left alone.
    """
    folder = vault_templates_dir(vault_root, subfolder, create=True)
    manifest = _read_manifest(manifest_path)
    results: list[InstallResult] = []
    for src in builtin_files():
        shipped = src.read_bytes()
        target = folder / src.name
        if not target.exists():
            if not add_missing:
                continue
            atomic_write_text(target, shipped.decode("utf-8"), vault_root=vault_root)
            manifest[src.name] = _sha(shipped)
            results.append(InstallResult(src.name, "installed"))
            continue
        current = target.read_bytes()
        if current == shipped:
            manifest[src.name] = _sha(shipped)
            results.append(InstallResult(src.name, "unchanged"))
        elif manifest.get(src.name) == _sha(current):
            atomic_write_text(
                target, shipped.decode("utf-8"), overwrite=True, vault_root=vault_root
            )
            manifest[src.name] = _sha(shipped)
            results.append(InstallResult(src.name, "updated"))
        else:
            results.append(InstallResult(src.name, "kept"))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        manifest_path,
        json.dumps({"version": 1, "files": manifest}, indent=2, sort_keys=True) + "\n",
        overwrite=True,
    )
    return results


def ensure_installed(vault_root: Path, subfolder: str, manifest_path: Path) -> bool:
    """First-run install: copy the built-ins when the templates folder does not exist yet.
    Afterwards, refresh the copies the user never edited when a new app version ships a changed
    built-in (Phase 15a added Summary Detailed this way). Returns True when it changed a file."""
    try:
        folder = vault_templates_dir(vault_root, subfolder)
    except MM3Error:
        return False
    if folder.exists():
        results = install_builtins(vault_root, subfolder, manifest_path, add_missing=False)
        return any(r.action == "updated" for r in results)
    install_builtins(vault_root, subfolder, manifest_path)
    return True


def newer_builtins(vault_root: Path, subfolder: str, manifest_path: Path) -> set[str]:
    """Built-in file names whose vault copy the user edited while the shipped version changed
    since MM3 installed it: the library offers "Reset to default" to get the new version."""
    try:
        folder = vault_templates_dir(vault_root, subfolder)
    except MM3Error:
        return set()
    manifest = _read_manifest(manifest_path)
    out = set()
    for src in builtin_files():
        target = folder / src.name
        installed = manifest.get(src.name)
        if installed is None or not target.is_file():
            continue
        shipped = _sha(src.read_bytes())
        if installed != shipped and _sha(target.read_bytes()) not in (installed, shipped):
            out.add(src.name)
    return out
