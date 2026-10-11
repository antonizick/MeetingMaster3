# Architecture Decision Log

Lightweight ADRs. Append new decisions at the bottom, and never rewrite history: to reverse a decision, add a new entry that supersedes the old one. Every phase that makes a non-trivial technical choice adds an entry here.

| ID | Date | Decision | Status | Phase |
|---|---|---|---|---|
| ADR-0001 | 2026-10-11 | License: Apache-2.0 | Accepted | 00 |
| ADR-0002 | 2026-10-11 | Frontend: Jinja2 + HTMX + Alpine.js, vendored assets, no CDN | Accepted | 00 |
| ADR-0003 | 2026-10-11 | Templates: 22, staged (5 in Phase 09, 17 in Phase 13) | Accepted | 00 |
| ADR-0004 | 2026-10-11 | LLM backends: Ollama, Bedrock, OpenAI-compatible (OpenRouter preset) | Accepted | 00 |
| ADR-0005 | 2026-10-11 | Python 3.12 + uv; SQLite for app state; XDG paths | Accepted (verified 2026-10-11, Phase 02) | 00, 02 |
| ADR-0006 | 2026-10-11 | Audio retention: Opus for 90 days, then auto-delete; pin; opt-in vault copy | Accepted | 00 |
| ADR-0007 | 2026-10-11 | Config: PyYAML + pydantic-settings, `MM3_<SECTION>__<FIELD>` env names, header-only CSRF | Accepted | 02 |
| ADR-0008 | 2026-10-11 | Process: phases are claimed by a status commit on `main` and run in per-phase worktrees | Accepted | process |

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
**Status.** Accepted (verified 2026-10-11, Phase 02).
**Verification.** uv 0.13.0 provisioned CPython 3.12.15. `uv pip compile` for `whisperx torch pyannote.audio` with `--python-version 3.12 --python-platform x86_64-unknown-linux-gnu` resolved cleanly: whisperx 3.8.6, torch 2.8.0, torchaudio 2.8.0, pyannote-audio 4.0.7, faster-whisper 1.2.1, ctranslate2 4.8.2, nvidia-cudnn-cu12 9.10.2.21. The same command for 3.14 also resolved, but to an older whisperx (3.7.2); 3.12 gets the newest stack and the widest wheel coverage, so the pin stays. Nothing was installed; real GPU behaviour is verified in Phase 06. `requires-python` is `>=3.12,<3.13`. SQLite itself arrives in Phase 04.

## ADR-0006: Audio retention is time-boxed and compressed
**Context.** Audio is only needed for review playback and possible re-transcription; notes and regeneration need only the transcript. Keeping it forever grows disk use and leaves sensitive recordings around indefinitely. Deleting it immediately loses playback. The owner's vault is synced, so copying audio into the vault by default would upload every recording to other devices.
**Options considered.** (A) keep forever; (B) delete after write; (C) keep N days; (D) copy into the vault.
**Decision.** C with a **90-day** default (owner's choice), stored as Opus at about 24 kbps (about 11 MB/h instead of about 115 MB/h of WAV); per-meeting pin; D available as an opt-in. See SPECIFICATION §15.2 R8.
**Consequences.** Meetings re-opened after 90 days have no audio unless pinned; the UI degrades gracefully. Pruning must be reliable and tested.

## ADR-0007: Configuration stack and CSRF mechanism
**Context.** Phase 02 needs a settings model with the precedence defaults < YAML < environment, secrets that never leak, and CSRF protection for an HTMX UI.
**Options considered.** YAML: PyYAML vs ruamel.yaml (comment-preserving). CSRF: header only vs header plus form field.
**Decision.** (1) **PyYAML** with `safe_load`/`safe_dump`. The app is the only writer of `config.yaml` and the Settings UI (Phase 12) round-trips structured data, so comment preservation is not needed; this avoids an extra dependency. Revisit if users hand-edit heavily commented files and expect comments to survive a UI save. (2) **pydantic-settings** with prefix `MM3_` and `__` nesting; YAML values are passed as init kwargs and the source order is changed so environment variables outrank them. (3) `SecretStr` for every secret, masked in dumps; saved atomically (`tempfile` + `os.replace`) at `0600`. (4) CSRF is a **double-submit cookie** (`mm3_csrf`, `SameSite=Strict`) checked against the `X-CSRF-Token` **header only**, plus an Origin check; reading a form body in middleware would buffer uploads, and HTMX sends headers natively. (5) `.env` files are not read by the app.
**Consequences.** Plain HTML forms need a JS shim or a later form-field fallback (noted in the Phase 10 prompt and SECURITY.md). Environment names for nested settings differ from the early `.env.example` placeholders (`MM3_HOST` became `MM3_SERVER__HOST`); `.env.example` and later prompts were updated.

## ADR-0008: Phases are claimed on `main` and run in per-phase worktrees
**Context.** Several agents run phases at once (for example 03, 05 and 08 on 2026-10-11). The old rule ("set `🔄 In progress`, then create the branch") left the status change on the phase branch, or uncommitted in a worktree, so `main` still showed `⬜ Not started` and other sessions could not tell which phases were taken. Agents sharing one checkout also risk switching branches under each other.
**Options considered.** (A) Keep the rule and just emphasise it; (B) claim with a status-only commit on `main` before branching; (C) a separate lock file or a hook that blocks edits until a claim exists.
**Decision.** B, plus one worktree per phase (`../MeetingMaster3-phase-NN`) with the main checkout always on `main`. `/phase` will not start a phase's Tasks until the claim is visible in `git show main:IMPLEMENTATION_PLAN.md`; `⛔ Blocked` is committed to `main` the same way; `/phase status` reports drift between the table and live branches or worktrees. C was rejected as heavier than needed; revisit it if claims are still skipped.
**Consequences.** `main` gains small `chore(plan): start phase NN` commits. Merges of parallel phases may conflict in the plan and changelog; the close-out checklist says to keep both sides. Each worktree needs its own `uv sync`.
