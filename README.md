# MeetingMaster3

**Turn meeting audio into speaker-attributed transcripts and secretary-grade, Obsidian-native Markdown notes, entirely on your own machine.**

[![CI](https://img.shields.io/badge/CI-pending-lightgrey)](#status)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

> ⚠️ **Pre-alpha, under construction.** There is no runnable application yet. The repository currently
> holds the specification, the implementation plan and project governance. Do not expect anything to
> install or run until the phases listed in the [plan](IMPLEMENTATION_PLAN.md) land.

## Status
Built in phases (see [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md)). Currently: Phase 01, repository foundation.
CI and licence badges above are placeholders until Phase 02 adds the CI workflow.

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
_Coming in Phase 10 (first runnable flow) and Phase 14 (Docker)._

## Installation
_Coming in Phase 02 (native, uv) and Phase 14 (Docker Compose)._

## Configuration
_Coming in Phase 02 and Phase 12 (see `docs/user-guide/`)._

## Hardware guidance
_Coming in Phase 05 (recommendations) and Phase 15 (measured performance)._

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
