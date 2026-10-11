# Architecture

> **Status:** skeleton from Phase 01. Expanded by every phase that adds a component. The canonical
> design is [`SPECIFICATION.md`](SPECIFICATION.md) (section 15 amendments win over sections 1-14).

## System shape
Single-user, local-first web app. A FastAPI backend serves server-rendered Jinja2 pages with HTMX and
Alpine.js (all assets vendored, no CDN), pushes progress over SSE, and writes Markdown into the user's
Obsidian vault, which is the source of truth. Bound to `127.0.0.1:8765` by default.

## Components (spec section 4)
1. Upload and job orchestration service
2. Transcription and diarization pipeline (WhisperX)
3. Speaker mapping and voiceprint store
4. Template engine and prompt assembler
5. LLM backend abstraction and model recommender (Ollama, Bedrock, OpenAI-compatible)
6. Markdown writer/parser (round-trip)
7. Settings and config manager
8. Feedback collector

## Key refinements from section 15
- Python 3.12 + uv; package `meetingmaster3` in `src/`; CLI `mm3` (R1, R2).
- XDG paths for config, data and model cache, overridable by `MM3_*` variables (R3).
- Per-stage checkpoints in SQLite and job artifacts; resume from the first incomplete stage (R4).
- One GPU job at a time, with explicit VRAM handoff before the LLM stage (R5).
- Map-reduce note generation when the transcript exceeds about 70% of the context window (R6).
- Audio normalised to 16 kHz mono WAV, kept as Opus for 90 days by default (R7, R8).
- Strict section markers so regeneration never touches content outside them (R11).
- Security baseline S1-S8 applies to every component.

## Target layout
```
src/meetingmaster3/
  config/ domain/ markdown/ vault/ storage/ jobs/ audio/ hardware/
  transcription/ speakers/ llm/ templates/ feedback/ web/ starter_templates/
```
Full tree: `prompts/_shared-instructions.md` section 2. ML imports are lazy, inside
`transcription/` and `speakers/` only.

_To be expanded in Phases 02-15 (module responsibilities, data flow, job state machine, sequence diagrams)._
