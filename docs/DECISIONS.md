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
| ADR-0009 | 2026-10-11 | LLM adapters: plain httpx for Ollama and OpenAI-compatible, boto3 for Bedrock; typed backend config; remote Ollama counts as cloud | Accepted | 08 |
| ADR-0010 | 2026-10-11 | Companion transcript: readable turns plus one hidden JSON-lines data block at the end | Accepted | 03 |
| ADR-0011 | 2026-10-11 | Line endings: preserve the file's own; LF for new files | Accepted | 03 |
| ADR-0012 | 2026-10-11 | Note round-trip: verbatim user bytes, per-key frontmatter reuse, strict markers charged to the outer section, lenient properties | Accepted | 03 |
| ADR-0013 | 2026-10-11 | Jobs: stdlib sqlite3 (WAL), thread-pool stages with a GPU semaphore held per GPU block, artifact checkpoints, generic input pauses, streamed uploads, retention by current setting incl. unfinished jobs | Accepted | 04 |

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

## ADR-0009: LLM adapter implementation choices
**Context.** Phase 08 needs three adapters behind one interface, with small dependencies, testable offline, and a consent rule keyed on where data goes.
**Options considered.** OpenAI-compatible: official `openai` SDK vs plain httpx. Ollama: `ollama` Python package vs plain httpx. Bedrock: boto3 vs raw signed HTTP. Backend config: free-form dicts vs a typed model.
**Decision.** (1) **Plain httpx** for Ollama and OpenAI-compatible: httpx is already a runtime dependency, the surface used is four endpoints, SSE and NDJSON parsing is about 20 lines each, and it mocks cleanly with respx; the SDKs add dependencies and hide retry and logging behaviour we must control (no body logging, bounded retries). (2) **boto3** (`bedrock` extra, lazy import) for Bedrock: SigV4, the credential chain and the event-stream decoder are not worth re-implementing. Calls run in threads; a stream's worker thread is told to stop on cancellation. (3) **Typed `BackendConfig`** (pydantic, `SecretStr` api_key) replaces the Phase 02 placeholder `dict[str, dict]`, so masking, saving and validation are uniform. (4) **Locality** is derived from the URL host: loopback and `host.docker.internal` are local; anything else, including a LAN Ollama, is treated as cloud for consent. Bedrock is always cloud. (5) Kinds are `ollama`, `openai_compat`, `openrouter`, `openai`, `bedrock`; the last three OpenAI-style kinds are presets of one class. (6) Unknown context windows fall back to 8192 tokens (conservative) unless the config sets `context_window`. (7) The Ollama `num_ctx` is sized from the prompt (min 4096, capped at the model maximum), because Ollama's default silently truncates long prompts.
**Consequences.** Adding a backend is one module plus a `register_kind` call. Bedrock cannot report context sizes, so cloud users should set `context_window`. Phase 05's `check_ollama` read `llm.backends` as raw dicts; whichever phase merges second must switch it to the registry (`llm.doctor.check_backends`).

## ADR-0010: Companion transcript data embedding
**Context.** Re-open and regeneration must recover segments, timings, labels and word timings from the vault alone (spec §9), while the companion stays pleasant to read in Obsidian. The Phase 03 prompt offered an HTML comment per turn or a data block at the end.
**Options considered.**

| Option | Pros | Cons |
|---|---|---|
| A. `<!-- mm3:seg ... -->` comment before each turn | Data sits next to its text; a turn's edits map to its segments | A merged turn has several segments, so each comment grows a list; word timings make every turn long; hundreds of comments clutter Live Preview and source mode |
| B. One hidden data block at the end (JSON lines) | Readable part stays clean; words fit compactly; trivial and robust to parse; one segment per line diffs well | Data and text are far apart; edits to the readable text are not reflected in the data |
| C. Sidecar `.json` file | Cleanest Markdown | A second file to sync and keep paired; breaks "the vault is self-contained Markdown" |

**Decision.** B. The block is `<!-- mm3:transcript-data v1`, a JSON header line, one JSON object per segment, then `-->`. JSON is ASCII-only with `<` and `>` escaped, so transcript text can never close the comment. The data block is the source of truth; the readable turns are derived. If the user edits the readable text, `body_matches_data` turns false and their text is kept as written. Speaker renames rewrite only turn-heading names, matched by turn position, and refuse rather than guess when turns were restructured.
**Consequences.** About 25 bytes per word: roughly 250 KB for a one-hour meeting with word timings. That is fine for Obsidian, but large; a later option could drop words for very long meetings. Edits to the readable text do not flow back into regeneration input (Phase 11 can surface `body_matches_data`). Format details: `docs/dev-guide/note-format.md` §6.

