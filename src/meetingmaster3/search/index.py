"""Keep ``search.db`` in step with the vault (Phase 15i, R30).

An update is incremental. It walks the vault, compares each indexable file with the document
stored for its path (mtime and size first, then sha256), and re-chunks only what changed. A file
that moved without changing (same ``mm3-id``, kind and sha256 under a new path) is re-pointed and
keeps its vectors. Documents whose file is gone are dropped (unless the walk was cut short).
Passages whose text is unchanged keep their vector when their document is re-chunked, so saving
one section re-embeds only that section.

Then every passage without a vector of the current embedding model is embedded, in batches.
With a local embedder, each batch waits for the GPU gate (the job runner's GPU, only while no job
is active), so indexing never competes with a transcription (R5). If the embedder is not
available (Ollama stopped, the model not pulled, no consent for a cloud embedder) the word index
is still complete and the reason is recorded for the status.

What is indexed (one place, so it can be widened later): live MM3 notes and companion
transcripts. Skipped: readable transcripts, archived copies, Ask answers (``mm3-kind: answer``),
files without ``mm3-id``, hidden folders and files, symlinks and anything outside the vault (S4).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import logging
import os
import re
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from meetingmaster3.config.settings import Settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.markdown.note_parser import NoteParseError
from meetingmaster3.markdown.transcript_format import TranscriptParseError
from meetingmaster3.search.chunking import Chunked, chunk_note, chunk_transcript
from meetingmaster3.search.embedder import EmbedderChoice
from meetingmaster3.search.store import DocumentInfo, SearchStore, StoredDocument
from meetingmaster3.vault.io import read_text
from meetingmaster3.vault.naming import NOTE_SUFFIX, TRANSCRIPT_SUFFIX
from meetingmaster3.vault.paths import is_inside
from meetingmaster3.vault.picker import NoteInfo, read_identity

log = logging.getLogger(__name__)

MAX_FILES = 50_000
"""Markdown files examined in one walk (as ``vault.relink``); beyond it nothing is dropped."""
EMBED_BATCH = 32
"""Passages per embedding call (and per hold of the GPU gate)."""
SKIPPED_KINDS = frozenset({"answer", "readable-transcript"})
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b")

Progress = Callable[[float, str], None]


class GpuGate(Protocol):
    """Something that hands out the GPU between jobs (``JobRunner.background_gpu``)."""

    def hold(self) -> AbstractAsyncContextManager[None]: ...


class NoGate:
    """No GPU sharing to respect (a cloud embedder, or the CLI's own gate)."""

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        yield


def indexable(info: NoteInfo | None, name: str, *, transcripts: bool) -> str | None:
    """``"note"``, ``"transcript"`` or ``None`` (not indexed) for a vault file."""
    if info is None or info.archived or info.is_readable or info.kind in SKIPPED_KINDS:
        return None
    if info.is_note:
        return "note"
    if transcripts and info.is_transcript and name.endswith(TRANSCRIPT_SUFFIX):
        return "transcript"
    return None


@dataclass(frozen=True)
class VaultFile:
    path: Path
    rel: str
    kind: str
    mm3_id: str
    mtime_ns: int
    size: int


@dataclass
class Scan:
    files: list[VaultFile] = field(default_factory=list)
    truncated: bool = False


@dataclass
class UpdateReport:
    added: int = 0
    updated: int = 0
    moved: int = 0
    removed: int = 0
    unchanged: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    """``(vault-relative path, message)`` of files that could not be indexed."""
    embedded: int = 0
    vectors_missing: int = 0
    vector_error: MM3Error | None = None
    truncated: bool = False
    seconds: float = 0.0
    embed_seconds: float = 0.0

    @property
    def changed(self) -> int:
        return self.added + self.updated + self.moved + self.removed


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


class Indexer:
    def __init__(
        self,
        store: SearchStore,
        settings: Settings,
        embedder: Callable[[], EmbedderChoice] | None = None,
        gate: GpuGate | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.embedder = embedder
        self.gate = gate or NoGate()
        self._skip: dict[str, tuple[int, int]] = {}
        """Files known not to be indexable, by path, with the (mtime, size) they had."""

    # -- walking the vault -------------------------------------------------------------------

    def scan(self, root: Path, known: dict[str, StoredDocument]) -> Scan:
        scan = Scan()
        seen = 0
        transcripts = self.settings.search.index_transcripts
        for folder, dirs, files in os.walk(root):
            dirs[:] = sorted(
                d for d in dirs if not d.startswith(".") and not os.path.islink(Path(folder) / d)
            )
            for name in sorted(files):
                if not name.endswith(NOTE_SUFFIX) or name.startswith("."):
                    continue
                seen += 1
                if seen > MAX_FILES:
                    scan.truncated = True
                    return scan
                path = Path(folder) / name
                try:
                    st = path.lstat()
                except OSError:
                    continue
                if path.is_symlink() or not is_inside(root, path):
                    continue
                rel = path.relative_to(root).as_posix()
                stamp = (st.st_mtime_ns, st.st_size)
                doc = known.get(rel)
                if doc is not None and doc.kind == "transcript" and not transcripts:
                    continue  # transcripts were switched off: the stored one goes
                if doc is not None and (doc.mtime_ns, doc.size) == stamp:
                    scan.files.append(VaultFile(path, rel, doc.kind, doc.mm3_id, *stamp))
                    continue
                if self._skip.get(rel) == stamp:
                    continue
                info = read_identity(path)
                kind = indexable(info, name, transcripts=transcripts)
                if kind is None or info is None:
                    self._skip[rel] = stamp
                    continue
                self._skip.pop(rel, None)
                scan.files.append(VaultFile(path, rel, kind, info.mm3_id, *stamp))
        return scan

    # -- the word index ----------------------------------------------------------------------

    def _chunk(self, f: VaultFile, text: str, notes: dict[str, tuple[str, str | None]]) -> Chunked:
        cfg = self.settings.search
        if f.kind == "note":
            return chunk_note(
                text,
                chunk_tokens=cfg.chunk_tokens,
                overlap=cfg.chunk_overlap,
                fallback_title=f.path.name.removesuffix(NOTE_SUFFIX),
            )
        title, date = notes.get(f.mm3_id, (None, None))
        if date is None and (m := _DATE_PREFIX_RE.match(f.path.name)):
            date = m.group(1)
        return chunk_transcript(
            text, chunk_tokens=cfg.chunk_tokens, overlap=cfg.chunk_overlap, title=title, date=date
        )

    def sync_files(self, root: Path, report: UpdateReport) -> None:
        """Bring documents and passages up to date with the vault (no embedding). Sync: runs in
        a worker thread."""
        known = {d.path: d for d in self.store.documents()}
        scan = self.scan(root, known)
        report.truncated = scan.truncated
        present = {f.rel for f in scan.files}
        gone = {} if scan.truncated else {p: d for p, d in known.items() if p not in present}
        notes = {d.mm3_id: (d.title, d.date) for d in known.values() if d.kind == "note"}
        now = _now()
        # Notes first: a transcript takes its title and date from its note.
        for f in sorted(scan.files, key=lambda f: f.kind != "note"):
            doc = known.get(f.rel)
            if doc is not None and (doc.mtime_ns, doc.size) == (f.mtime_ns, f.size):
                report.unchanged += 1
                continue
            try:
                text = read_text(f.path)
            except (OSError, UnicodeDecodeError) as exc:
                report.failed.append((f.rel, f"cannot be read ({type(exc).__name__})"))
                continue
            sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if doc is not None and doc.sha256 == sha:
                self.store.touch_document(doc.id, f.mtime_ns)
                report.unchanged += 1
                continue
            if doc is None:
                twin = next(
                    (
                        g
                        for g in gone.values()
                        if (g.mm3_id, g.kind, g.sha256) == (f.mm3_id, f.kind, sha)
                    ),
                    None,
                )
                if twin is not None:  # moved or renamed without a change: keep its vectors
                    self.store.move_document(twin.id, f.rel, f.mtime_ns, now)
                    del gone[twin.path]
                    report.moved += 1
                    continue
            try:
                chunked = self._chunk(f, text, notes)
            except (NoteParseError, TranscriptParseError, MM3Error, ValueError) as exc:
                message = exc.message if isinstance(exc, MM3Error) else type(exc).__name__
                report.failed.append((f.rel, message))
                if doc is not None:
                    self.store.delete_documents([doc.id])
                continue
            if chunked.kind == "note":
                notes[chunked.mm3_id] = (chunked.title, chunked.date)
            info = DocumentInfo(
                mm3_id=chunked.mm3_id,
                kind=chunked.kind,
                path=f.rel,
                title=chunked.title,
                date=chunked.date,
                participants=chunked.participants,
                speakers=chunked.speakers,
                sha256=sha,
                mtime_ns=f.mtime_ns,
                size=f.size,
            )
            self.store.put_document(info, chunked.passages, now)
            if doc is None:
                report.added += 1
            else:
                report.updated += 1
        self.store.delete_documents([d.id for d in gone.values()])
        report.removed += len(gone)

    # -- vectors -----------------------------------------------------------------------------

    async def embed_missing(self, report: UpdateReport, progress: Progress | None = None) -> None:
        if self.embedder is None:
            return
        try:
            choice = self.embedder()
            choice.require_consent()
        except MM3Error as exc:
            report.vector_error = exc
            report.vectors_missing = await asyncio.to_thread(self.store.count_without_vectors)
            return
        if await asyncio.to_thread(self.store.drop_vectors_not_of, choice.model_id):
            log.info("Search index: vectors of another embedding model were dropped")
        total = await asyncio.to_thread(self.store.count_without_vectors)
        gate = self.gate if choice.is_local else NoGate()
        started = time.monotonic()
        done = 0
        try:
            while True:
                batch = await asyncio.to_thread(self.store.passages_without_vectors, EMBED_BATCH)
                if not batch:
                    break
                async with gate.hold():
                    vectors = await choice.embed_documents([text for _, text in batch])
                await asyncio.to_thread(
                    self.store.put_vectors,
                    choice.model_id,
                    [(pid, vec) for (pid, _), vec in zip(batch, vectors, strict=True)],
                )
                done += len(batch)
                if progress is not None and total:
                    progress(done / total, f"Embedded {done} of {total} passages")
        except MM3Error as exc:
            report.vector_error = exc
        report.embedded += done
        report.embed_seconds += time.monotonic() - started
        report.vectors_missing = await asyncio.to_thread(self.store.count_without_vectors)
        if done:
            dims = await asyncio.to_thread(self._dims, choice.model_id)
            await asyncio.to_thread(
                self.store.set_meta, embed_model=choice.model_id, dims=str(dims) if dims else None
            )

    def _dims(self, model_id: str) -> int | None:
        row = self.store.fetchone("SELECT dims FROM vectors WHERE model = ? LIMIT 1", (model_id,))
        return int(row["dims"]) if row else None

    # -- both --------------------------------------------------------------------------------

    async def update(self, root: Path, progress: Progress | None = None) -> UpdateReport:
        started = time.monotonic()
        report = UpdateReport()
        if progress is not None:
            progress(0.0, "Reading the vault")
        await asyncio.to_thread(self.sync_files, root, report)

        def vectors_progress(fraction: float, message: str) -> None:
            if progress is not None:
                progress(0.1 + 0.9 * fraction, message)

        if progress is not None:
            progress(0.1, "Embedding passages")
        await self.embed_missing(report, vectors_progress)
        report.seconds = time.monotonic() - started
        error = report.vector_error
        await asyncio.to_thread(
            self.store.set_meta,
            last_update=_now(),
            last_seconds=f"{report.seconds:.1f}",
            vector_error=f"{error.message} {error.hint}".strip() if error else None,
            vector_error_code=error.code if error else None,
            failed=str(len(report.failed)) if report.failed else None,
            truncated="1" if report.truncated else None,
        )
        return report
