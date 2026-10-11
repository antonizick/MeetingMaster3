"""WhisperXEngine against fake ``whisperx``/``torch``/``pandas`` modules (no ML install needed)."""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from meetingmaster3.transcription import engine as engine_mod
from meetingmaster3.transcription.engine import SpeakerTurn, WhisperXEngine

from .fakes import FakeAudio


class Frame:
    """A tiny stand-in for a pandas DataFrame."""

    def __init__(self, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
        self.rows, self.columns = rows, columns

    def itertuples(self, index: bool = False) -> Iterator[Any]:
        return iter(types.SimpleNamespace(**r) for r in self.rows)


@pytest.fixture
def fake_ml(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    class Pipeline:
        model = types.SimpleNamespace(
            feat_kwargs={"feature_size": 128},
            encode=lambda seg: calls.setdefault("encoded", seg) and "enc",
            model=types.SimpleNamespace(detect_language=lambda enc: [[("<|de|>", 0.93)]]),
        )

        def transcribe(self, audio: Any, **kw: Any) -> dict[str, Any]:
            calls["transcribe"] = kw
            kw["progress_callback"](100.0)
            return {"segments": [], "language": kw["language"]}

    whisperx = types.ModuleType("whisperx")
    whisperx.load_audio = lambda p: calls.setdefault("load_audio", p) and FakeAudio([0.0] * 10)  # type: ignore[attr-defined]
    whisperx.load_model = lambda *a, **kw: calls.setdefault("load_model", (a, kw)) and Pipeline()  # type: ignore[attr-defined]
    whisperx.load_align_model = lambda **kw: (calls.setdefault("align_model", kw), {"m": 1})  # type: ignore[attr-defined]
    whisperx.align = lambda *a, **kw: calls.setdefault("align", (a, kw)) and {"segments": [1]}  # type: ignore[attr-defined]

    wx_audio = types.ModuleType("whisperx.audio")
    wx_audio.N_SAMPLES = 480_000  # type: ignore[attr-defined]
    wx_audio.log_mel_spectrogram = lambda audio, n_mels, padding: ("mel", n_mels, padding)  # type: ignore[attr-defined]

    class Diarizer:
        def __init__(self, **kw: Any) -> None:
            calls["diarizer"] = kw

        def __call__(self, audio: Any, **kw: Any) -> Frame:
            calls["diarize"] = kw
            return Frame([{"start": 0.0, "end": 1.5, "speaker": "SPEAKER_00", "segment": None}])

    wx_diarize = types.ModuleType("whisperx.diarize")
    wx_diarize.DiarizationPipeline = Diarizer  # type: ignore[attr-defined]

    def assign(frame: Frame, result: dict[str, Any], fill_nearest: bool = False) -> dict[str, Any]:
        calls["assign"] = (frame.rows, fill_nearest)
        return result

    wx_diarize.assign_word_speakers = assign  # type: ignore[attr-defined]

    torch = types.ModuleType("torch")
    torch.cuda = types.SimpleNamespace(is_available=lambda: True)  # type: ignore[attr-defined]
    pandas = types.ModuleType("pandas")
    pandas.DataFrame = Frame  # type: ignore[attr-defined]

    for name, mod in {
        "whisperx": whisperx,
        "whisperx.audio": wx_audio,
        "whisperx.diarize": wx_diarize,
        "torch": torch,
        "pandas": pandas,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr(engine_mod, "_quieted", False)
    return calls


def test_whisperx_engine_calls(fake_ml: dict[str, Any], tmp_path: Path) -> None:
    e = WhisperXEngine()
    assert e.cuda_available()
    audio = e.load_audio(tmp_path / "audio.wav")
    assert fake_ml["load_audio"] == str(tmp_path / "audio.wav")
    assert e.audio_seconds(FakeAudio([0.0] * 32_000)) == 2.0

    asr = e.load_asr("small", device="cuda", compute_type="int8_float16", language=None,
                     local_only=True)  # fmt: skip
    assert fake_ml["load_model"] == (
        ("small", "cuda"),
        {"compute_type": "int8_float16", "language": None, "local_files_only": True},
    )
    assert e.detect_language(asr, audio) == ("de", 0.93)
    assert fake_ml["encoded"] == ("mel", 128, 480_000 - 10)  # short audio is padded to 30 s

    seen: list[float] = []
    e.transcribe(asr, audio, batch_size=4, language="de", progress=seen.append)
    assert fake_ml["transcribe"]["batch_size"] == 4 and seen == [100.0]

    aligner, meta = e.load_aligner("de", device="cuda")
    assert fake_ml["align_model"] == {"language_code": "de", "device": "cuda"}
    assert e.align(aligner, meta, [], audio, device="cuda", progress=seen.append) == {
        "segments": [1]
    }
    assert fake_ml["align"][1]["return_char_alignments"] is False

    diarizer = e.load_diarizer("org/diar", token="hf_x", device="cuda")
    assert fake_ml["diarizer"] == {"model_name": "org/diar", "token": "hf_x", "device": "cuda"}
    turns = e.diarize(diarizer, audio, min_speakers=2, max_speakers=None, progress=seen.append)
    assert turns == [SpeakerTurn(0.0, 1.5, "SPEAKER_00")]
    assert fake_ml["diarize"]["min_speakers"] == 2

    e.assign_speakers(turns, {"segments": []})
    rows, fill_nearest = fake_ml["assign"]
    assert rows == [{"start": 0.0, "end": 1.5, "speaker": "SPEAKER_00"}] and fill_nearest


def test_quiet_libraries_keeps_whisperx_logs_in_the_app_logger(fake_ml: dict[str, Any]) -> None:
    import logging

    wx = logging.getLogger("whisperx")
    before = list(wx.handlers)
    try:
        engine_mod._import("whisperx")
        assert wx.propagate and wx.level == logging.WARNING
        assert any(isinstance(h, logging.NullHandler) for h in wx.handlers)
    finally:
        wx.handlers[:] = before


def test_default_engine() -> None:
    assert isinstance(engine_mod.default_engine(), WhisperXEngine)