## ADR-0011: Line-ending policy
**Context.** Notes may arrive with CRLF (Windows editors, some sync tools) or mixed endings. The phase requires that content outside markers stays byte-identical, and that an unchanged file re-renders exactly.
**Options considered.** (A) Normalise everything to LF on read. (B) Preserve: keep user bytes exactly and write MM3 content in the file's own style. (C) Always write CRLF on Windows-like files only.
**Decision.** B. A file's style is its first line break; user text (including mixed endings) is stored verbatim; MM3-written content (sections, re-emitted properties) uses the file's style; new files are LF. Section *bodies* are normalised to LF in the domain model and converted on write. Lines are split on `\n` only, never `str.splitlines`, so Unicode separators are ordinary characters. Files are read with `newline=""`.
**Consequences.** Byte-identity holds for any input (verified by Hypothesis with CRLF and mixed input). A mixed-ending file gets its new content in the style of its first line, which is acceptable.

## ADR-0012: Note round-trip rules
**Context.** The vault is the source of truth and users edit notes freely in Obsidian. MM3 must re-open, regenerate one section and save without disturbing anything else, and it must never guess around damaged markers (R11).
**Decision.**
1. **Document model.** A note is frontmatter metadata plus an ordered list of `TextBlock | Section`. Text blocks hold user bytes verbatim; sections are normalised. `parse_note` returns a `ParsedNote` that also keeps the raw bytes; `render_note(note, base=parsed)` reuses them for everything unchanged. Without `base`, rendering is canonical, and `parse(render(note)) == note`.
2. **Frontmatter reuse per key.** Each top-level key's raw text (and any comment lines after it) is kept, located with PyYAML's composer and verified by re-parsing each chunk. Unchanged keys keep their bytes; the whole block is verbatim when nothing changed. Unchanged means the *domain* value is equal, so a user's `participants: Alice, Bob` stays as typed until the participants really change. Comment preservation needs no new dependency (no ruamel.yaml, in line with ADR-0007).
3. **Strict markers, outer-section blame.** A section is valid only when its two markers are adjacent marker lines and unique. Nesting errors are charged to the outer section, so an unclosed section does not make every later section unusable, and the R11 "append a fresh section" path always produces a usable section.
4. **Lenient properties.** Hand-edited properties are understood where the intent is clear and otherwise ignored with a warning; only a missing or invalid `mm3-id` stops parsing.
5. **Wikilink targets** cannot contain `[`, `]` or `|` (domain validation), so a link can never be mis-read as an alias.
6. **Markers inside code fences** are still markers (a simpler, predictable grammar); MM3 refuses to write content that contains marker-like lines.
7. **`MeetingMeta.date` is optional**, because a user may delete it; new notes always set it.

**Consequences.** Hypothesis checks the properties at 500 examples each: identity both ways, byte-identity for user-edited files (inserted text, stray and broken markers, trailing whitespace, frontmatter comments, CRLF), byte preservation outside the replaced section, and pure insertion for appends. Frontmatter comments are lost only for keys that actually change. `errors.py` now imports FastAPI lazily so the pure layers do not depend on it.

## ADR-0013: Job runner, storage and retention design
**Context.** Phase 04 needs durable job state, checkpointed stages that survive restarts, one GPU job at a time on an 8 GB card, live progress, human-in-the-loop pauses, and the R8 audio retention policy, in a single-user app with no external services.
**Options considered.**

| Topic | Option | Pros | Cons |
|---|---|---|---|
| Database access | stdlib `sqlite3` | No dependency; full control of WAL, transactions and threads; tiny schema | Hand-written SQL and row mapping |
| | SQLAlchemy Core | Portable schema DSL, Alembic later | A large dependency for three tables; another abstraction to learn |
| Execution | Threads (`run_in_executor`) | Stages share the process (models stay loaded between GPU stages); simple progress callbacks | A stuck native call cannot be killed; cancellation is cooperative |
| | Subprocess per stage | Hard kill, isolation from native crashes | Models reload per stage (slow, VRAM churn); IPC for progress |
| | Celery/RQ | Mature queueing | Needs a broker; overkill for one user |
| GPU lock scope | Per stage | Simplest | Another job can load models between `transcribe` and `diarize` and OOM an 8 GB card |
| | Per contiguous run of GPU stages | No interleaving while models are resident | A long GPU block delays other jobs' GPU work (acceptable, it is serial anyway) |
| Speaker confirmation | Dedicated `/speakers` route now | Matches Phase 07's eventual URL | Phase 06's language gate needs the same pause |
| | Generic `InputRequired` + `POST /input` | One mechanism for every pause; stages validate their own answers | Phase 07 adds friendlier routes on top |

