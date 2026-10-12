"""Run the generation eval against a real LLM backend and print the scores.

    uv run python -m tests.eval.run_eval --model qwen3:8b
    uv run python -m tests.eval.run_eval --model gemma2:9b --templates executive-summary
    uv run python -m tests.eval.run_eval --model qwen3:8b --long      # map-reduce check
    uv run python -m tests.eval.run_eval --model qwen3:8b --json results.json
    uv run python -m tests.eval.baseline results.json                 # flag regressions

Notes are saved to ``--out`` (default: a temp folder) for reading. Uses the backends configured
in ``config.yaml`` (default: the local Ollama). Nothing is sent anywhere else.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import random
import sys
import tempfile
import time
from pathlib import Path

from meetingmaster3.config.settings import load_settings
from meetingmaster3.domain.transcript import Segment, Transcript
from meetingmaster3.llm.base import LLMBackend
from meetingmaster3.llm.budget import estimate_tokens
from meetingmaster3.llm.registry import BackendRegistry
from meetingmaster3.markdown.note_writer import build_note, render_note
from meetingmaster3.templates.assembler import format_turns, transcript_turns
from meetingmaster3.templates.generator import GenerationResult, NoteGenerator
from meetingmaster3.templates.loader import load_library
from meetingmaster3.templates.schema import Template
from tests.eval.checker import Meeting, Score, load_meetings, score_note

TODAY = dt.date(2026, 10, 11)

_TEAMS = ["Mobile", "Data platform", "Billing", "Design systems", "Infrastructure", "Growth"]
_UPDATES = [
    "{team} closed {n} tickets this sprint and the backlog is down to {m}.",
    "{team} is still waiting on the vendor for the {thing} renewal paperwork.",
    "{team} finished the {thing} migration in staging; production follows next sprint.",
    "{team} ran {n} interviews for the open role and has two candidates in the final round.",
    "{team} reports error rates around {p} percent, which is within the agreed range.",
    "{team} spent most of the week on on-call follow-ups, {n} incidents, none customer-facing.",
]
_THINGS = ["logging", "analytics", "feature flag", "payments", "notification", "search index"]


def long_meeting(meetings: list[Meeting], min_tokens: int, seed: int = 7) -> Meeting:
    """A long all-hands: the eval meetings in sequence, padded with team status updates (with
    no decisions or actions) until the transcript reaches ``min_tokens``. Expectations are the
    union of the parts'."""
    rng = random.Random(seed)  # noqa: S311 - fixture text, not security
    speakers: dict[str, str] = {}
    segments: list[Segment] = []
    t = 0.0
    expected: dict[str, list[object]] = {"decisions": [], "actions": [], "open_questions": []}

    def add(label: str, text: str, seconds: float) -> None:
        nonlocal t
        segments.append(
            Segment(id=len(segments), start=t, end=t + seconds, speaker_label=label, text=text)
        )
        t += seconds

    def filler(count: int) -> None:
        for _ in range(count):
            label = f"SPEAKER_{rng.randrange(20, 26)}"
            speakers.setdefault(label, f"Host {int(label[-2:]) - 19}")
            add(
                label,
                rng.choice(_UPDATES).format(
                    team=rng.choice(_TEAMS),
                    n=rng.randint(3, 40),
                    m=rng.randint(10, 90),
                    p=round(rng.uniform(0.1, 0.9), 1),
                    thing=rng.choice(_THINGS),
                ),
                rng.uniform(8, 20),
            )

    k = 0
    while True:
        for mi, m in enumerate(meetings):
            filler(30)
            offset = 30 + (k * len(meetings) + mi) * 5  # unique labels per copy of a meeting
            for seg in m.transcript.segments:
                assert seg.speaker_label is not None
                label = f"SPEAKER_{int(seg.speaker_label[-2:]) + offset:02d}"
                if seg.speaker_label in m.speakers:
                    speakers[label] = m.speakers[seg.speaker_label]
                add(label, seg.text, max(seg.end - seg.start, 3.0))
            if k == 0:
                for key in expected:
                    expected[key] += m.expected.get(key, [])
        k += 1
        text = format_turns(transcript_turns(_named(segments, speakers)))
        if estimate_tokens(text) >= min_tokens:
            break
    transcript = Transcript(segments=segments, language="en", duration=t, diarized=True)
    return Meeting("long-all-hands", "Quarterly All-Hands", meetings[0].date, speakers,
                   transcript, expected)  # fmt: skip


def _named(segments: list[Segment], speakers: dict[str, str]) -> Transcript:
    from meetingmaster3.domain.transcript import SpeakerMap

    return SpeakerMap(names=speakers).apply(Transcript(segments=segments, diarized=True))


