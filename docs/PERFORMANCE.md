# Performance

Measured in Phase 15 (2026-10-12) on the reference machine. These numbers replace the estimates for
the 8 GB profile (`src/meetingmaster3/hardware/recommendations.yaml`, `status: measured`), the README
hardware table and the time shown before a job starts (spec R17). Other profiles are still
estimates. Your hardware, recordings and models will differ: treat these as a guide, not a promise.

## Summary (8 GB laptop GPU)
| What | 10 min | 31 min | 72 min |
|---|---|---|---|
| Transcribe + align + diarize, `large-v3-turbo` | 47 s (12.8x) | 139 s (13.5x) | 275 s (15.8x) |
| Transcribe + align + diarize, `medium` | 49 s (12.2x) | 138 s (13.6x) | 295 s (14.7x) |
| Notes, `qwen3:8b`, Executive Summary | 22-30 s | 94-111 s | 210-280 s (map-reduce) |
| **Upload to note in the vault (whole job)** | **79-85 s** | **252-271 s** | **552-600 s** |

So on this laptop **a 60-minute meeting is transcribed with speakers in about 4-5 minutes**, and the
complete job, including notes written by a local 8B model, takes **about 8-9 minutes**. With a
cloud LLM the notes take seconds instead (not measured here; that depends on the provider).

- `medium` is **not faster** than `large-v3-turbo` on this GPU (turbo has 4 decoder layers) and
  uses slightly more memory; keep turbo as the default and `medium` as the out-of-memory fallback.
- **Diarization is about half** of the transcription time and runs at a constant ~28x real time.
- **Peak GPU memory of the app** is 2.8 GB with turbo and 3.3 GB with medium; Ollama with qwen3:8b
  peaks at 5.5-5.8 GB. They never share the GPU: the app asks Ollama to unload before transcription
  and frees Whisper and pyannote before generation (spec R5). The whole GPU never exceeded 6.8 GB.
- **Peak RAM** of the app is 2.5-3.1 GB during transcription (models in memory); Ollama's runner
  holds about 5.4 GB of RAM while loaded.

## Raw numbers
Per stage: wall time in seconds (real-time factor in brackets = audio seconds / wall seconds), then
the peak GPU memory of the MeetingMaster3 process, of Ollama, and the app's peak resident memory
(MiB). "Total" is the whole job from upload to the note written in the vault. Timestamps have
one-second resolution.

| Recording | Model | ingest | transcribe | align | diarize | generate | Total |
|---|---|---|---|---|---|---|---|
| 10 min | large-v3-turbo | 1 | 17 (35x) | 9 (67x) | 21 (29x) | 30 | 84.8 s (7.1x) |
| 10 min | medium | 1 | 19 (32x) | 8 (75x) | 22 (27x) | 22 | 78.5 s (7.6x) |
| 31 min | large-v3-turbo | 1 | 41 (46x) | 30 (63x) | 68 (28x) | 111 | 270.6 s (6.9x) |
| 31 min | medium | 1 | 48 (39x) | 25 (75x) | 65 (29x) | 94 | 251.7 s (7.5x) |
| 72 min | large-v3-turbo | 2 | 69 (63x) | 55 (79x) | 151 (29x) | 280 | 600.2 s (7.2x) |
| 72 min | medium | 2 | 90 (48x) | 55 (79x) | 150 (29x) | 210 | 551.8 s (7.9x) |

| Recording | Model | App VRAM: transcribe / align / diarize | Ollama VRAM (generate) | App RSS peak |
|---|---|---|---|---|
| 10 min | large-v3-turbo | 2720 / 2240 / 2846 | 5460 | 2959 |
| 10 min | medium | 3008 / 2240 / 2846 | 5460 | 2949 |
| 31 min | large-v3-turbo | 2720 / 1964 / 2846 | 5574 | 2689 |
| 31 min | medium | 3264 / 2336 / 2846 | 5574 | 2701 |
| 72 min | large-v3-turbo | 2720 / 2622 / 2848 | 5492 | 3068 |
| 72 min | medium | 3200 / 3008 / 2848 | 5816 | 3104 |

Generation time varies with how much was said and with the template; map-reduce (long meetings)
makes more calls. The eval below gives per-template times.