**Decision.**
1. **stdlib `sqlite3`**, one shared connection (lock-guarded, WAL), forward-only numbered migrations in code.
2. **Stages run in a thread pool**; GPU stages are serialised by one `asyncio.Semaphore(1)` held across each contiguous run of GPU stages of a job. Cancellation is cooperative (`ctx.check_cancelled()`), and a server stop marks running jobs `interrupted`. Interrupted jobs are not auto-resumed at startup (a job that crashed the server would crash it again); queued jobs are.
3. **Checkpoints** are artifact files in the job folder, recorded by name in `job_stages`; resume starts at the first stage that is not completed or whose artifact is missing. Stages must write artifacts atomically inside the job folder.
4. **Pauses** use `InputRequired` and `POST /api/jobs/{id}/input`; the answer is saved as `input.<stage>.json` and the stage re-runs to consume it.
5. **Uploads** are parsed with python-multipart's streaming `MultipartParser` and written straight to the job folder (mode `0600`), so the size limit is enforced while streaming and audio never sits in `/tmp` (Starlette's `request.form()` spools to a temp file first). The upload is probed before the job is created; a rejected upload leaves nothing behind.
6. **Retention** keeps `privacy.audio_retention` as the Phase 02 enum (`forever` / `days` / `delete_after_write`) rather than the prompt's `null`/`0` encoding of `audio_retention_days`. The pruner applies the **current** setting to every written job from its `written_at` (so switching to *forever* also keeps older audio), records `audio_expires_at` for display, and also prunes the audio of unfinished jobs `audio_retention_days` after their last change (unless *forever*), so abandoned uploads do not stay forever. Pinned and active jobs are never pruned; only audio files are deleted.
7. **Job ids** are UUIDv4 strings, validated before any path is built; `jobs.audio_path` and artifact paths are file names relative to the job folder, so the data folder can move (Docker volumes).

**Consequences.** No new runtime dependencies. A native call that ignores cancellation keeps its thread until it returns (Phase 06 must check for cancellation between chunks). Phase 07 builds its `/speakers` routes on `JobRunner.submit_input`, and Phase 06 uses `should_retry` for OOM and `InputRequired` for the language gate. Unfinished jobs lose their audio after the retention period; the spec records this as R19.

## ADR-0014: Transcription stack pins, diarization model and stage design
**Context.** Phase 06 turns the placeholder `transcribe`, `align` and `diarize` stages into real WhisperX
stages that must run on the 8 GB reference GPU (RTX 2070 Max-Q, driver 610, CUDA 13.3 capable), degrade
gracefully, and keep the app local-first (S5, S6, R5, R14).
**Options considered.**

| Topic | Option | Pros | Cons |
|---|---|---|---|
| Pins | Pin only `whisperx==3.8.6`; the lockfile pins the rest | One known-good combination (verified on the GPU); the lock is the source of truth | Upgrading needs a deliberate re-test |
| | Loose `whisperx>=3.8` | Easy upgrades | Silent pyannote/torch API changes (pyannote 3 → 4 changed `use_auth_token` to `token`) |
| Model residency | Keep models loaded from `transcribe` to `diarize` | Saves about 5-10 s of loading per job | Whisper (about 3 GB) sits idle during diarization on an 8 GB card; complicates OOM recovery and resume |
| | Each stage loads and frees its own model | At most one model resident; a retry or resume starts clean | Reloads models per job |
| Transcription model option | Reuse `JobOptions.model` | Matches the Phase 04 prompt's example | `model` already means the LLM model next to `backend` (Phase 09 `--model`, Phase 10 "backend and model") |
| | New `transcription_model` option | Unambiguous | Phase 10 prompt and the jobs guide change |
| "Proceed" on non-English audio | Force English decoding (spec §3 wording) | Literal spec | Whisper forced to English on foreign speech translates or hallucinates; useless transcript |
| | Transcribe in the detected language, optional language override | Useful transcript; alignment models exist for many languages | Notes templates are English, so note quality varies (warned) |
| Non-diarized fallback labels | Everyone `SPEAKER_00` | Single-speaker shape | Attributes everything to one named person after naming |
| | No speaker labels (`diarized=false`) | Honest; renders as "Speaker" | Phase 07 has nothing to confirm (correct) |

