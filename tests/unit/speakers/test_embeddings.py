"""Segment selection, snippets and the embedding plumbing (no ML models needed)."""

from __future__ import annotations

import sys
import types
import wave
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from meetingmaster3.domain.transcript import Segment, Transcript
from meetingmaster3.speakers.embeddings import (
    CONFIDENT_SECONDS,
    Interval,
    LabelledTurn,
    PyannoteEmbedder,
    clean_intervals,
    embed_profiles,
    pick_snippets,
    profile_speakers,
    read_wav,
    select_segments,
    split_long,
    subtract,
    turns_from,
    union,
)
from meetingmaster3.speakers.vectors import Vector, normalize

I = Interval  # noqa: E741


def T(start: float, end: float, speaker: str) -> LabelledTurn:
    return LabelledTurn(start, end, speaker)


def test_union_and_subtract() -> None:
    assert union([I(5, 6), I(0, 2), I(1, 3), I(3, 4), I(7, 7)]) == [I(0, 4), I(5, 6)]
    assert subtract([I(0, 10)], [I(2, 3), I(5, 6)]) == [I(0, 2), I(3, 5), I(6, 10)]
    assert subtract([I(0, 2), I(4, 6)], [I(1, 5)]) == [I(0, 1), I(5, 6)]
    assert subtract([I(0, 2)], []) == [I(0, 2)]
    assert subtract([I(2, 3)], [I(0, 10)]) == []


def test_clean_intervals_remove_overlap() -> None:
    turns = [T(0, 10, "A"), T(8, 12, "B"), T(11, 20, "A"), T(15, 16, "C")]
    assert clean_intervals(turns, "A") == [I(0, 8), I(12, 15), I(16, 20)]
    assert clean_intervals(turns, "B") == [I(10, 11)]


def test_split_and_select() -> None:
    assert split_long(I(0, 25), 10) == [I(0, 25 / 3), I(25 / 3, 50 / 3), I(50 / 3, 25)]
    assert split_long(I(0, 5), 10) == [I(0, 5)]
    pieces = [I(0, 1.5), I(10, 13), I(20, 45), I(50, 54)]
    chosen = select_segments(pieces, target_seconds=20)
    assert I(0, 1.5) not in chosen  # under the 2 s minimum
    assert sum(c.duration for c in chosen) >= 20 and all(c.duration <= 10 for c in chosen)
    assert chosen == sorted(chosen)
    assert len(select_segments([I(i * 10, i * 10 + 5) for i in range(30)], max_segments=4)) == 4


def test_snippets_are_spread_short_and_ordered() -> None:
    clean = [I(0, 20), I(5, 8), I(100, 104), I(200, 230), I(400, 400.5)]
    snips = pick_snippets(clean, seconds=6)
    assert snips == [I(0, 6), I(100, 104), I(200, 206)]
    # Not enough far-apart pieces: fill up with nearby ones.
    assert len(pick_snippets([I(0, 5), I(6, 9), I(10, 12)])) == 3
    # No clean speech at all: fall back to the raw turns.
    assert pick_snippets([], [I(3, 4)]) == [I(3, 4)]
    assert pick_snippets([], []) == []


def test_turns_from_diarization_or_transcript() -> None:
    t = Transcript(
        segments=[
            Segment(id=0, start=0, end=3, speaker_label="S0", text="a"),
            Segment(id=1, start=3, end=3, speaker_label="S1", text="b"),  # zero length
            Segment(id=2, start=4, end=6, text="c"),  # unlabelled
        ],
        diarized=True,
    )
    assert turns_from(None, t) == [T(0, 3, "S0")]
    assert turns_from({"turns": []}, t) == [T(0, 3, "S0")]
    diar = {
        "turns": [{"start": 0, "end": 2, "speaker": "S1"}, {"start": 3, "end": 2, "speaker": "X"}]
    }
    assert turns_from(diar, t) == [T(0, 2, "S1")]


class FakeEmbedder:
    model_id = "fake"

    def __init__(self, fail_after: float | None = None) -> None:
        self.fail_after = fail_after
        self.calls: list[list[Interval]] = []

    def embed(self, audio: Path, segments: Sequence[Interval]) -> list[Vector | None]:
        self.calls.append(list(segments))
        return [
            None if self.fail_after is not None and s.start >= self.fail_after else
            normalize([1.0, s.start + 1.0])
            for s in segments
        ]  # fmt: skip

    def close(self) -> None:
        pass