## Method
- **Machine:** laptop with an NVIDIA GeForce RTX 2070 with Max-Q Design (8 GB, driver 610.57),
  Intel Core i7-9750H, 32 GB RAM, Omarchy (Arch) Linux. Native install (`uv`), not Docker.
- **Software:** MeetingMaster3 at the Phase 15 branch; WhisperX 3.8.6, faster-whisper 1.2.1,
  CTranslate2 4.8.2, torch 2.8.0+cu128, pyannote.audio 4.0.7 (`speaker-diarization-community-1`);
  Ollama 0.33.3 with `qwen3:8b` (Q4_K_M). Default `vram8` settings: `int8_float16`, batch 8,
  diarization on, models loaded and freed per stage.
- **Recordings:** the owner's own meetings (private, used locally via `MM3_PRIVATE_TEST_AUDIO`,
  never committed; only numbers were recorded): a 31-minute interview, a 72-minute working meeting
  and the first 10 minutes of the latter. English, 2-5 speakers, MP3.
- **Script:** `scripts/measure_performance.py` runs each (recording, model) pair in a fresh process
  with throw-away config, data and vault folders and the shared model cache. It goes through the
  same job pipeline as the web app (`mm3 process` logic, speaker names answered automatically) and
  samples every 500 ms: `nvidia-smi --query-compute-apps` (per-process GPU memory),
  `nvidia-smi --query-gpu=memory.used` (whole GPU) and `/proc/<pid>/status` (RSS of the app and of
  Ollama's processes). Stage times come from the job database.
  ```
  MM3_PRIVATE_TEST_AUDIO=/path/a.mp3:/path/b.mp3 MM3_SECRETS__HF_TOKEN=hf_... \
    uv run --extra ml python scripts/measure_performance.py --models large-v3-turbo,medium \
    --llm-model qwen3:8b --out performance.json
  ```
- Nothing else heavy ran during the transcription measurements.

## Long meetings (spec §3 edge case)
- **3-hour recording, fake pipeline** (`MM3_FAKE_PIPELINE=1`, a 3-hour Opus file): the job ran to
  the vault in 97 s, almost all of it ffmpeg converting 3 hours of audio to 16 kHz WAV and back to
  Opus for retention. The app's memory stayed flat at **50 MiB** (audio is streamed by ffmpeg in a
  subprocess, never loaded into the app), with 91 progress events and no gaps.
- **Real long recordings:** the 72-minute run above scales linearly (RTF rises slightly with length
  because model loading is a fixed cost). By extrapolation, 3 hours takes about 12 minutes to
  transcribe on this GPU; whisper and pyannote process audio in windows, so GPU memory does not grow
  with length (2.85 GB for both 31 and 72 minutes).
- **Review workspace, 3-hour transcript** (synthetic: 1 029 turns, 24 444 words, every word a
  clickable `<span>`): the page is 1.3 MB of HTML and loads in 1.8 s in Chromium, with 29 633 DOM
  nodes and a 6 MB JavaScript heap; scrolling the transcript stayed at 60 frames per second
  (median 16.7 ms per frame, worst 17.6 ms). No "drop word timings" option is needed.
- Generation of long meetings uses map-reduce (`generation.max_context` 16 384 tokens on 8 GB). The
  eval's long-meeting check passes (below). Regenerating one section of a long meeting repeats the
  map step (about the same time as the first generation); caching the map notes is on the roadmap.

## Quality baseline
`tests/eval/baseline.json` records the generation eval with `qwen3:8b` on this machine: every
template against every synthetic eval meeting (`tests/eval/meetings/`), plus the long map-reduce
meeting. Re-run and compare after changing prompts, templates or the model:
```
uv run python -m tests.eval.run_eval --model qwen3:8b --json /tmp/results.json
uv run python -m tests.eval.baseline /tmp/results.json        # exits 1 on a regression
```
Results of the Phase 15 run are in the Phase Log of `IMPLEMENTATION_PLAN.md`.

## Not measured
16 GB and 24 GB profiles, CPU-only transcription speed and Apple hardware (no such machine was
available; the values stay `estimated`). `generation.max_context` above 16 384 tokens needs a GPU
with more memory. Docker adds no measurable overhead in Phase 14's check (150 s clip in about 60 s
in the GPU container).
