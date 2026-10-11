# Architecture Decision Log

Lightweight ADRs. Append new decisions at the bottom, and never rewrite history: to reverse a decision, add a new entry that supersedes the old one. Every phase that makes a non-trivial technical choice adds an entry here.

| ID | Date | Decision | Status | Phase |
|---|---|---|---|---|
| ADR-0001 | 2026-10-11 | License: Apache-2.0 | Accepted | 00 |
| ADR-0002 | 2026-10-11 | Frontend: Jinja2 + HTMX + Alpine.js, vendored assets, no CDN | Accepted | 00 |
| ADR-0003 | 2026-10-11 | Templates: 22, staged (5 in Phase 09, 17 in Phase 13) | Accepted | 00 |
| ADR-0004 | 2026-10-11 | LLM backends: Ollama, Bedrock, OpenAI-compatible (OpenRouter preset) | Accepted | 00 |
| ADR-0005 | 2026-10-11 | Python 3.12 + uv; SQLite for app state; XDG paths | Proposed (verify in Phase 02) | 00 |
| ADR-0006 | 2026-10-11 | Audio retention: Opus for 90 days, then auto-delete; pin; opt-in vault copy | Accepted | 00 |

---

## ADR-0001: License is Apache-2.0
**Context.** The project must be free, open-source and publishable on GitHub. Its dependencies (WhisperX BSD-2, faster-whisper MIT, pyannote.audio MIT, FastAPI MIT) are all permissive.
**Decision.** Apache-2.0, with a `NOTICE` file.
**Consequences.** Permissive license with an explicit patent grant, suited to wide adoption. Model weights (Whisper, pyannote gated models, LLMs) have separate terms, documented in `THIRD_PARTY_NOTICES.md` and never redistributed in the image.

## ADR-0002: Server-rendered UI with HTMX + Alpine.js
**Context.** Single-user local web UI. The PrePlan says to avoid heavy frameworks, and local-first privacy rules out CDNs.
**Decision.** FastAPI + Jinja2 templates, HTMX for server interactions, Alpine.js for local state, and a small number of vendored libraries (Markdown editor, diff renderer). Progress is pushed over SSE.
**Consequences.** Everything stays in Python, there is no Node build step, the image is smaller and a strict CSP is possible. The synced audio/transcript view needs careful hand-written JS (Phase 11).

## ADR-0003: 22 templates in two stages
**Context.** The PrePlan lists 5 starters and the design notes list 20, with partial overlap.
**Decision.** Ship the 5 PrePlan starters in Phase 09 and the remaining 17 in Phase 13.
**Consequences.** The end-to-end flow is proven on 5 templates before the template schema is used at scale.

## ADR-0004: MVP LLM backends
**Decision.** Ollama (default, local), AWS Bedrock (Converse API), and a generic OpenAI-compatible adapter with an OpenRouter preset.
**Consequences.** The generic adapter also covers OpenAI, LM Studio and vLLM. Native Anthropic and Google adapters go on the roadmap.

## ADR-0005: Python 3.12 + uv; SQLite app state; XDG paths
**Context.** The host has Python 3.14, which torch/WhisperX/pyannote are unlikely to support yet. The PrePlan leaves "local app data" unspecified.
**Decision.** Pin 3.12 via uv. Store jobs, checkpoints, voiceprints, feedback and recents in SQLite. Use XDG config/data/cache dirs, with Docker volumes in containers. See SPECIFICATION §15.2 R1–R3.
**Status.** Proposed. Phase 02 confirms it with a working install and updates this entry.

## ADR-0006: Audio retention is time-boxed and compressed
**Context.** Audio is only needed for review playback and possible re-transcription; notes and regeneration need only the transcript. Keeping it forever grows disk use and leaves sensitive recordings around indefinitely. Deleting it immediately loses playback. The owner's vault is synced, so copying audio into the vault by default would upload every recording to other devices.
**Options considered.** (A) keep forever; (B) delete after write; (C) keep N days; (D) copy into the vault.
**Decision.** C with a **90-day** default (owner's choice), stored as Opus at about 24 kbps (about 11 MB/h instead of about 115 MB/h of WAV); per-meeting pin; D available as an opt-in. See SPECIFICATION §15.2 R8.
**Consequences.** Meetings re-opened after 90 days have no audio unless pinned; the UI degrades gracefully. Pruning must be reliable and tested.