async def run_one(
    backend: LLMBackend, model: str, template: Template, meeting: Meeting, max_context: int
) -> tuple[str, GenerationResult, float]:
    gen = NoteGenerator(backend, model, template, max_context=max_context, today=TODAY,
                        warn=lambda m: print(f"    warning: {m}", file=sys.stderr))  # fmt: skip
    meta = meeting.meta().model_copy(update={"template_id": template.id, "model": model})
    started = time.monotonic()
    result = await gen.generate(meta, meeting.named())
    return render_note(build_note(meta, result.sections)), result, time.monotonic() - started


def score_record(score: Score, result: GenerationResult, seconds: float) -> dict[str, object]:
    """One note's result for ``--json`` and the baseline (numbers and ids only)."""
    return {
        "meeting": score.meeting,
        "template": score.template,
        "passed": score.passed,
        "checks": dict(score.checks),
        "found": {k: len(v) for k, v in score.found.items()},
        "missing": {k: sorted(v) for k, v in score.missing.items() if v},
        "metrics": dict(score.metrics),
        "mode": result.mode,
        "calls": result.calls,
        "seconds": round(seconds, 1),
    }


def write_results(path: Path, model: str, records: list[dict[str, object]]) -> None:
    import json

    data = {"model": model, "date": dt.date.today().isoformat(), "results": records}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--backend", default=None)
    ap.add_argument("--model", required=True)
    ap.add_argument("--templates", nargs="*", default=None)
    ap.add_argument("--meetings", nargs="*", default=None)
    ap.add_argument("--max-context", type=int, default=16384)
    ap.add_argument("--long", action="store_true", help="Only the long map-reduce meeting.")
    ap.add_argument("--long-window", type=int, default=8192)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None, help="Write per-note results (scores).")
    args = ap.parse_args(argv)

    settings = load_settings()
    registry = BackendRegistry(settings)
    backend = registry.get(args.backend)
    library = load_library()
    templates = (
        [library.get(t) for t in args.templates]
        if args.templates
        else [e.template for e in library.listing() if e.template]
    )
    meetings = load_meetings()
    if args.meetings:
        meetings = [m for m in meetings if m.name in args.meetings]
    out = args.out or Path(tempfile.mkdtemp(prefix="mm3-eval-"))
    out.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[Template, Meeting, int]]
    if args.long:
        meeting = long_meeting(
            [m for m in load_meetings() if m.templates is None], 3 * args.long_window
        )
        tokens = estimate_tokens(format_turns(transcript_turns(meeting.named())))
        print(f"Long meeting: {tokens} estimated tokens, window {args.long_window} "
              f"({tokens / args.long_window:.1f}x)")  # fmt: skip
        jobs = [(t, meeting, args.long_window) for t in templates[:1]]
    else:
        jobs = [
            (t, m, args.max_context)
            for m in meetings
            for t in templates
            if m.templates is None or t.id in m.templates
        ]

    scores: list[Score] = []
    modes: list[str] = []
    records: list[dict[str, object]] = []
    for template, meeting, window in jobs:
        print(f"- {meeting.name} / {template.id} ...", flush=True)
        text, result, seconds = await run_one(backend, args.model, template, meeting, window)
        (out / f"{meeting.name}.{template.id}.md").write_text(text, encoding="utf-8")
        score = score_note(text, meeting, template)
        scores.append(score)
        modes.append(result.mode)
        records.append(score_record(score, result, seconds))
        if args.json:
            write_results(args.json, args.model, records)
        print(f"  {score.summary()}  [{result.mode}, {result.chunks} chunks, "
              f"{result.calls} calls, {seconds:.0f} s]")  # fmt: skip
        for p in score.problems:
            print(f"    ! {p}")
        for kind, ids in score.missing.items():
            print(f"    missing {kind}: {', '.join(ids)}")
    if args.long:
        # Acceptance (Phase 09): a meeting of at least 3x the window completes through map-reduce
        # with a valid note and no invented owners; recall is reported, not required.
        required = (
            "markers_valid", "sections_present", "ai_recommendations_last",
            "no_empty_sections", "no_invented_owners",
        )  # fmt: skip
        ok = modes == ["map-reduce"] and all(scores[0].checks.get(k) for k in required)
        print(
            f"\nLong meeting {'completed' if ok else 'FAILED'} through {modes[0]}. Notes in {out}"
        )
        return 0 if ok else 1
    passed = sum(s.passed for s in scores)
    print(f"\n{passed}/{len(scores)} notes pass every check. Notes saved in {out}")
    return 0 if passed == len(scores) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
