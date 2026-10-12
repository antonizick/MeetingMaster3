"""Optional copy of a job's retained Opus audio into the vault (R8).

Controlled by ``privacy.copy_audio_to_vault``.
The audio goes to ``vault.attachments_subfolder`` next to a name derived from the note, and the
note's ``mm3-audio`` frontmatter key is set to a wikilink target so Obsidian can play it. Nothing
here runs unless the user turned the setting on, and a failure never fails the job.
"""

from __future__ import annotations

import contextlib
import errno
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.files import OPUS_NAME, job_dir
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.note_writer import render_note
from meetingmaster3.storage.repositories import JobRecord
from meetingmaster3.vault.io import atomic_write_text, read_text
from meetingmaster3.vault.paths import ensure_folder, is_inside, resolve_vault_root

log = logging.getLogger(__name__)

WRITTEN_FILE = "written.json"  # same name as templates.stages.WRITTEN_FILE (no import cycle)


def copy_audio_to_vault(jobs_root: Path, job: JobRecord, settings: Settings) -> str | None:
    """Copy ``audio.opus`` into the vault and link it from the note. Returns the vault-relative
    path of the copy, or ``None`` when there is nothing to do or it failed (logged)."""
    if not settings.privacy.copy_audio_to_vault or settings.vault.path is None:
        return None
    try:
        return _copy(jobs_root, job, settings)
    except (MM3Error, OSError, ValueError) as exc:
        log.warning("Audio was not copied to the vault for job %s: %s", job.id, exc)
        return None


def _place(tmp: Path, folder: Path, stem: str) -> Path:
    """Move ``tmp`` to ``<stem>.opus`` in ``folder``, or ``<stem> (2).opus``... if taken: an
    existing file is never replaced (S4, R13)."""
    for n in range(1, 1000):
        target = folder / (f"{stem}.opus" if n == 1 else f"{stem} ({n}).opus")
        try:
            os.link(tmp, target)  # atomic "create if absent"
            return target
        except FileExistsError:
            continue
        except OSError as exc:  # no hard links (exFAT, some FUSE mounts)
            if exc.errno not in (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV):
                raise
            if not os.path.lexists(target):
                os.replace(tmp, target)
                return target
    raise MM3Error("vault_file_exists", f"Too many recordings named {stem!r}.", "")


def _copy(jobs_root: Path, job: JobRecord, settings: Settings) -> str | None:
    folder = job_dir(jobs_root, job.id)
    source = folder / OPUS_NAME
    written = folder / WRITTEN_FILE
    if not source.is_file() or not written.is_file():
        return None
    info = json.loads(written.read_text(encoding="utf-8"))
    root = resolve_vault_root(settings.vault.path)
    note_path = Path(info["note_path"])
    if not note_path.is_file() or not is_inside(root, note_path):
        return None
    parsed = parse_note(read_text(note_path))
    linked = parsed.note.meta.audio_ref
    if linked and (root / linked).is_file() and is_inside(root, root / linked):
        return linked  # already copied (the write stage ran again after a crash)
    target_dir = ensure_folder(root, settings.vault.attachments_subfolder)
    fd, tmp = tempfile.mkstemp(dir=target_dir, prefix=".audio-", suffix=".mm3tmp")
    try:
        with os.fdopen(fd, "wb") as out, open(source, "rb") as src:
            shutil.copyfileobj(src, out)
        target = _place(Path(tmp), target_dir, note_path.stem)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
    if not is_inside(root, target):  # pragma: no cover - ensure_folder confined the folder
        target.unlink(missing_ok=True)
        return None
    relative = target.relative_to(root).as_posix()
    meta = parsed.note.meta.model_copy(update={"audio_ref": relative})
    atomic_write_text(
        note_path,
        render_note(parsed.note.with_meta(meta), parsed),
        overwrite=True,
        vault_root=root,
    )
    return relative
