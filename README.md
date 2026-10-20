# MeetingMaster3

**Turn meeting audio into speaker-attributed transcripts and secretary-grade, Obsidian-native Markdown notes, entirely on your own machine.**

[![CI](https://img.shields.io/badge/CI-pending-lightgrey)](#status)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

> ⚠️ **Pre-alpha.** The whole flow works in the browser, headlessly and in Docker (audio →
> transcript → named speakers → structured note in your vault → review, edit and regenerate), and it
> has had a security review (Phase 15). The first release is Phase 16 of the
> [plan](MM3_IMPLEMENTATION_PLAN.md).

## Status
Built in phases (see [`MM3_IMPLEMENTATION_PLAN.md`](MM3_IMPLEMENTATION_PLAN.md)). Done so far: Phases 01-13 (repository, Python scaffold, data model and Markdown round-trip, job orchestration and audio ingest, hardware detection, transcription and diarization, speaker naming and voiceprints, LLM backends, templates and note generation, the web UI's core flow, and the review workspace: synced audio and transcript, note editor, per-section regeneration with diffs and archives, template switching, renaming speakers and re-opening notes from the vault (see [reviewing and editing](docs/user-guide/reviewing-and-editing.md)), the Settings screen, template library management, local feedback ratings and export, and all 22 built-in templates), Docker images (Phase 14), and hardening: a [threat model](docs/THREAT_MODEL.md), a security review with fixes, fuzzing, end-to-end and accessibility tests, a licence audit and [measured performance](docs/PERFORMANCE.md) (Phase 15). Tuning round 15a added a readable transcript in the vault, two summaries per note (Summary Succinct and Summary Detailed) with an "Update older notes" action, dates from month-day file names, a "can I leave this page?" line and a logo.
The CI badge above is a placeholder until the repository is published (Phase 16).

## Planned features (MVP)
- Upload audio, get a diarized transcript (WhisperX: faster-whisper + wav2vec2 alignment + pyannote).
- Name speakers once; optional local voiceprints recognise them in later meetings.
- Structured notes from 23 templates (Default Notes by topic, executive summary, decision log, action items, and more), each
  opening with a short and a detailed summary, written straight into your Obsidian vault with
  frontmatter, wikilinks, a readable colour-coded transcript and a full-fidelity companion transcript.
- Side-by-side review with audio, per-section regeneration with diffs, and re-opening existing notes.
- Fix a meeting's title or date after the fact: every file is renamed and the links to it in your other
  notes follow (backed up first).
- Local-first LLMs through Ollama; optional BYOK cloud backends (AWS Bedrock, OpenAI-compatible
  endpoints including OpenRouter), both verified live with Claude and other model families
  ([setup guide](docs/user-guide/llm-backends.md), [measured cost and quality](docs/PERFORMANCE.md#cloud-backends)).
- Hardware-aware: designed to work on an 8 GB VRAM GPU.
- Docker Compose deployment (GPU and CPU).

## Privacy stance
Your audio, transcripts and notes stay on your machine. Nothing leaves it unless you explicitly pick a
cloud LLM backend, and the app asks for consent before the first cloud use. There is no telemetry.
Voiceprints are treated as biometric data: opt-in, local only, stored only for the people you choose,
physically erased when deleted. See [`docs/PRIVACY.md`](docs/PRIVACY.md).

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

## Installation
**Docker (recommended):**
```bash
export MM3_VAULT_PATH="$HOME/Documents"   # your Obsidian vault
docker compose -f docker/compose.yaml up -d --build                                # NVIDIA GPU
docker compose -f docker/compose.yaml -f docker/compose.cpu.yaml up -d --build     # CPU only
```
Then open <http://127.0.0.1:8765> (published on the loopback only). Models download into a volume, not
the image. Full guide, Ollama options and sizes: [`docs/user-guide/install-docker.md`](docs/user-guide/install-docker.md).
**Native (uv):** [`docs/user-guide/install-native.md`](docs/user-guide/install-native.md).

## Quickstart
Start the web UI and follow the on-screen steps (vault setup, upload, name speakers):
```bash
uv sync --extra ml && uv run mm3 serve   # then open http://127.0.0.1:8765
MM3_FAKE_PIPELINE=1 uv run mm3 serve     # try the flow with simulated results, no models needed
```
The walk-through with screenshots is in [`docs/user-guide/getting-started.md`](docs/user-guide/getting-started.md).

Or process a recording headlessly, from audio to a note in your vault:
```bash
uv sync --extra ml                      # transcription engine (see Installation)
ollama pull qwen3:8b                    # a local LLM that fits an 8 GB GPU
uv run mm3 process "2026-10-11 Product Sync.m4a" \
    --vault ~/Documents/MyVault --backend ollama --model qwen3:8b \
    --template executive-summary --speakers "SPEAKER_00=Alice,SPEAKER_01=Bob"
```
It transcribes, separates and names the speakers, writes the notes with a local model and saves
`Meetings/2026/2026-10-11 - Product Sync.md` plus its `.transcript.md` in the vault. Leave out
`--speakers` to be asked on the terminal (the speakers are listed with their talk time). Without the
`ml` extra or a model, `MM3_FAKE_PIPELINE=1` runs the same flow with simulated results.
`uv run mm3 templates list` shows the templates; `uv run mm3 serve` starts the API server
(<http://127.0.0.1:8765/>, health check `/healthz`).

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
[`docs/dev-guide/jobs-and-stages.md`](docs/dev-guide/jobs-and-stages.md)). Docker Compose is in place (Phase 14). Details:
[`docs/user-guide/install-native.md`](docs/user-guide/installation.md) and
[`docs/dev-guide/setup.md`](docs/dev-guide/setup.md).

**Transcription engine (optional extra).** Real transcription and speaker diarization need
`uv sync --extra ml` (WhisperX, PyTorch, pyannote.audio; about 6 GB), an NVIDIA GPU with a CUDA 12.8
capable driver (570+; no CUDA toolkit install needed) or patience on the CPU, and about 2 GB more
for the default models. Speaker diarization uses a gated model: accept its terms at
<https://huggingface.co/pyannote/speaker-diarization-community-1>, set a Hugging Face read token
(`secrets.hf_token`), then run `uv run mm3 models download`. After that everything runs offline.
Guide: [`docs/user-guide/transcription.md`](docs/user-guide/transcription.md).

**Speaker names.** Each job pauses so you can name its speakers (with sample clips to listen to).
Optional voice recognition (`privacy.voiceprints_enabled: true`, off by default) remembers the voices
you choose and suggests their names in later meetings; `uv run mm3 voiceprints list|delete|wipe`
manages what is stored. Guide: [`docs/user-guide/speakers.md`](docs/user-guide/speakers.md).

**Notes and templates.** 23 built-in templates (Default Notes, Executive Summary, Decision Log, Action-Focused,
Job Interview Notes, Board Minutes, Stand-up, Retrospective and more; see the
[catalogue](docs/user-guide/template-catalogue.md)) are copied into your vault's `MeetingMaster3/templates/` folder,
where you can edit them or add your own. Action items are Obsidian checkboxes with an owner only when
someone actually took the task on; long meetings are summarised in parts so nothing is skipped. Cloud
models are used only after you confirm. Guide: [`docs/user-guide/templates.md`](docs/user-guide/templates.md).

**Settings, templates and your data.** The **Settings** screen edits everything in `config.yaml` (vault, transcription, language-model backends with write-only API keys and connection tests, audio retention, voiceprints, diagnostics). The **Templates** screen lets you star, preview, edit, duplicate, create and reset templates, which stay plain files in your vault. Rate notes and sections (stored only on your computer), download a note, transcript or zip, and export all your data. Guide: [`docs/user-guide/settings.md`](docs/user-guide/settings.md).

## Configuration
Settings come from `config.yaml`, overridden by `MM3_*` environment variables. Run `uv run mm3 config path`
to see where files live. Every setting is documented in
[`docs/user-guide/configuration.md`](docs/user-guide/configuration.md).

## Hardware guidance
MeetingMaster3 detects your GPU and recommends settings; run `uv run mm3 doctor` to see them for your
machine. The 8 GB row is **measured** on the reference laptop (RTX 2070 Max-Q, Phase 15); the others
are **estimates** from the specification (no such hardware was available to measure). Method and raw
numbers: [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md); settings: [`docs/user-guide/hardware.md`](docs/user-guide/hardware.md).

| Profile | Whisper model | Diarization | Speed (x real time) | Local LLM (Ollama) |
|---|---|---|---|---|
| CPU only | small / medium, int8 | optional | 0.5-2 (estimated) | 3-4B, or a cloud backend |
| 8 GB VRAM | large-v3-turbo, int8_float16 | yes | 13-16 (measured: 60 min in about 4-5 min) | 7-9B at Q4_K_M (measured: qwen3:8b adds 3-4 min per hour) |
| 16 GB VRAM | large-v3, float16 | yes | 30-50 (estimated) | 12-14B at Q4_K_M |
| 24 GB+ VRAM | large-v3, float16 | yes | 40-70 (estimated) | about 30B at Q4_K_M |

On 8 GB, transcription and the LLM take turns on the GPU (peak 2.8 GB for transcription, about 6 GB
for qwen3:8b). With Ollama's flash attention and 8-bit context cache turned on
([how](docs/user-guide/hardware.md#ollama-settings-for-small-gpus-recommended-on-8-gb)), a 60-minute
meeting goes from upload to a finished note in about 6-7 minutes with a short template such as
Executive Summary, or about 8-9 minutes with the default, Default Notes, which writes much fuller
notes; with Ollama's default settings notes take about twice as long
([measurements](docs/PERFORMANCE.md)). Override auto-detection with `hardware.profile` in `config.yaml`.

## Known limitations
- **No login.** Single user on `127.0.0.1`; do not expose the port (use an SSH tunnel for remote
  access). See [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) for the residual risks.
- **English-first.** Other languages are transcribed (with a warning), but the templates and the
  task-owner cues are English; note quality in other languages is not evaluated.
- **The ML stack carries known advisories** (torch 2.8, transformers 4.57, nltk) that WhisperX's pins
  block; they concern loading untrusted model files, which the app does not do (ADR-0014).
- **Local notes on long meetings are slower than transcription**: about 4-5 minutes per hour of audio
  with an 8B model on 8 GB (map-reduce); regenerating one section of a long meeting repeats that work.
- **Voice recognition** was tuned on a few recordings (threshold 0.6); suggestions always need your
  confirmation.
- **Cloud models vary.** Claude, Llama 4, Qwen3, GLM, Mistral Large and GPT-5.5 write good notes; models
  that only reason (DeepSeek R1, gpt-oss) often return nothing within a section's allowance, Mistral 7B/Mixtral on
  Bedrock reject system prompts, and some models are only callable through an inference profile. The model
  model pickers list only models that can write notes, with prices (live for OpenRouter, a dated table for
  Bedrock), an estimated cost per meeting and Best value / Best quality picks; Bedrock prices exist only for the
  model families in the table, and the listing cannot tell whether your account has access to a model.
- Only measured on one 8 GB laptop GPU; tested in Chromium (Firefox and Safari not tested).

## FAQ
_Coming in Phase 16._

## Documentation and project files
- [Specification](docs/MM3_SPECIFICATION.md) (section 15 amendments override sections 1-14)
- [Implementation plan](MM3_IMPLEMENTATION_PLAN.md) and [decision log](docs/MM3_DECISIONS.md)
- [Contributing](CONTRIBUTING.md) · [Code of Conduct](CODE_OF_CONDUCT.md) · [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)

## License
Apache-2.0. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). The logo and hero picture
(`src/meetingmaster3/web/static/brand/`) are released by Nick Antonizick under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/): free to keep and reuse. Model weights are not bundled and carry
their own terms; see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
