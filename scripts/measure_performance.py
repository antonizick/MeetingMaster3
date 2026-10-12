"""Measure the real pipeline on the reference machine (Phase 15, ``docs/PERFORMANCE.md``).

Runs ``mm3 process`` logic (the same job pipeline as the web app) on private recordings and
records, per stage: wall time, real-time factor, peak GPU memory (``nvidia-smi`` every 500 ms,
whole GPU, so Ollama is included) and peak resident memory (this process plus Ollama).

Recordings are never committed. Pass them as arguments or via ``MM3_PRIVATE_TEST_AUDIO``
(file paths separated by ``os.pathsep``). The output contains numbers and a neutral label
(``rec-31min``) only: no file names, titles, transcripts or speaker names.

Each run happens in a fresh subprocess with throw-away config, data and vault folders; the model
cache (``MM3_MODELS_DIR``, default ``~/.cache/meetingmaster3/models``) is shared. A Hugging Face
token for diarization comes from ``MM3_SECRETS__HF_TOKEN``.

    MM3_PRIVATE_TEST_AUDIO=/path/a.mp3:/path/b.mp3 \\
        uv run python scripts/measure_performance.py --models large-v3-turbo,medium \\
        --llm-model qwen3:8b --out perf.json
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

SAMPLE_SECONDS = 0.5


def _rss_kib(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return 0


def _ollama_pids() -> list[int]:
    pids = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                comm = (entry / "comm").read_text().strip()
            except OSError:
                continue
            if comm.startswith("ollama"):
                pids.append(int(entry.name))
    return pids


class Sampler:
    """Background sampling of GPU memory (MiB) and RSS (MiB) with wall-clock timestamps."""

    def __init__(self) -> None:
        self.samples: list[tuple[float, int, int, int]] = []  # (t, vram, app_rss, ollama_rss)
        self._stop = threading.Event()
        self._vram = 0
        self._smi: subprocess.Popen[str] | None = None

    def start(self) -> None:
        try:
            self._smi = subprocess.Popen(  # noqa: S603 - fixed argument list
                # nvidia-smi from PATH, like hardware.detect
                [  # noqa: S607
                    "nvidia-smi",
                    "--query-gpu=memory.used",
                    "--format=csv,noheader,nounits",
                    f"-lms={int(SAMPLE_SECONDS * 1000)}",
                ],
                stdout=subprocess.PIPE,
                text=True,
            )
            threading.Thread(target=self._read_smi, daemon=True).start()
        except FileNotFoundError:
            self._smi = None
        threading.Thread(target=self._loop, daemon=True).start()

    def _read_smi(self) -> None:
        if self._smi is None or self._smi.stdout is None:
            return
        for line in self._smi.stdout:
            try:
                self._vram = int(line.strip().split(",")[0])
            except ValueError:
                continue

    def _loop(self) -> None:
        me = os.getpid()
        while not self._stop.is_set():
            ollama = sum(_rss_kib(p) for p in _ollama_pids()) // 1024
            self.samples.append((time.time(), self._vram, _rss_kib(me) // 1024, ollama))
            self._stop.wait(SAMPLE_SECONDS)

    def stop(self) -> None:
        self._stop.set()
        if self._smi is not None:
            self._smi.terminate()

    def peaks(self, start: float, end: float) -> dict[str, int]:
        window = [s for s in self.samples if start <= s[0] <= end] or self.samples[-1:]
        return {
            "peak_vram_mib": max((s[1] for s in window), default=0),
            "peak_app_rss_mib": max((s[2] for s in window), default=0),
            "peak_ollama_rss_mib": max((s[3] for s in window), default=0),
        }


def _ts(text: str | None) -> float | None:
    return dt.datetime.fromisoformat(text).timestamp() if text else None


def run_one(audio: Path, model: str, llm_model: str | None, template: str | None) -> dict[str, Any]:
    """One measured run in this process (called in a fresh subprocess)."""
    from meetingmaster3.audio.ingest import probe
    from meetingmaster3.config.paths import resolve_paths
    from meetingmaster3.config.settings import load_settings
    from meetingmaster3.headless import ProcessRequest, build_options, process

    settings = load_settings()
    paths = resolve_paths()
    duration = probe(audio).duration_seconds
    options = build_options(
        audio,
        title="Performance run",
        date=dt.date(2026, 1, 1),
        transcription_model=model,
        diarize=True,
        model=llm_model,
        template=template,
        language="en",
    )
    names = {f"SPEAKER_{i:02d}": f"Person {i + 1}" for i in range(16)}
    sampler = Sampler()
    sampler.start()
    t0 = time.time()
    result = asyncio.run(
        process(settings, paths, ProcessRequest(audio, options, names), echo=lambda _: None)
    )
    t1 = time.time()
    time.sleep(SAMPLE_SECONDS * 2)
    sampler.stop()
    con = sqlite3.connect(paths.database)
    rows = con.execute(
        "SELECT stage, status, started_at, finished_at, attempt FROM job_stages "
        "WHERE job_id = ? ORDER BY position",
        (result.job_id,),
    ).fetchall()
    stages = []
    for stage, status, started, finished, attempt in rows:
        s, f = _ts(started), _ts(finished)
        entry: dict[str, Any] = {"stage": stage, "status": status, "attempt": attempt}
        if s is not None and f is not None:
            wall = f - s
            entry["wall_s"] = round(wall, 1)
            entry["rtf"] = round(duration / wall, 1) if wall > 0.05 else None
            entry.update(sampler.peaks(s, f))
        stages.append(entry)
    return {
        "audio_minutes": round(duration / 60, 1),
        "transcription_model": model,
        "llm_model": llm_model,
        "status": result.status.value,
        "error": (result.error or {}).get("code"),
        "total_wall_s": round(t1 - t0, 1),
        "total_rtf": round(duration / (t1 - t0), 1),
        "stages": stages,
        **{f"run_{k}": v for k, v in sampler.peaks(t0, t1).items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("audio", nargs="*", type=Path)
    parser.add_argument("--models", default="large-v3-turbo,medium")
    parser.add_argument("--llm-model", default="qwen3:8b")
    parser.add_argument("--template", default=None)
    parser.add_argument("--out", type=Path, default=Path("performance.json"))
    parser.add_argument("--one", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.one:
        print(json.dumps(run_one(args.audio[0], args.models, args.llm_model, args.template)))
        return

    files = list(args.audio) or [
        Path(p) for p in os.environ.get("MM3_PRIVATE_TEST_AUDIO", "").split(os.pathsep) if p
    ]
    if not files:
        sys.exit("No recordings: pass paths or set MM3_PRIVATE_TEST_AUDIO.")
    results: list[dict[str, Any]] = []
    for audio in files:
        for model in args.models.split(","):
            with tempfile.TemporaryDirectory(prefix="mm3-perf-") as tmp:
                vault = Path(tmp, "vault")
                vault.mkdir()
                env = {
                    **os.environ,
                    "MM3_CONFIG_DIR": str(Path(tmp, "config")),
                    "MM3_DATA_DIR": str(Path(tmp, "data")),
                    "MM3_MODELS_DIR": os.environ.get(
                        "MM3_MODELS_DIR", str(Path.home() / ".cache/meetingmaster3/models")
                    ),
                    "MM3_VAULT__PATH": str(vault),
                }
                cmd = [sys.executable, __file__, "--one", str(audio), "--models", model]
                cmd += ["--llm-model", args.llm_model]
                if args.template:
                    cmd += ["--template", args.template]
                proc = subprocess.run(  # noqa: S603 - our own script, fixed arguments
                    cmd, env=env, capture_output=True, text=True, check=False
                )
                if proc.returncode != 0:
                    tail = proc.stderr.strip().splitlines()[-3:]
                    print(f"run failed ({model}): {' | '.join(tail)}", file=sys.stderr)
                    continue
                data = json.loads(proc.stdout.strip().splitlines()[-1])
                data["label"] = f"rec-{round(data['audio_minutes'])}min"
                results.append(data)
                print(
                    f"{data['label']} {model}: {data['status']} in {data['total_wall_s']} s "
                    f"(RTF {data['total_rtf']}), peak VRAM {data['run_peak_vram_mib']} MiB",
                    flush=True,
                )
                args.out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
