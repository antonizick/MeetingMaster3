# MeetingMaster3

**Turn meeting audio into speaker-attributed transcripts and secretary-grade, Obsidian-native Markdown notes, entirely on your own machine.**

[![CI](https://img.shields.io/badge/CI-pending-lightgrey)](#status)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

> ⚠️ **Pre-alpha, under construction.** The backend foundations run (configuration, hardware
> detection, LLM backends, the note format and the job API with upload, live progress, cancel and
> resume), but real transcription, note generation and the UI arrive in the phases listed in the
> [plan](IMPLEMENTATION_PLAN.md).

## Status
Built in phases (see [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)). Done so far: Phases 01-05 and 08 (repository, Python scaffold, data model and Markdown round-trip, job orchestration and audio ingest, hardware detection, LLM backends).
The CI badge above is a placeholder until the repository is published (Phase 16).

## Planned features (MVP)
- Upload audio, get a diarized transcript (WhisperX: faster-whisper + wav2vec2 alignment + pyannote).
- Name speakers once; optional local voiceprints recognise them in later meetings.
- Structured notes from 22 templates (executive summary, decision log, action items, and more),
  written straight into your Obsidian vault with frontmatter, wikilinks and a companion transcript.
- Side-by-side review with audio, per-section regeneration with diffs, and re-opening existing notes.
- Local-first LLMs through Ollama; optional BYOK cloud backends (AWS Bedrock, OpenAI-compatible
  endpoints including OpenRouter).
- Hardware-aware: designed to work on an 8 GB VRAM GPU.
- Docker Compose deployment (GPU and CPU).

## Privacy stance
Your audio, transcripts and notes stay on your machine. Nothing leaves it unless you explicitly pick a
cloud LLM backend, and the app asks for consent before the first cloud use. There is no telemetry.
Voiceprints are treated as biometric data: opt-in, local only, deletable. See [`docs/PRIVACY.md`](docs/PRIVACY.md).

## Architecture at a glance
```
 browser (HTMX + Alpine, localhost only)
        |  REST + SSE
 FastAPI app ── job queue (one GPU worker) ── SQLite + job artifacts
        |                |
        |        WhisperX pipeline ── speaker mapping / voiceprints
        |                |
        |        template engine ── LLM backend (Ollama | Bedrock | OpenAI-compatible)
        v
 Markdown writer/parser ──> your Obsidian vault (source of truth)
```
Details: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Quickstart
Development server (the real flow arrives in Phase 10; Docker in Phase 14):
```bash
uv sync
uv run mm3 serve          # http://127.0.0.1:8765/  (health check: /healthz)
```

## Installation
Native install for development (needs [uv](https://docs.astral.sh/uv/); it fetches Python 3.12 for you):
```bash
git clone <repo-url> MeetingMaster3 && cd MeetingMaster3
uv sync
uv run pre-commit install   # optional, recommended for contributors
uv run pytest
```
**ffmpeg is required** (`ffmpeg` and `ffprobe` on `PATH`; Arch: `sudo pacman -S ffmpeg`, Debian/Ubuntu:
`sudo apt install ffmpeg`, macOS: `brew install ffmpeg`); `uv run mm3 doctor` checks it. To try the job
flow without ML models, run `MM3_FAKE_PIPELINE=1 uv run mm3 serve` (see
[`docs/dev-guide/jobs-and-stages.md`](docs/dev-guide/jobs-and-stages.md)). Docker Compose arrives in Phase 14. Details:
[`docs/user-guide/installation.md`](docs/user-guide/installation.md) and
[`docs/dev-guide/setup.md`](docs/dev-guide/setup.md).

## Configuration
Settings come from `config.yaml`, overridden by `MM3_*` environment variables. Run `uv run mm3 config path`
to see where files live. Every setting is documented in
[`docs/user-guide/configuration.md`](docs/user-guide/configuration.md).

## Hardware guidance
MeetingMaster3 detects your GPU and recommends settings; run `uv run mm3 doctor` to see them for your
machine. Values below are **estimates** from the specification, to be replaced by measured numbers
(Phase 15). Details: [`docs/user-guide/hardware.md`](docs/user-guide/hardware.md).

| Profile | Whisper model | Diarization | Speed (x real time) | Local LLM (Ollama) |
|---|---|---|---|---|
| CPU only | small / medium, int8 | optional | 0.5-2 (estimated) | 3-4B, or a cloud backend |
| 8 GB VRAM | large-v3-turbo, int8_float16 | yes | 15-30 (estimated) | 7-9B at Q4_K_M |
| 16 GB VRAM | large-v3, float16 | yes | 30-50 (estimated) | 12-14B at Q4_K_M |
| 24 GB+ VRAM | large-v3, float16 | yes | 40-70 (estimated) | about 30B at Q4_K_M |

On 8 GB, transcription and the LLM take turns on the GPU. Override auto-detection with
`hardware.profile` in `config.yaml`.

## FAQ
_Coming in Phase 16._

## Documentation and project files
- [Specification](docs/SPECIFICATION.md) (section 15 amendments override sections 1-14)
- [Implementation plan](IMPLEMENTATION_PLAN.md) and [decision log](docs/DECISIONS.md)
- [Contributing](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) · [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

## License
Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). Model weights are not bundled and carry
their own terms; see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