**Decision.**
1. **Pins (verified by installing on the reference machine):** `ml` extra = `whisperx==3.8.6`, which locks
   torch 2.8.0+cu128 / torchaudio 2.8.0 / torchvision 0.23.0, faster-whisper 1.2.1, ctranslate2 4.8.2,
   pyannote.audio 4.0.7, transformers 4.57.6, huggingface-hub 0.36.2, nvidia-cudnn-cu12 9.10.2.21 and the
   CUDA 12.8 wheels. CUDA and cuDNN come from PyPI wheels, so no system CUDA toolkit is needed; the NVIDIA
   driver must support CUDA 12.8 (570+). CTranslate2 4.8 uses the same cuDNN 9 as torch 2.8, so the
   classic CTranslate2/cuDNN 8 mismatch does not occur. CTranslate2 reports `float16`, `int8_float16`,
   `int8`, `int8_float32` and `float32` on the Turing GPU.
2. **Diarization model (R14):** WhisperX 3.8.6 defaults to `pyannote/speaker-diarization-community-1`
   (pyannote.audio 4, CC-BY-4.0, gated; accept at https://huggingface.co/pyannote/speaker-diarization-community-1).
   It is self-contained (segmentation, WeSpeaker embedding and PLDA in one repository), so no second gated
   model is needed. Voice activity detection uses the pyannote weights bundled in the WhisperX wheel (no
   download, no token). English alignment uses torchaudio `WAV2VEC2_ASR_BASE_960H`.
3. **Each stage loads and frees its own model**; the GPU semaphore still spans the GPU stages so no other
   job interleaves. A cached whisper model is loaded with `local_files_only`, and a cached diarization
   pipeline from its snapshot folder, because both libraries otherwise contact Hugging Face on every job.
4. **`transcription_model`** (plus `compute_type`, `batch_size`, `language`, `on_non_english`) are new job
   options; `model` stays the LLM model. "Retry with a smaller model" = resume with
   `{"overrides": {"transcription_model": "<smaller>"}}`, offered in `detail.error.details.suggested_overrides`
   (new optional `MM3Error.details`).
5. **Language gate:** detection on the first 30 s after the model loads; non-English pauses with
   `InputRequired("language")` (policy `transcription.on_non_english`: `ask`/`proceed`/`abort`). Proceed
   transcribes in the detected language unless the answer names another; abort cancels and forgets the
   answer so a resume asks again.
6. **OOM:** one automatic retry per stage (`transcribe`: half batch, `int8_float16`); a second OOM fails
   `transcribe` with `E_OOM`, while `align`/`diarize` fall back with a warning.
7. **Non-diarized transcripts have no speaker labels.** Segments are split where the word-level speaker
   changes, because WhisperX segments are VAD chunks of up to 30 s that often hold two speakers.
8. **Stage warnings:** `StageContext.warn()` records user-visible warnings (fallbacks, language, OOM retry)
   in the stage detail and the job description.
9. **No telemetry:** pyannote.audio 4 sends OpenTelemetry traces to `otel.pyannote.ai` by default (model
   names, audio duration, speaker counts, a session id). MeetingMaster3 forces
   `PYANNOTE_METRICS_ENABLED=false`, `HF_HUB_DISABLE_TELEMETRY=1` and `DO_NOT_TRACK=1` before any ML import.

**Gotchas recorded.** torchcodec 0.7 (a pyannote dependency) only loads FFmpeg 4-7 shared libraries; on a
host with FFmpeg 8 (Arch, October 2026) it warns at import. Harmless because MeetingMaster3 always passes
in-memory waveforms; the warning is filtered. WhisperX's `get_logger` installs its own stdout handler and
disables propagation, bypassing the redaction filter, unless the `whisperx` logger already has a handler;
the engine adds a `NullHandler` and re-enables propagation before importing it.

**Measured (reference machine, large-v3-turbo, int8_float16, batch 8, diarization on).** 60 s fixture:
18 s including model loading. 31 min: transcribe 38 s, align 27 s, diarize 66 s (131 s, 14.3x). 72 min:
74 s / 55 s / 154 s (283 s, 15.3x). Peak whole-card VRAM 3.6 GB with Ollama unloaded. Recorded as
`measured` in `hardware/recommendations.yaml` (vram8: 14-16x).
**Status.** Accepted (2026-10-11, Phase 06).
**Consequences.** Upgrading WhisperX or pyannote needs the GPU acceptance test re-run. Phase 07 can ask
`DiarizationPipeline` for speaker embeddings (`return_embeddings=True`) or compute its own. Phase 10's
"retry with smaller model" and the language prompt use the interfaces above. Spec amendment R20.
