"""Convert WhisperX results into ``domain.Transcript`` and the stage artifacts' JSON (pure)."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from meetingmaster3.domain.transcript import SPEAKER_LABEL_RE, Segment, Transcript, Word
from meetingmaster3.transcription.engine import SpeakerTurn


def finite(value: Any) -> float | None:
    """A finite float, or ``None`` (WhisperX leaves NaN or nothing for unaligned words)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def clean_segments(segments: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """WhisperX segments reduced to JSON-safe ``start``/``end``/``text`` (+ ``words``,
    ``speaker``), with character alignments and NaNs dropped."""
    out: list[dict[str, Any]] = []
    for seg in segments:
        start = max(0.0, finite(seg.get("start")) or 0.0)
        end = finite(seg.get("end"))
        item: dict[str, Any] = {
            "start": round(start, 3),
            "end": round(max(start, end if end is not None else start), 3),
            "text": str(seg.get("text", "")),
        }
        if "words" in seg:
            item["words"] = [
                {
                    "word": str(w.get("word", "")),
                    "start": finite(w.get("start")),
                    "end": finite(w.get("end")),
                    "score": finite(w.get("score")),
                    **({"speaker": w["speaker"]} if w.get("speaker") else {}),
                }
                for w in seg["words"]
            ]
        if seg.get("speaker"):
            item["speaker"] = str(seg["speaker"])
        if (logprob := finite(seg.get("avg_logprob"))) is not None:
            item["avg_logprob"] = logprob
        out.append(item)
    return out


def to_transcript(
    segments: Iterable[dict[str, Any]],
    *,
    language: str | None,
    duration: float | None,
    model: str | None,
    diarized: bool,
) -> Transcript:
    """Build the domain transcript. Empty segments are dropped; ids are renumbered from 0.
    Speaker labels are kept only when ``diarized`` (a non-diarized transcript has none)."""
    out: list[Segment] = []
    for seg in segments:
        text = " ".join(str(seg.get("text", "")).split())
        if not text:
            continue
        start = max(0.0, finite(seg.get("start")) or 0.0)
        end = max(start, finite(seg.get("end")) or start)
        words = [
            Word(
                text=word_text,
                start=finite(w.get("start")),
                end=finite(w.get("end")),
                score=finite(w.get("score")),
            )
            for w in seg.get("words", [])
            if (word_text := " ".join(str(w.get("word", "")).split()))
        ]
        label = seg.get("speaker") if diarized else None
        if label is not None and not SPEAKER_LABEL_RE.match(str(label)):
            label = None
        out.append(
            Segment(
                id=len(out),
                start=round(start, 3),
                end=round(end, 3),
                speaker_label=label,
                text=text,
                words=words,
            )
        )
    return Transcript(
        segments=out,
        language=language,
        duration=round(duration, 3) if duration is not None and duration >= 0 else None,
        model=model,
        diarized=diarized,
    )


def talk_time(turns: Iterable[SpeakerTurn]) -> dict[str, float]:
    """Seconds of speech per diarization label, largest first."""
    totals: dict[str, float] = {}
    for t in turns:
        totals[t.speaker] = totals.get(t.speaker, 0.0) + max(0.0, t.end - t.start)
    return {k: round(v, 2) for k, v in sorted(totals.items(), key=lambda kv: -kv[1])}


NO_SPACE_LANGUAGES = frozenset({"ja", "zh", "th", "lo", "my", "yue"})
JITTER_SECONDS = 0.3


def split_by_speaker(
    segments: Iterable[dict[str, Any]], language: str | None = None
) -> list[dict[str, Any]]:
    """Split WhisperX segments where the word-level speaker changes.

    WhisperX segments are VAD chunks of up to 30 s, so one segment often holds a question and
    its answer; ``assign_word_speakers`` labels the whole segment with the dominant speaker but
    labels every aligned word individually. A one-word run shorter than ``JITTER_SECONDS``
    between two runs of the same speaker is treated as diarization jitter. Segments without
    word speakers are returned unchanged."""
    joiner = "" if language in NO_SPACE_LANGUAGES else " "
    out: list[dict[str, Any]] = []
    for seg in segments:
        words: list[dict[str, Any]] = list(seg.get("words") or [])
        if not any(w.get("speaker") for w in words):
            out.append(seg)
            continue
        runs: list[list[dict[str, Any]]] = []
        current = seg.get("speaker")
        for w in words:
            speaker = w.get("speaker") or current
            current = speaker
            if runs and runs[-1][0].get("_speaker") == speaker:
                runs[-1].append({**w, "_speaker": speaker})
            else:
                runs.append([{**w, "_speaker": speaker}])
        merged: list[list[dict[str, Any]]] = []
        for i, run in enumerate(runs):
            prev = merged[-1] if merged else None
            nxt = runs[i + 1] if i + 1 < len(runs) else None
            if (
                prev is not None
                and nxt is not None
                and len(run) == 1
                and prev[0]["_speaker"] == nxt[0]["_speaker"]
                and _span(run) < JITTER_SECONDS
            ):
                prev.extend({**w, "_speaker": prev[0]["_speaker"]} for w in run)
            elif prev is not None and prev[0]["_speaker"] == run[0]["_speaker"]:
                prev.extend(run)
            else:
                merged.append(list(run))
        if len(merged) == 1:
            out.append(seg)
            continue
        for run in merged:
            starts = [s for w in run if (s := finite(w.get("start"))) is not None]
            ends = [e for w in run if (e := finite(w.get("end"))) is not None]
            out.append(
                {
                    "start": min(starts) if starts else seg.get("start", 0.0),
                    "end": max(ends) if ends else seg.get("end", 0.0),
                    "text": joiner.join(str(w.get("word", "")) for w in run),
                    "speaker": run[0]["_speaker"],
                    "words": [{k: v for k, v in w.items() if k != "_speaker"} for w in run],
                }
            )
    return out


def _span(run: list[dict[str, Any]]) -> float:
    start, end = finite(run[0].get("start")), finite(run[-1].get("end"))
    return (end - start) if start is not None and end is not None else 0.0
