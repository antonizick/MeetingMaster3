"""A scriptable fake of the transcription engine (no whisperx, torch or pyannote needed)."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from meetingmaster3.transcription.engine import Progress, SpeakerTurn

OOM_MESSAGE = "CUDA failed with error out of memory"

SEGMENTS: list[dict[str, Any]] = [
    {"start": 0.5, "end": 4.0, "text": " Shall we look at the budget?"},
    {"start": 4.5, "end": 9.0, "text": " Yes. I think it is fine. Okay, good."},
]

WORDS: list[list[tuple[str, float, float]]] = [
    [("Shall", 0.5, 0.8), ("we", 0.8, 1.0), ("look", 1.0, 1.4), ("at", 1.4, 1.5),
     ("the", 1.5, 1.6), ("budget?", 1.6, 2.2)],
    [("Yes.", 4.5, 4.9), ("I", 5.0, 5.1), ("think", 5.1, 5.4), ("it", 5.4, 5.5),
     ("is", 5.5, 5.6), ("fine.", 5.6, 6.1), ("Okay,", 7.0, 7.4), ("good.", 7.4, 8.0)],
]  # fmt: skip

TURNS = [
    SpeakerTurn(0.4, 2.5, "SPEAKER_00"),
    SpeakerTurn(4.4, 6.3, "SPEAKER_01"),
    SpeakerTurn(6.9, 8.2, "SPEAKER_00"),
]


class FakeAudio(list[float]):
    """Stands in for a numpy array (``len`` and ``shape``)."""

    @property
    def shape(self) -> tuple[int]:
        return (len(self),)


@dataclass
class FakeEngine:
    language: tuple[str, float] = ("en", 0.99)
    cuda: bool = True
    oom: dict[str, int] = field(default_factory=dict)  # stage -> how many calls raise OOM
    errors: dict[str, BaseException] = field(default_factory=dict)  # stage -> raised every call
    turns: list[SpeakerTurn] = field(default_factory=lambda: list(TURNS))
    block: threading.Event | None = None  # transcribe waits (calling progress) until set
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def _call(self, name: str, **kwargs: Any) -> None:
        with self.lock:
            self.calls.append((name, kwargs))
        if name in self.errors:
            raise self.errors[name]
        if self.oom.get(name, 0) > 0:
            self.oom[name] -= 1
            raise RuntimeError(OOM_MESSAGE)

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]

    def kwargs(self, name: str) -> list[dict[str, Any]]:
        return [c[1] for c in self.calls if c[0] == name]

    # -- Engine ---------------------------------------------------------------------------------

    def cuda_available(self) -> bool:
        return self.cuda

    def load_audio(self, path: Path) -> Any:
        self._call("load_audio", path=path)
        return FakeAudio([0.0] * 16_000 * 10)

    def audio_seconds(self, audio: Any) -> float:
        return len(audio) / 16_000

    def load_asr(
        self, model: str, *, device: str, compute_type: str, language: str | None, local_only: bool
    ) -> Any:
        self._call(
            "load_asr",
            model=model,
            device=device,
            compute_type=compute_type,
            language=language,
            local_only=local_only,
        )
        return object()

    def detect_language(self, asr: Any, audio: Any) -> tuple[str, float]:
        self._call("detect_language")
        return self.language

    def transcribe(
        self, asr: Any, audio: Any, *, batch_size: int, language: str, progress: Progress
    ) -> dict[str, Any]:
        self._call("transcribe", batch_size=batch_size, language=language)
        if self.block is not None:
            while not self.block.wait(0.01):
                progress(10.0)
        for pct in (50.0, 100.0):
            progress(pct)
        return {"segments": [dict(s) for s in SEGMENTS], "language": language}

    def load_aligner(self, language: str, *, device: str) -> tuple[Any, dict[str, Any]]:
        self._call("load_aligner", language=language, device=device)
        return object(), {"language": language}

    def align(
        self,
        aligner: Any,
        metadata: dict[str, Any],
        segments: list[dict[str, Any]],
        audio: Any,
        *,
        device: str,
        progress: Progress,
    ) -> dict[str, Any]:
        self._call("align", device=device)
        progress(100.0)
        out = []
        for seg, words in zip(segments, WORDS, strict=False):
            out.append(
                {
                    **seg,
                    "words": [{"word": w, "start": s, "end": e, "score": 0.9} for w, s, e in words],
                }
            )
        out[0]["words"].append({"word": "um", "score": float("nan")})  # unaligned word
        return {"segments": out, "word_segments": []}

    def load_diarizer(self, model: str, *, token: str | None, device: str) -> Any:
        self._call("load_diarizer", model=model, token=token, device=device)
        return object()

    def diarize(
        self,
        diarizer: Any,
        audio: Any,
        *,
        min_speakers: int | None,
        max_speakers: int | None,
        progress: Progress,
    ) -> list[SpeakerTurn]:
        self._call("diarize", min_speakers=min_speakers, max_speakers=max_speakers)
        progress(100.0)
        return list(self.turns)

    def assign_speakers(self, turns: list[SpeakerTurn], result: dict[str, Any]) -> dict[str, Any]:
        """Like whisperx: the dominant speaker per segment, and one per aligned word."""
        self._call("assign_speakers")

        def speaker_at(start: float, end: float) -> str | None:
            best, overlap = None, 0.0
            for t in turns:
                o = min(end, t.end) - max(start, t.start)
                if o > overlap:
                    best, overlap = t.speaker, o
            return best

        for seg in result["segments"]:
            if (s := speaker_at(seg["start"], seg["end"])) is not None:
                seg["speaker"] = s
            for w in seg.get("words", []):
                if w.get("start") is not None and (s := speaker_at(w["start"], w["end"])):
                    w["speaker"] = s
        return result
