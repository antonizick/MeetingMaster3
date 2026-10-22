"""Atomic, non-clobbering text writes and exact reads for vault files (S4)."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from meetingmaster3.errors import MM3Error
from meetingmaster3.vault.changes import vault_changed
from meetingmaster3.vault.paths import is_inside

NEW_FILE_MODE = 0o644
TEMP_SUFFIX = ".mm3tmp"


def read_text(path: Path) -> str:
    """Read UTF-8 text exactly as stored: no newline translation (``\\r\\n`` is kept)."""
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def _fsync_dir(folder: Path) -> None:
    with contextlib.suppress(OSError):
        fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _exists_error(path: Path) -> MM3Error:
    return MM3Error(
        "vault_file_exists",
        f"{path.name!r} already exists, and MeetingMaster3 never overwrites a note silently.",
        "Choose another title, or explicitly confirm that the existing file may be replaced.",
        status_code=409,
    )


def atomic_write_text(
    path: Path, text: str, *, overwrite: bool = False, vault_root: Path | None = None
) -> Path:
    """Write ``text`` to ``path`` atomically: a temporary file in the same folder is written,
    fsynced and then moved into place, so readers (and Obsidian sync) never see a partial file.

    Without ``overwrite=True`` an existing file is never replaced (``vault_file_exists``).
    With ``vault_root``, the target must resolve inside the vault. The temporary file is removed
    on success and on failure.
    """
    folder = path.parent
    if vault_root is not None and not (
        is_inside(vault_root, folder) and is_inside(vault_root, path)
    ):
        raise MM3Error(
            "vault_path_escape",
            f"The path {str(path)!r} is outside the vault.",
            "Write only inside the configured vault.",
        )
    if not overwrite and os.path.lexists(path):
        raise _exists_error(path)
    try:
        mode = stat.S_IMODE(path.stat().st_mode) if overwrite and path.exists() else NEW_FILE_MODE
    except OSError:  # pragma: no cover - racing deletion
        mode = NEW_FILE_MODE
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=TEMP_SUFFIX, dir=folder)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        if overwrite:
            os.replace(tmp, path)
        else:
            try:
                os.link(tmp, path)  # atomic "create if absent"
            except FileExistsError as exc:
                raise _exists_error(path) from exc
            except OSError as exc:  # filesystems without hard links (exFAT, some FUSE mounts)
                if exc.errno not in (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV):
                    raise
                if os.path.lexists(path):
                    raise _exists_error(path) from exc
                os.replace(tmp, path)
        _fsync_dir(folder)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
    if path.suffix == ".md":
        vault_changed(path)  # the search index updates itself (listeners ignore other folders)
    return path


@dataclass(frozen=True)
class FileFingerprint:
    """Identifies a file version, to detect edits made outside MM3 (Phase 11)."""

    mtime_ns: int
    size: int
    sha256: str


def fingerprint(path: Path) -> FileFingerprint:
    data = path.read_bytes()
    st = path.stat()
    return FileFingerprint(st.st_mtime_ns, st.st_size, hashlib.sha256(data).hexdigest())
