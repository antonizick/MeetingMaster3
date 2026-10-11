"""Vault root validation, output-folder templates and path confinement (S4).

Every path MM3 writes is resolved (symlinks included) and must stay inside the vault root.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path, PurePath

from meetingmaster3.errors import MM3Error

_PLACEHOLDERS = {"{yyyy}": "%Y", "{mm}": "%m", "{dd}": "%d"}


def resolve_vault_root(path: str | os.PathLike[str] | None) -> Path:
    """The vault root as a resolved, existing, writable directory."""
    if path is None or not str(path).strip():
        raise MM3Error(
            "vault_not_configured",
            "No Obsidian vault is configured.",
            "Choose your vault folder in Settings (or set MM3_VAULT__PATH).",
        )
    try:
        root = Path(path).expanduser().resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise MM3Error(
            "vault_missing",
            f"The vault folder {str(path)!r} does not exist.",
            "Check the path in Settings, or mount the drive or sync folder that holds the vault.",
        ) from exc
    if not root.is_dir():
        raise MM3Error(
            "vault_not_a_directory",
            f"The vault path {str(root)!r} is not a folder.",
            "Choose the vault's top-level folder (the one that contains .obsidian/).",
        )
    if not os.access(root, os.W_OK | os.X_OK):
        raise MM3Error(
            "vault_unwritable",
            f"MeetingMaster3 cannot write to the vault folder {str(root)!r}.",
            "Fix the folder's permissions, or run MeetingMaster3 as the vault's owner.",
        )
    return root


def expand_folder_template(template: str, when: dt.date) -> str:
    """Fill ``{yyyy}``, ``{mm}`` and ``{dd}`` in an output-folder template."""
    out = template
    for placeholder, fmt in _PLACEHOLDERS.items():
        out = out.replace(placeholder, when.strftime(fmt))
    unknown = re.search(r"\{[^}]*\}", out)
    if unknown:
        raise MM3Error(
            "vault_folder_template_invalid",
            f"Unknown placeholder {unknown.group()!r} in the output folder {template!r}.",
            "Use only {yyyy}, {mm} and {dd}.",
        )
    return out


def _escape(relative: object) -> MM3Error:
    return MM3Error(
        "vault_path_escape",
        f"The path {str(relative)!r} is outside the vault.",
        "Use a folder inside the vault. Paths that leave the vault through '..' or a "
        "symbolic link are refused.",
    )


def is_inside(root: Path, path: Path) -> bool:
    """Whether ``path`` (resolved, following symlinks) is ``root`` or inside it."""
    return path.resolve().is_relative_to(root)


def confine(root: Path, relative: str | PurePath) -> Path:
    """Resolve ``relative`` against the (already resolved) vault ``root`` and refuse anything
    that is absolute or resolves outside it."""
    rel = PurePath(relative)
    if "\x00" in str(relative) or rel.is_absolute() or rel.drive or str(relative).startswith("~"):
        raise _escape(relative)
    candidate = (root / rel).resolve()
    if not candidate.is_relative_to(root):
        raise _escape(relative)
    return candidate


def ensure_folder(root: Path, relative: str | PurePath) -> Path:
    """Create a folder inside the vault (and its parents) and return its resolved path."""
    folder = confine(root, relative)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except FileExistsError as exc:
        raise MM3Error(
            "vault_folder_blocked",
            f"{str(relative)!r} exists in the vault but is not a folder.",
            "Rename that file or choose another output folder.",
        ) from exc
    except PermissionError as exc:
        raise MM3Error(
            "vault_unwritable",
            f"MeetingMaster3 cannot create the folder {str(relative)!r} in the vault.",
            "Fix the vault's permissions.",
        ) from exc
    if not is_inside(root, folder):  # pragma: no cover - a symlink swapped in during mkdir
        raise _escape(relative)
    return folder


def output_folder(root: Path, template: str, when: dt.date) -> Path:
    """The meeting's output folder (``vault.output_subfolder`` with placeholders filled)."""
    return ensure_folder(root, expand_folder_template(template, when))