def test_profiles_and_embedding() -> None:
    turns = [T(0, 30, "A"), T(30, 33, "B"), T(40, 41, "C"), T(50, 70, "A")]
    profiles = profile_speakers(turns, ["A", "B", "C"], talk_seconds={"A": 50.0})
    a, b, c = profiles["A"], profiles["B"], profiles["C"]
    assert a.talk_seconds == 50.0 and b.talk_seconds == 3.0
    assert a.clean_seconds == 50.0 and c.segments == []
    assert b.low_confidence and a.low_confidence  # nothing embedded yet
    emb = FakeEmbedder(fail_after=60)
    progress: list[float] = []
    embed_profiles(emb, Path("x.wav"), profiles, check=lambda: None, progress=progress.append)
    assert len(emb.calls) == 2 and progress == [0.5, 1.0]  # C has no usable speech
    assert a.embedding is not None and not a.low_confidence
    assert a.embedded_segments == len(a.segments) - 1  # the window at 60-70 s failed
    assert b.embedding is not None and b.embedded_seconds < CONFIDENT_SECONDS and b.low_confidence
    assert c.embedding is None and c.low_confidence
    stats = a.stats()
    assert stats["low_confidence"] is False and stats["embedded_segments"] == a.embedded_segments


def test_read_wav_slices_pcm(tmp_path: Path) -> None:
    path = tmp_path / "a.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x01\x00" * 32000)
    frames, rate = read_wav(path, 0.5, 1.0)
    assert rate == 16000 and len(frames) == 2 * 8000
    assert read_wav(path, 5, 6)[0] == b""  # past the end
    stereo = tmp_path / "s.wav"
    with wave.open(str(stereo), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00" * 64)
    with pytest.raises(ValueError, match="mono"):
        read_wav(stereo, 0, 1)


def test_pyannote_embedder_with_fake_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The adapter's plumbing against stand-in torch/numpy/pyannote modules."""
    folder = tmp_path / "embedding"
    folder.mkdir()
    (folder / "pytorch_model.bin").write_bytes(b"weights")
    with pytest.raises(FileNotFoundError):
        PyannoteEmbedder(tmp_path, pipeline="p")
    emb = PyannoteEmbedder(folder, pipeline="org/pipe")
    assert emb.model_id.startswith("org/pipe/embedding@") and len(emb.model_id.split("@")[1]) == 16
    assert PyannoteEmbedder(folder, pipeline="org/pipe").model_id == emb.model_id

    wav = tmp_path / "a.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x10\x00" * 16000 * 3)

    class Out:
        def __init__(self, values: list[float]) -> None:
            self.values = values

        def __getitem__(self, i: int) -> Out:
            return self

        def float(self) -> Out:
            return self

        def cpu(self) -> Out:
            return self

        def numpy(self) -> Out:
            return self

        def tolist(self) -> list[float]:
            return self.values

    class Model:
        device = "cpu"
        loaded_from = ""

        @classmethod
        def from_pretrained(cls, path: str) -> Model:
            m = cls()
            m.loaded_from = path
            return m

        def eval(self) -> None:
            pass

        def to(self, device: Any) -> Model:
            return self

        def __call__(self, waveform: Any) -> Out:
            return Out([0.0, 0.0] if waveform.n < 16000 else [3.0, 4.0])

    class Tensor:
        def __init__(self, n: int) -> None:
            self.n = n

        def __getitem__(self, idx: Any) -> Tensor:
            return self

        def to(self, device: Any) -> Tensor:
            return self

    class Samples:
        def __init__(self, n: int) -> None:
            self.n = n

        def astype(self, t: str) -> Samples:
            return self

        def __truediv__(self, x: float) -> Samples:
            return self

    class InferenceMode:
        def __enter__(self) -> None:
            pass

        def __exit__(self, *a: object) -> None:
            pass

    torch = types.ModuleType("torch")
    torch.device = lambda d: d  # type: ignore[attr-defined]
    torch.from_numpy = lambda s: Tensor(s.n)  # type: ignore[attr-defined]
    torch.inference_mode = InferenceMode  # type: ignore[attr-defined]
    numpy = types.ModuleType("numpy")
    numpy.frombuffer = lambda b, dtype: Samples(len(b) // 2)  # type: ignore[attr-defined]
    pyannote_audio = types.ModuleType("pyannote.audio")
    pyannote_audio.Model = Model  # type: ignore[attr-defined]
    for name, mod in {"torch": torch, "numpy": numpy, "pyannote.audio": pyannote_audio}.items():
        monkeypatch.setitem(sys.modules, name, mod)
    monkeypatch.setattr("meetingmaster3.transcription.engine._quiet_libraries", lambda: None)

    out = emb.embed(wav, [I(0, 2), I(2, 2.2), I(2.2, 2.9)])
    assert out[0] is not None and [round(x, 6) for x in out[0]] == [0.6, 0.8]
    assert out[1] is None  # under half a second
    assert out[2] is None  # the model returned a zero vector
    assert emb._model.loaded_from == str(folder)
    emb.close()
    assert emb._model is None
