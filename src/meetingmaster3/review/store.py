"""Per-meeting working files of the review workspace, kept in the app data folder (not the vault).

``<data>/reviews/<mm3-id>/``

* ``base-<sha>.md``: the note text a workspace was opened from. Saves are joined against it and
  compared with the file on disk to detect edits made elsewhere. The newest few are kept.
* ``draft.json``: the editor's unsaved parts (autosaved, debounced) with the base they apply to.
* ``pending-<token>.md``: a template switch that is waiting for the user's confirmation.

The folder is created ``0700``; it holds meeting content, like the job folders.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.editing import Edits
from meetingmaster3.vault.io import atomic_write_text, read_text

REVIEWS_DIR = "reviews"
KEEP_BASES = 5
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def text_sha(text: str) -> str:
    """The SHA-256 of ``text`` as UTF-8: equal to ``vault.io.fingerprint(path).sha256`` of a
    file read with ``read_text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Draft:
    base_sha: str
    edits: Edits
    saved_at: dt.datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_sha": self.base_sha,
            "saved_at": self.saved_at.isoformat(),
            "texts": list(self.edits.texts),
            "sections": dict(self.edits.sections),
            "frontmatter": self.edits.frontmatter,
        }


class ReviewStore:
    def __init__(self, data_dir: Path, mm3_id: str | uuid.UUID) -> None:
        self.folder = data_dir / REVIEWS_DIR / str(uuid.UUID(str(mm3_id)))

    def _ensure(self) -> Path:
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            os.chmod(self.folder, 0o700)
        return self.folder

    # -- bases --------------------------------------------------------------------------------

    def put_base(self, text: str) -> str:
        sha = text_sha(text)
        path = self._ensure() / f"base-{sha}.md"
        if not path.exists():
            atomic_write_text(path, text, overwrite=True)
        os.utime(path)
        bases = sorted(self.folder.glob("base-*.md"), key=lambda p: p.stat().st_mtime_ns)
        for old in bases[:-KEEP_BASES]:
            with contextlib.suppress(OSError):
                old.unlink()
        return sha

    def base(self, sha: str) -> str | None:
        if not _SHA_RE.match(sha):
            return None
        path = self.folder / f"base-{sha}.md"
        return read_text(path) if path.is_file() else None

    # -- drafts -------------------------------------------------------------------------------

    def save_draft(self, base_sha: str, edits: Edits, when: dt.datetime | None = None) -> Draft:
        draft = Draft(base_sha, edits, when or dt.datetime.now(dt.UTC).replace(microsecond=0))
        atomic_write_text(
            self._ensure() / "draft.json", json.dumps(draft.to_dict()) + "\n", overwrite=True
        )
        return draft

    def draft(self) -> Draft | None:
        path = self.folder / "draft.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Draft(
                str(data["base_sha"]),
                Edits.from_dict(data),
                dt.datetime.fromisoformat(data["saved_at"]),
            )
        except (ValueError, KeyError, TypeError, MM3Error):  # a damaged draft is dropped
            self.clear_draft()
            return None

    def clear_draft(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            (self.folder / "draft.json").unlink()

    # -- pending template switches ----------------------------------------------------------

    def put_pending(self, base_sha: str, text: str, info: dict[str, Any]) -> str:
        token = secrets.token_hex(16)
        folder = self._ensure()
        for old in folder.glob("pending-*"):
            with contextlib.suppress(OSError):
                old.unlink()
        atomic_write_text(folder / f"pending-{token}.md", text, overwrite=True)
        meta = {"base_sha": base_sha, **info}
        atomic_write_text(folder / f"pending-{token}.json", json.dumps(meta) + "\n", overwrite=True)
        return token

    def pending(self, token: str) -> tuple[str, dict[str, Any]] | None:
        if not _TOKEN_RE.match(token):
            return None
        text_path = self.folder / f"pending-{token}.md"
        meta_path = self.folder / f"pending-{token}.json"
        if not (text_path.is_file() and meta_path.is_file()):
            return None
        return read_text(text_path), json.loads(meta_path.read_text(encoding="utf-8"))

    def clear_pending(self) -> None:
        for old in self.folder.glob("pending-*"):
            with contextlib.suppress(OSError):
                old.unlink()

    def remove(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)
