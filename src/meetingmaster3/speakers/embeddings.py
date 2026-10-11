"""Per-speaker voice embeddings: choose clean speech, embed it, average to one centroid.

Selection is pure Python and works from the diarization turns (``diarization.json``) or, when
those are missing, from the transcript's segments. For each speaker it keeps the parts of its turns
that no other speaker overlaps, drops pieces shorter than ``min_segment`` seconds, cuts long pieces
into windows of at most ``max_segment`` seconds, and takes the longest windows until about
``target_seconds`` of speech (at most ``max_segments`` windows) are chosen.

:class:`PyannoteEmbedder` embeds those windows with the WeSpeaker ResNet34 model that the pinned
diarization pipeline (``pyannote/speaker-diarization-community-1``) ships in its ``embedding/``
folder, loaded from the local model cache (never from the network). The windows' embeddings are
averaged (weighted by duration) and L2-normalised into one centroid per speaker.
"""

from __future__ import annotations

import hashlib
import logging
import wave
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from meetingmaster3.speakers.vectors import Vector, normalize, weighted_mean

if TYPE_CHECKING:
    from meetingmaster3.domain.transcript import Transcript

log = logging.getLogger(__name__)

MIN_SEGMENT_SECONDS = 2.0
MAX_SEGMENT_SECONDS = 10.0
TARGET_SECONDS = 45.0
MAX_SEGMENTS = 12
CONFIDENT_SECONDS = 10.0
"""Less clean speech than this (in the chosen windows) marks a speaker ``low_confidence``."""
SNIPPETS = 3
SNIPPET_SECONDS = 6.0


@dataclass(frozen=True, order=True)
class Interval:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, float]:
        return {"start": round(self.start, 2), "end": round(self.end, 2)}


@dataclass(frozen=True)
class LabelledTurn:
    start: float
    end: float
    speaker: str


def turns_from(diarization: dict[str, Any] | None, transcript: Transcript) -> list[LabelledTurn]:
    """Diarization turns (overlap-aware) when available, else the transcript's segments."""
    raw = (diarization or {}).get("turns") or []
    turns = [
        LabelledTurn(float(t["start"]), float(t["end"]), str(t["speaker"]))
        for t in raw
        if isinstance(t, dict) and t.get("speaker") and float(t["end"]) > float(t["start"])
    ]
    if turns:
        return turns
    return [
        LabelledTurn(s.start, s.end, s.speaker_label)
        for s in transcript.segments
        if s.speaker_label and s.end > s.start
    ]


def union(intervals: Iterable[Interval]) -> list[Interval]:
    """Sorted, merged intervals."""
    out: list[Interval] = []
    for iv in sorted(intervals):
        if iv.duration <= 0:
            continue
        if out and iv.start <= out[-1].end:
            out[-1] = Interval(out[-1].start, max(out[-1].end, iv.end))
        else:
            out.append(iv)
    return out


def subtract(keep: list[Interval], remove: list[Interval]) -> list[Interval]:
    """``keep`` minus ``remove`` (both sorted and merged)."""
    out: list[Interval] = []
    j = 0
    for iv in keep:
        start = iv.start
        while j < len(remove) and remove[j].end <= start:
            j += 1
        k = j
        while k < len(remove) and remove[k].start < iv.end:
            if remove[k].start > start:
                out.append(Interval(start, remove[k].start))
            start = max(start, remove[k].end)
            k += 1
        if start < iv.end:
            out.append(Interval(start, iv.end))
    return out


def clean_intervals(turns: Sequence[LabelledTurn], label: str) -> list[Interval]:
    """Where ``label`` speaks and nobody else does."""
    own = union(Interval(t.start, t.end) for t in turns if t.speaker == label)
    others = union(Interval(t.start, t.end) for t in turns if t.speaker != label)
    return subtract(own, others)


