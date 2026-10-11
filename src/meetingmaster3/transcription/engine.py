"""The thin seam between the stages and WhisperX/pyannote.

:class:`Engine` is what the stages call; :class:`WhisperXEngine` implements it with lazy imports
of whisperx, torch and pyannote (imported via ``importlib``, so they are plain ``Any`` for the
type checker whether or not the ``ml`` extra is installed). Tests pass a fake engine, or install
fake ``whisperx``/``torch`` modules to exercise :class:`WhisperXEngine` itself.
"""

from __future__ import annotations

import importlib
import logging
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

Progress = Callable[[float], None]
"""Receives a percentage in ``[0, 100]``; may raise ``JobCancelled`` to stop the work."""


@dataclass(frozen=True)
class SpeakerTurn:
    start: float
    end: float
    speaker: str


class Engine(Protocol):
    def cuda_available(self) -> bool: ...

    def load_audio(self, path: Path) -> Any: ...

    def audio_seconds(self, audio: Any) -> float: ...

    def load_asr(
        self, model: str, *, device: str, compute_type: str, language: str | None, local_only: bool
    ) -> Any: ...

    def detect_language(self, asr: Any, audio: Any) -> tuple[str, float]: ...

    def transcribe(
        self, asr: Any, audio: Any, *, batch_size: int, language: str, progress: Progress
    ) -> dict[str, Any]: ...

    def load_aligner(self, language: str, *, device: str) -> tuple[Any, dict[str, Any]]: ...

    def align(
        self,
        aligner: Any,
        metadata: dict[str, Any],
        segments: list[dict[str, Any]],
        audio: Any,
        *,
        device: str,
        progress: Progress,
    ) -> dict[str, Any]: ...

    def load_diarizer(self, model: str, *, token: str | None, device: str) -> Any: ...

    def diarize(
        self,
        diarizer: Any,
        audio: Any,
        *,
        min_speakers: int | None,
        max_speakers: int | None,
        progress: Progress,
    ) -> list[SpeakerTurn]: ...

    def assign_speakers(
        self, turns: list[SpeakerTurn], result: dict[str, Any]
    ) -> dict[str, Any]: ...


_quieted = False


def _import(name: str) -> Any:
    _quiet_libraries()
    return importlib.import_module(name)


def _quiet_libraries() -> None:
    """Before the first ML import: keep the libraries' INFO chatter out of the app log
    (transcript text is never logged at INFO) and hide warnings that do not apply here."""
    global _quieted
    if _quieted:
        return
    _quieted = True
    # whisperx's get_logger() installs its own stdout handler and stops propagation (bypassing
    # the app's redaction filter) unless the "whisperx" logger already has a handler.
    wx = logging.getLogger("whisperx")
    wx.addHandler(logging.NullHandler())
    wx.propagate = True
    for name in ("whisperx", "pyannote", "speechbrain", "lightning", "pytorch_lightning",
                 "lightning.pytorch.utilities.migration.utils"):  # fmt: skip
        logging.getLogger(name).setLevel(logging.WARNING)
    # pyannote warns at import when torchcodec cannot load FFmpeg (torchcodec 0.7 supports
    # FFmpeg 4-7); MeetingMaster3 always passes in-memory waveforms, so this does not apply.
    warnings.filterwarnings("ignore", message=r"\s*torchcodec is not installed correctly")
    # pyannote disables TF32 for reproducibility and says so on every load; and its statistics
    # pooling warns on very short windows (the result is still used correctly).
    warnings.filterwarnings("ignore", message=r"TensorFloat-32 \(TF32\) has been disabled")
    warnings.filterwarnings("ignore", message=r"std\(\): degrees of freedom is <= 0")


class WhisperXEngine:
    """WhisperX 3.8 (faster-whisper + wav2vec2 alignment + pyannote.audio 4 diarization)."""

    sample_rate = 16_000

    def cuda_available(self) -> bool:
        try:
            return bool(_import("torch").cuda.is_available())
        except Exception:  # pragma: no cover - broken CUDA install
            log.warning("torch could not query CUDA; using the CPU", exc_info=True)
            return False

    def load_audio(self, path: Path) -> Any:
        return _import("whisperx").load_audio(str(path))

    def audio_seconds(self, audio: Any) -> float:
        return float(len(audio)) / self.sample_rate

    def load_asr(
        self, model: str, *, device: str, compute_type: str, language: str | None, local_only: bool
    ) -> Any:
        return _import("whisperx").load_model(
            model,
            device,
            compute_type=compute_type,
            language=language,
            local_files_only=local_only,
        )

    def detect_language(self, asr: Any, audio: Any) -> tuple[str, float]:
        """Language and probability from the first 30 s (whisperx's own method drops the
        probability)."""
        wx_audio = _import("whisperx.audio")
        n = wx_audio.N_SAMPLES
        n_mels = asr.model.feat_kwargs.get("feature_size") or 80
        segment = wx_audio.log_mel_spectrogram(
            audio[:n], n_mels=n_mels, padding=0 if audio.shape[0] >= n else n - audio.shape[0]
        )
        encoded = asr.model.encode(segment)
        token, probability = asr.model.model.detect_language(encoded)[0][0]
        return str(token)[2:-2], float(probability)

    def transcribe(
        self, asr: Any, audio: Any, *, batch_size: int, language: str, progress: Progress
    ) -> dict[str, Any]:
        result: dict[str, Any] = asr.transcribe(
            audio, batch_size=batch_size, language=language, progress_callback=progress
        )
        return result

    def load_aligner(self, language: str, *, device: str) -> tuple[Any, dict[str, Any]]:
        model, metadata = _import("whisperx").load_align_model(
            language_code=language, device=device
        )
        return model, metadata

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
        result: dict[str, Any] = _import("whisperx").align(
            segments,
            aligner,
            metadata,
            audio,
            device,
            return_char_alignments=False,
            progress_callback=progress,
        )
        return result

    def load_diarizer(self, model: str, *, token: str | None, device: str) -> Any:
        return _import("whisperx.diarize").DiarizationPipeline(
            model_name=model, token=token, device=device
        )

    def diarize(
        self,
        diarizer: Any,
        audio: Any,
        *,
        min_speakers: int | None,
        max_speakers: int | None,
        progress: Progress,
    ) -> list[SpeakerTurn]:
        frame = diarizer(
            audio,
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            progress_callback=progress,
        )
        return [
            SpeakerTurn(float(row.start), float(row.end), str(row.speaker))
            for row in frame.itertuples(index=False)
        ]

    def assign_speakers(self, turns: list[SpeakerTurn], result: dict[str, Any]) -> dict[str, Any]:
        pd = _import("pandas")
        frame = pd.DataFrame(
            [{"start": t.start, "end": t.end, "speaker": t.speaker} for t in turns],
            columns=["start", "end", "speaker"],
        )
        # fill_nearest: a segment that falls in a diarization gap gets the nearest speaker
        # instead of no label, which would read as an unknown extra person.
        assigned: dict[str, Any] = _import("whisperx.diarize").assign_word_speakers(
            frame, result, fill_nearest=True
        )
        return assigned


def default_engine() -> Engine:
    return WhisperXEngine()