def split_long(iv: Interval, max_seconds: float) -> list[Interval]:
    """Cut ``iv`` into equal windows of at most ``max_seconds``."""
    if iv.duration <= max_seconds:
        return [iv]
    n = int(-(-iv.duration // max_seconds))  # ceil
    step = iv.duration / n
    return [Interval(iv.start + i * step, iv.start + (i + 1) * step) for i in range(n)]


def select_segments(
    intervals: Sequence[Interval],
    *,
    min_seconds: float = MIN_SEGMENT_SECONDS,
    max_seconds: float = MAX_SEGMENT_SECONDS,
    target_seconds: float = TARGET_SECONDS,
    max_segments: int = MAX_SEGMENTS,
) -> list[Interval]:
    """The longest clean windows, up to ``target_seconds`` in total, in time order."""
    windows = [
        w for iv in intervals if iv.duration >= min_seconds for w in split_long(iv, max_seconds)
    ]
    windows.sort(key=lambda w: (-w.duration, w.start))
    chosen: list[Interval] = []
    total = 0.0
    for w in windows:
        if len(chosen) >= max_segments or total >= target_seconds:
            break
        chosen.append(w)
        total += w.duration
    return sorted(chosen)


def pick_snippets(
    intervals: Sequence[Interval],
    fallback: Sequence[Interval] = (),
    *,
    count: int = SNIPPETS,
    seconds: float = SNIPPET_SECONDS,
    spacing: float = 30.0,
) -> list[Interval]:
    """Up to ``count`` short sample clips to play in the UI: the longest clean pieces, at least
    ``spacing`` seconds apart where possible, each cut to ``seconds``, in time order."""
    pool = [iv for iv in intervals if iv.duration >= 1.0] or [
        iv for iv in fallback if iv.duration > 0
    ]
    pool = sorted(pool, key=lambda iv: (-iv.duration, iv.start))
    chosen: list[Interval] = []
    for min_gap in (spacing, 0.0):
        for iv in pool:
            if len(chosen) >= count:
                break
            if iv in chosen or any(abs(iv.start - c.start) < min_gap for c in chosen):
                continue
            chosen.append(iv)
    return sorted(Interval(c.start, min(c.end, c.start + seconds)) for c in chosen)


@dataclass
class SpeakerProfile:
    """What the confirmation screen and the matcher need about one diarized speaker."""

    label: str
    talk_seconds: float
    clean_seconds: float
    segments: list[Interval]
    snippets: list[Interval]
    embedding: Vector | None = None
    embedded_seconds: float = 0.0
    embedded_segments: int = 0
    window_embeddings: list[Vector] = field(default_factory=list, repr=False)

    @property
    def low_confidence(self) -> bool:
        return self.embedding is None or self.embedded_seconds < CONFIDENT_SECONDS

    def stats(self) -> dict[str, Any]:
        return {
            "talk_seconds": round(self.talk_seconds, 1),
            "clean_seconds": round(self.clean_seconds, 1),
            "embedded_seconds": round(self.embedded_seconds, 1),
            "embedded_segments": self.embedded_segments,
            "low_confidence": self.low_confidence,
        }


def profile_speakers(
    turns: Sequence[LabelledTurn],
    labels: Sequence[str],
    *,
    talk_seconds: dict[str, float] | None = None,
    target_seconds: float = TARGET_SECONDS,
) -> dict[str, SpeakerProfile]:
    """Talk time, clean speech, chosen embedding windows and sample snippets per label."""
    out: dict[str, SpeakerProfile] = {}
    for label in labels:
        own = union(Interval(t.start, t.end) for t in turns if t.speaker == label)
        clean = clean_intervals(turns, label)
        talk = (talk_seconds or {}).get(label)
        out[label] = SpeakerProfile(
            label=label,
            talk_seconds=float(talk) if talk is not None else sum(iv.duration for iv in own),
            clean_seconds=sum(iv.duration for iv in clean),
            segments=select_segments(clean, target_seconds=target_seconds),
            snippets=pick_snippets(clean, own),
        )
    return out


# -- embedding ---------------------------------------------------------------------------------


class Embedder(Protocol):
    model_id: str
    """Identifies the embedding space; embeddings with different ids are never compared."""

    def embed(self, audio: Path, segments: Sequence[Interval]) -> list[Vector | None]:
        """One embedding per segment (``None`` where the audio could not be embedded)."""
        ...

    def close(self) -> None: ...


CancelCheck = Callable[[], None]


def embed_profiles(
    embedder: Embedder,
    audio: Path,
    profiles: dict[str, SpeakerProfile],
    *,
    check: CancelCheck | None = None,
    progress: Callable[[float], None] | None = None,
) -> None:
    """Fill each profile's ``embedding`` (the duration-weighted, normalised centroid)."""
    todo = [p for p in profiles.values() if p.segments]
    for i, p in enumerate(todo):
        if check is not None:
            check()
        vectors = embedder.embed(audio, p.segments)
        kept = [(v, s) for v, s in zip(vectors, p.segments, strict=True) if v is not None]
        if kept:
            p.window_embeddings = [v for v, _ in kept]
            p.embedding = weighted_mean([v for v, _ in kept], [s.duration for _, s in kept])
            p.embedded_seconds = sum(s.duration for _, s in kept)
            p.embedded_segments = len(kept)
        if progress is not None:
            progress((i + 1) / len(todo))


def read_wav(path: Path, start: float, end: float) -> tuple[bytes, int]:
    """Raw 16-bit mono PCM frames of ``path`` between ``start`` and ``end`` seconds."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError("expected 16-bit mono PCM (the ingest stage's output)")
        rate = w.getframerate()
        first = max(0, min(w.getnframes(), int(start * rate)))
        last = max(first, min(w.getnframes(), int(end * rate)))
        w.setpos(first)
        return w.readframes(last - first), rate


def weights_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


class PyannoteEmbedder:
    """WeSpeaker ResNet34 (256-d) from the cached diarization pipeline's ``embedding/`` folder.

    ``model_id`` is ``<pipeline>/embedding@<sha256 of the weights, 16 hex>``, so new weights give
    a new embedding space and old voiceprints are simply not compared with it."""

    def __init__(self, embedding_dir: Path, *, pipeline: str, device: str = "cpu") -> None:
        weights = embedding_dir / "pytorch_model.bin"
        if not weights.is_file():
            raise FileNotFoundError(weights)
        self.embedding_dir = embedding_dir
        self.device = device
        self.model_id = f"{pipeline}/embedding@{weights_digest(weights)}"
        self._model: Any = None
        self._torch: Any = None

    def _load(self) -> Any:
        if self._model is None:
            import importlib

            from meetingmaster3.transcription.engine import _quiet_libraries

            _quiet_libraries()  # telemetry off and quiet loggers before pyannote is imported
            torch = importlib.import_module("torch")
            audio_model = importlib.import_module("pyannote.audio").Model
            model = audio_model.from_pretrained(str(self.embedding_dir))
            if model is None:  # pragma: no cover - pyannote returns None on failure
                raise RuntimeError("the speaker embedding model could not be loaded")
            model.eval()
            self._model = model.to(torch.device(self.device))
            self._torch = torch
        return self._model

    def embed(self, audio: Path, segments: Sequence[Interval]) -> list[Vector | None]:
        model = self._load()
        torch = self._torch
        import importlib

        np = importlib.import_module("numpy")
        out: list[Vector | None] = []
        for seg in segments:
            frames, rate = read_wav(audio, seg.start, seg.end)
            if len(frames) < 2 * rate * 0.5:  # under half a second: nothing usable
                out.append(None)
                continue
            samples = np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0
            waveform = torch.from_numpy(samples)[None, None, :].to(self._model.device)
            with torch.inference_mode():
                vec = model(waveform)[0].float().cpu().numpy().tolist()
            try:
                out.append(normalize(vec))
            except ValueError:
                out.append(None)
        return out

    def close(self) -> None:
        self._model = None
        self._torch = None
