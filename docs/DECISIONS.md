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
| ADR-0014 | 2026-10-11 | Transcription stack pins, diarization model and stage design | Accepted | 06 |
| ADR-0015 | 2026-10-11 | Speaker embeddings, voiceprint matching and threshold | Accepted | 07 |
| ADR-0016 | 2026-10-11 | Map-reduce for long meetings | Accepted | 09 |
| ADR-0017 | 2026-10-11 | Prompt layout, default temperatures and deterministic aids for small models | Accepted | 09 |
| ADR-0018 | 2026-10-11 | Generation and write stages: consent pause, idempotent writes, fake pipeline | Accepted | 09 |
| ADR-0019 | 2026-10-11 | Server-rendered UI with HTMX partials, SSE as a trigger, Alpine CSP build | Accepted | 10 |
| ADR-0020 | 2026-10-11 | Settings screen: declarative fields, all-or-nothing validation, write-only secrets | Accepted | 12 |
| ADR-0021 | 2026-10-11 | Feedback ratings and data export | Accepted | 12 |
| ADR-0022 | 2026-10-11 | Optional copy of the retained audio into the vault (R8) | Accepted | 12 |
| ADR-0023 | 2026-10-11 | Stage-2 template library: shared section ids, one exception to AI Recommendations, type-aware eval | Accepted | 13 |
| ADR-0024 | 2026-10-11 | Review editor: textareas per note part instead of CodeMirror 6 | Accepted | 11 |
| ADR-0025 | 2026-10-11 | Review workspace save model: base snapshots, conflict check, accept-then-save | Accepted | 11 |
| ADR-0026 | 2026-10-11 | Docker images: python:3.12-slim + torch's own CUDA wheels; host-network override for Ollama | Accepted (base image superseded by ADR-0027) | 14 |
| ADR-0027 | 2026-10-12 | Docker base image moves to Debian 13 (trixie); no curl or system pip at run time | Accepted | 15 |
| ADR-0028 | 2026-10-12 | Phase 15 security hardening choices | Accepted | 15 |
| ADR-0029 | 2026-10-12 | Check that a model can write notes before any work, and recover in place | Accepted | pre-release fix |
| ADR-0030 | 2026-10-12 | Interim tuning rounds are numbered 15a, 15b, 15c… | Accepted (generalised by ADR-0034) | process |
| ADR-0031 | 2026-10-12 | Readable transcript, dates without a year, two summaries, note upgrade path | Accepted | 15a |
| ADR-0032 | 2026-10-12 | Logo committed and hidden on meeting pages; all rights reserved | Accepted (licence superseded by ADR-0035) | 15a |
| ADR-0033 | 2026-10-13 | Large logo picture above "New meeting" | Accepted (licence superseded by ADR-0035) | after 15a |
| ADR-0034 | 2026-10-14 | Inserting phases anywhere with `/phase-add` | Accepted | process |
| ADR-0035 | 2026-10-14 | Logo and hero picture released under CC0 1.0 | Accepted; implemented in 15b | 15b |
| ADR-0036 | 2026-10-14 | Review opens in Preview; one retention rule shared by the pruner and the countdown; Keep forever wording | Accepted | 15b |
| ADR-0037 | 2026-10-14 | Tuning round 3 split into 15c/15d/15e; meeting rename updates backlinks after a backup; the Plaud-style template is topic-based and named neutrally | Accepted | 15c, 15d, 15e |
| ADR-0038 | 2026-10-14 | Long review actions are polled background tasks with a smoothed ETA; recording download route; Open a note merged into a paged Meetings page | Accepted | 15c |
| ADR-0039 | 2026-10-14 | Default Notes: topic-based template and new default; template choice on New meeting sticks; `params.detail: high` for richer map-reduce notes | Accepted | 15e |
| ADR-0040 | 2026-10-14 | Renaming a meeting: pure plan, journal with a database commit point, Obsidian-style backlink matching, folder-move rule, backups in app data | Accepted | 15d |
| ADR-0041 | 2026-10-15 | Live cloud backend verification: IAM user access keys, synthetic plus one real meeting, Bedrock required and OpenRouter if keyed, about USD 5 per provider | Accepted (planning) | 15g |
| ADR-0042 | 2026-10-15 | Cloud model picker: capable-model filter, live OpenRouter prices and a dated Bedrock price table, Best value / Best quality recommendations; split from 15g | Accepted | 15h |
| ADR-0043 | 2026-10-15 | `num_ctx` is the note's largest real call plus a measured 10 % margin (no double-counted reserve); map chunks count timestamps; reduce notes counted at 1.15× density; Ollama flash attention + q8_0 cache recommended | Accepted | 15f |
| ADR-0044 | 2026-10-15 | Bedrock context windows from a dated, family-level table (`bedrock_models.yaml`, longest prefix, geo profile ids stripped, Claude capped at 200k); unknown models keep 8192 with a visible hint | Accepted | 15g |
| ADR-0045 | 2026-10-15 | Bedrock follows a model's own ValidationException advice once (drop `temperature`; thinking off as `disabled`/`between_tools`/effort `low`) and remembers it; an empty answer cut off by length or a filter is an `E_LLM_BAD_RESPONSE`; real Bedrock validation texts map to `E_LLM_CONFIG`; OpenRouter addendum: `reasoning` switch with a low-effort fallback, provider reasons on 4xx | Accepted | 15g |

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
**Known vulnerabilities accepted (pip-audit, 2026-10-11).** The `ml` extra carries advisories in torch
2.8.0 (fixed in 2.9-2.13, including CVE-2026-24747 in the `weights_only` unpickler), transformers 4.57.6
(model-config and checkpoint deserialization, fixed in 5.x) and nltk 3.10.3 (no fix). They cannot be
patched: WhisperX 3.8.6 (and 3.8.7rc1) require `torch~=2.8.0` and `huggingface-hub<1.0`, which excludes
transformers 5.x. Exposure is limited because they need a malicious model or checkpoint file: the app
only loads the pinned faster-whisper repositories (CTranslate2 format, no pickle), torchaudio's wav2vec2
from download.pytorch.org, the WhisperX-bundled VAD weights, the user's cached pyannote snapshot and
WhisperX's fixed per-language alignment repositories. CI's `pip-audit` covers the default install only.
Revisit when WhisperX allows torch 2.10+ (Phase 15).
**Status.** Accepted (2026-10-11, Phase 06).
**Consequences.** Upgrading WhisperX or pyannote needs the GPU acceptance test re-run. Phase 07 can ask
`DiarizationPipeline` for speaker embeddings (`return_embeddings=True`) or compute its own. Phase 10's
"retry with smaller model" and the language prompt use the interfaces above. Spec amendment R20.

## ADR-0015: Speaker embeddings, voiceprint matching and threshold
**Context.** Phase 07 suggests a name for each diarized speaker from an opt-in, local voiceprint store
(S7). It needs an embedding model, a way to score a speaker against a person, a default threshold, and
a privacy design for biometric data on an 8 GB laptop GPU.
**Options considered.**

| Topic | Option | Pros | Cons |
|---|---|---|---|
| Embedding model | **WeSpeaker ResNet34 from the cached `speaker-diarization-community-1` snapshot (`embedding/`)** | Already downloaded and licence-accepted for diarization; 256-d; loads offline from the snapshot folder; seconds per meeting | Tied to the diarization pipeline's weights |
| | WhisperX `DiarizationPipeline(return_embeddings=True)` centroids | No second model load | Centroids come from pyannote's clustering internals (overlap-filtered chunks, PLDA space for VBx), not from our own clean-speech selection; changes with the pipeline version |
| | A separate model (e.g. SpeechBrain ECAPA) | Well documented | Another download, licence and dependency |
| Score | **Max cosine over the person's stored embeddings** | Keeps recordings from different conditions (headset vs laptop) separately useful | One bad enrollment can attract false matches (mitigated by the margin and the cap) |
| | Cosine to the mean of the person's embeddings | Smooths noise | Blurs different conditions together |
| Assignment | **Hungarian over `score − threshold`, plus a margin over the speaker's second-best person** | Two speakers never get the same person; ambiguous speakers (often one person split in two by the diarizer) get no suggestion | Conservative: sometimes no suggestion where a greedy match would have been right |
| Storage | **Two SQLite tables, float32 BLOBs, `model_id` per embedding, capped at 20 per person and model** | Simple, local, model-safe | Linear scan (fine for a personal store) |

**Experiment (2026-10-11, reference machine).** Diarized three recordings (the 60 s AMI fixture and two
private recordings of 31 and 72 minutes, used locally only; numbers only were recorded). For each label
with at least 20 s of speech, the timeline was cut into thirds: centroids from thirds 1 and 2 were
"enrolled" and the centroid from third 3 (45 s target, and a 10 s short probe) was scored. Genuine = same
diarization label, impostor = different labels in the same recording (4 genuine and 9 impostor pairs;
the fixture's speakers had too little speech per third for genuine pairs).

| Score | Genuine (min / median / max) | Impostor (min / median / max) |
|---|---|---|
| Max over two enrollments | 0.930 / 0.948 / 0.958 | 0.002 / 0.160 / 0.430 |
| Mean of two enrollments | 0.925 / 0.942 / 0.968 | −0.023 / 0.158 / 0.418 |
| One enrollment | 0.848 / 0.869 / 0.942 | −0.043 / 0.160 / 0.430 |
| Max, 10 s probe | 0.874 / 0.908 / 0.923 | 0.002 / 0.207 / 0.418 |

Every threshold from 0.45 to 0.75 accepted all genuine pairs and no impostor pair. Across the two private
recordings (different sessions), the dominant speakers scored 0.929 against each other while every other
cross-recording pair stayed at or below 0.365: almost certainly the same person, a real cross-session
genuine pair. Max and mean were within ±0.02 of each other. Embedding all speakers of the 72-minute
recording took 0.3 s on the GPU and 1.6 s on the CPU.
**Decision.**
1. WeSpeaker ResNet34 loaded with `pyannote.audio.Model.from_pretrained(<snapshot>/embedding)`, on CUDA
   when available, otherwise CPU. `model_id` = `<pipeline>/embedding@<first 16 hex of the weights'
   SHA-256>`; embeddings with different ids are never compared.
2. Per speaker: overlap-free parts of its diarization turns, pieces of at least 2 s, cut into windows
   of at most 10 s, longest first up to 45 s (12 windows); centroid = duration-weighted mean, L2
   normalised. Under 10 s of embedded speech the speaker is `low_confidence`.
3. Score = **max** cosine (equal accuracy here, and better suited to mixed recording conditions).
   Default `speakers.match_threshold` **0.6** (a wide gap on both sides of the measured distributions,
   inside the 0.6-0.75 range planned in the phase prompt) and `speakers.match_margin` **0.1**.
4. Enrollment is explicit per speaker (`enroll: true`) and only when `privacy.voiceprints_enabled`. Labels
   confirmed as the same person are merged into one embedding. Re-enrolling from the same job replaces
   that job's embedding. When disabled, no embeddings are computed at all.
5. Biometric hygiene: per-meeting embeddings live only in the job folder (`speaker_embeddings.json`)
   until confirmation and are then deleted; vectors never appear in the API, logs or vault; SQLite runs
   with `secure_delete=ON` and deletes are followed by a WAL checkpoint, so deleted voiceprints are
   physically erased; deleting everything is a two-step call with a single-use token.
**Status.** Accepted (2026-10-11, Phase 07).
**Consequences.** The small experiment does not cover noisy or very short recordings; the threshold is
configurable and Phase 15 can re-measure with more data. A diarization-pipeline upgrade with new
embedding weights starts a new embedding space: old voiceprints are kept but not used until people are
enrolled again. Spec amendment R21.

## ADR-0016: Map-reduce for long meetings
**Context.** R6 asks for map-reduce when the transcript and prompt exceed about 70 % of the model's
context window. On the 8 GB reference GPU an 8B model cannot hold its advertised window next to its
weights (`qwen3:8b` advertises 40 960 tokens), so a one-hour meeting (about 12k tokens) is already
"long" there. Phase 09 needs a design that is correct, resumable and cheap enough on small models.
**Options considered.**

| Option | Pros | Cons |
|---|---|---|
| A. Truncate or sample the transcript | Simple, one call per section | Silently loses decisions and tasks: unacceptable for minutes |
| B. Rolling summary (refine each chunk into a running summary) | Few tokens | Sequential, early detail fades, errors compound, nothing structured to merge |
| C. Per-chunk JSON extraction, deterministic merge, sections from the merged notes | Structured (decisions, actions, questions survive verbatim), parallelisable later, merge and dedupe are testable code | One extra call per chunk; small models produce bad JSON |
| D. Hierarchical summaries of summaries | Scales without limit | Many calls; loses attribution and timestamps |

**Decision.** Option C.
1. *Fit check:* system prompt + transcript + the longest section tail + that section's output limit
   against `llm.budget.fits_window` (70 %). The planned window is `min(model window,
   generation.max_context)` for local backends (default 16 384, sized for 8 GB) and the model window
   for cloud backends.
2. *Map:* `chunk_transcript` on speaker-turn boundaries with one overlap turn; budget per chunk =
   70 % of the window − extraction prompt − 1 500 output tokens. Each chunk returns `{summary, points,
   decisions, actions, questions}` with `[mm:ss]` times and speakers, at temperature 0.1 with JSON
   mode. Decisions, actions and questions come first in the schema and points last, capped at the
   10 most important (at most 20 words each), because the first live run showed qwen3:8b copying
   ~30 transcript sentences as points until the 1 500-token limit cut the JSON on every chunk. Bad
   JSON is repaired locally (code fences, prose around the object, trailing commas, reasoning
   blocks, lenient shapes, and an answer cut off by the limit: the unfinished tail is dropped and
   the brackets closed); otherwise asked once more with the parser error (or, after a cut-off,
   for a shorter answer); a chunk that still fails is skipped with a user-visible warning (all
   chunks failing is an error).
3. *Merge:* concatenate in time order; near-duplicates (normalised equality, containment, or ≥ 80 %
   word overlap) are combined, keeping the earliest timestamp and the clearly more detailed wording;
   the same task for two different named owners is kept twice.
4. *Reduce:* every section is generated from the merged notes (`<meeting_notes>`) instead of the
   transcript; if the notes are still too long, minor points and then chunk summaries are thinned
   evenly (decisions, actions and questions are never cut) with a warning.
**Status.** Accepted (2026-10-11, Phase 09).
**Consequences.** A long meeting costs one extra call per chunk. Regenerating one section of a long
meeting repeats the map step (a cache of the merged notes is a possible optimisation). Chunk
extraction quality depends on the model's JSON discipline; the repair path is covered by tests.

## ADR-0017: Prompt layout, default temperatures and deterministic aids for small models
**Context.** The notes must read like a skilled chief of staff wrote them: specific, attributed, no
invented owners or dates. The default model is a local 7-9B model on 8 GB. The Phase 09 eval (three
synthetic meetings × five templates, `tests/eval/`) showed what prompts alone cannot fix on such
models: owners invented from whoever said "we should…", wrong weekday-to-date arithmetic (even with a
calendar in the prompt, and copying an example date from the prompt), dropped small commitments, and
reasoning models spending the output budget on hidden "thinking".
**Options considered.**

| Topic | Option | Pros | Cons |
|---|---|---|---|
| Layout | One call for the whole note | Fewest calls | Small models lose structure; one bad answer spoils every section; no per-section regeneration |
| | **One call per section, shared prefix** | Regenerable sections, per-section temperature, prompt-cache reuse | N calls |
| Dates | Ask the model to resolve dates | No code | Measured wrong on qwen3:8b |
| | **Deadline as said; code adds the date** | Correct by construction | Only simple forms (weekday, today, tomorrow, next X) |
| Owners | Stronger wording only | No code | Still ~1 in 3 notes wrong in the eval |
| | **Tagged cues in the prompt + owner guard after** | Measured fix (8/15 → 14/15 notes passing) | Heuristic regexes; English only |
| Thinking | Model default | Possibly better reasoning | 2-10× slower, eats `max_tokens` |
| | **`think: false` by default** (`generation.think`) | Fast, predictable | Users of reasoning models opt in |

**Decision.**
1. One chat call per section. The system message (MM3 global rules, the template's `_system` block,
   meeting facts, today's date) and the start of the user message (the transcript as
   `[mm:ss] Name: text` turns, or the map-reduce notes) are identical for every section; only the
   tail (section instructions, task candidates, user instructions, regeneration context, output
   rules) differs. One `num_ctx` per note, so a local Ollama reuses its prompt cache and never
   reloads the model between sections.
2. Temperatures (R6): `extraction` sections 0.2, `narrative` 0.4; templates override per section or
   globally; map extraction 0.1.
3. Task sections get **tagged candidate sentences** from `templates/cues.py` (commits / asks /
   suggestion / declines, with negation handling), and their output passes the **owner guard**: a
   named owner becomes **Unassigned** only when that person merely suggested or declined the task and
   never committed to it or was asked to do it (word overlap ≥ 0.25). It never assigns anyone.
   Replaying it over every note from the eval changed exactly the invented-owner lines.
4. **Deadlines** are written as said; post-processing appends the date for "today", "tomorrow",
   weekdays, "next <weekday>" and "<weekday> next week", relative to the meeting date.
5. **Post-processing** strips reasoning blocks, wrapping code fences, preambles, a leading heading
   and marker-like lines, demotes `#`/`##` to `###`, normalises checkboxes; an empty answer is asked
   once more, then shown as `_Nothing to report._` with a warning.
6. Reasoning models run with `think: false` (Ollama) unless `generation.think` is true.
**Status.** Accepted (2026-10-11, Phase 09).
**Consequences.** Templates stay plain prompts; the deterministic aids apply to every template with a
`format: tasks` section. The cue regexes are English; other languages get the prompts without the
aids' benefit (Phase 15 follow-up). Eval scores are recorded in the Phase 09 log.

## ADR-0018: Generation and write stages: consent pause, idempotent writes, fake pipeline
**Context.** The `generate` and `write` stages join the Phase 04 job pipeline. They must honour S6
(cloud consent) without losing work, survive crashes without duplicate files, and let Phase 10 click
through the whole flow with `MM3_FAKE_PIPELINE=1`.
**Decision.**
1. *Consent (S6):* a cloud backend without consent (job option `cloud_consent`, or the backend's
   `consent_remembered`) pauses the job with `InputRequired("cloud_consent", {backend,
   backend_kind, badge, message})` instead of failing. `{"consent": true}` continues and is recorded
   as `cloud_consent_for: <backend>` in the job options (a later backend change asks again);
   `{"consent": false}` fails the job with `E_CONSENT_REQUIRED`, and nothing was sent.
   `NoteGenerator` also calls `llm.consent.enforce_consent` before its first call, so no other
   caller can skip the check.
2. *GPU:* the runner asks a stage `gpu_for(job options)` when it has one; `generate` holds the GPU
   semaphore only when the job's backend is a local Ollama (R5).
3. *Checkpoints:* finished sections are kept in `generate.partial.json` keyed by a hash of template,
   backend, model, instructions and transcript, so a failed or interrupted generation resumes at the
   first missing section. `write` records its chosen stem in `write.intent.json` and skips a file that
   already carries the note's `mm3-id`, so a crash between the two files never produces `(2)` copies.
   The companion transcript is written before the note, so the note's link is never dangling.
4. `resume(job, overrides, from_stage=...)` re-runs a completed stage (e.g. `generate` with another
   template); `POST /api/jobs/{id}/generate` uses it.
5. *Fake pipeline:* `generate` is the real stage with the offline `FakeLLMBackend` (local or cloud like
   the configured backend, so consent can be exercised), and `write` is the real stage whenever a vault
   is configured.
**Status.** Accepted (2026-10-11, Phase 09).
**Consequences.** Spec amendment R22. The UI (Phase 10) handles a third input kind, `cloud_consent`.

## ADR-0019: Server-rendered UI with HTMX partials, SSE as a trigger, Alpine CSP build
**Context.** Phase 10 needs a live progress view, forms with a CSRF token, a strict CSP (S2, S3) and no
build step (ADR-0002). Alpine's standard build evaluates expressions with `eval`, which a strict CSP forbids.
**Decision.**
1. Pages and partials are rendered by Jinja on the server; HTMX swaps partials. The job page does not
   interpret SSE payloads: any `snapshot`/`stage`/`job` event (throttled to 4 per second) re-fetches
   `/ui/jobs/{id}/panel`, plus a 5 s refresh while a job is running. State therefore always comes from
   `JobRunner.describe`, and reloads and reconnects need no replay logic. A job waiting for input is not polled,
   so buttons keep keyboard focus.
2. UI actions are form-encoded `/ui/...` routes that call the runner and return the refreshed panel (or an
   `HX-Redirect`); the JSON `/api/...` surface is unchanged. Errors become toasts.
3. Alpine is the CSP build with method-only bindings; HTMX runs with `allowEval=false`. All script is in
   `static/app.js`; styles are in `app.css` (progress uses `<progress>`, never inline style).
4. Notes are previewed with `markdown-it-py` (MIT, already a transitive dependency) with raw HTML disabled
   rather than adding a separate sanitiser; the CSP is the second layer. Phase 11 reuses `web/render.py`.
5. Setup writes `vault.path` and `vault.output_subfolder` into the live settings object and `config.yaml`.
**Alternatives.** Client-side rendering of SSE payloads with Alpine `x-for` (more script, fragile under the CSP
build, needs replay on reconnect); a JS framework with a build step (rejected by ADR-0002); `nh3` as a
sanitiser (an extra native dependency for no gain while HTML is escaped).
**Status.** Accepted (2026-10-11, Phase 10).
**Consequences.** Firefox is expected to work (standard APIs only) but only Chromium was exercised here.

## ADR-0020: Settings screen: declarative fields, all-or-nothing validation, write-only secrets
**Context.** Phase 12 puts every setting in the UI and must round-trip to `config.yaml` (Phase 02 uses PyYAML, which
does not keep comments), keep secrets out of every response, and respect the strict CSP (no inline script or style, header-only CSRF).
**Decision.**
1. The editable settings are described once, as data (`web/settings_fields.py`: path, label, kind, choices, hint). One Jinja macro renders them and one
   function parses a submitted form into a patch, so a new setting is one line. The LLM backends, voiceprints, model downloads and diagnostics are
   custom panels.
2. A patch is validated per section with the pydantic models (`config/editing.py`) and applied only if every value is valid; the response re-renders the
   tab with inline errors and what the user typed. Validation does not go through `Settings(...)`, so environment overrides are not copied into the
   file by the validation step. Saving dumps the live settings, so an environment-supplied value is written too; the screen flags such fields.
3. Secrets are write-only: no value is ever rendered; empty means unchanged; a checkbox clears. Backend API keys follow the same rule.
4. Each tab is a form posted with HTMX (`hx-post`, so the CSRF header is sent) and answered with the tab fragment. Tabs are separate URLs (`/settings/<tab>`), so
   the screen works with a reload and without script. Long-running work (model downloads) runs in a daemon thread and is polled every two seconds.
5. UI saves normalise `config.yaml` (comments and key order are lost). Adopting `ruamel.yaml` to preserve them was weighed and not done: it is a new
   dependency for a file the UI now owns, and the file stays human-readable.
6. A single-use confirmation token (the Phase 07 token store) guards "delete all voiceprints" in the UI as in the API.
**Alternatives.** Hand-written forms per tab (more markup, easy to forget validation on a field); client-side validation and JSON PATCH (needs script and
duplicates the pydantic rules); ruamel.yaml round-tripping (extra dependency).
**Status.** Accepted (2026-10-11, Phase 12).
**Consequences.** `jobs.max_concurrent` and `jobs.prune_interval_hours` are read at start-up and still need a restart (the field says so). The settings
object is mutated in place, so the runner and registry see changes at once; `BackendRegistry.invalidate()` is called after each save.

## ADR-0021: Feedback ratings and data export
**Context.** Spec §3 step 9 wants ratings for a future improvement loop, and the design notes want the user to own their data. Both must stay local.
**Decision.**
1. Table `feedback` (migration 3): meeting id, template, backend, model, optional section id, kind (`thumbs` -1/1 or `stars` 1-5), value, comment (at most
   2000 characters), timestamp. A new rating of the same kind for the same note or section replaces the old one, so the table holds the current opinion; the
   history is not kept (nothing consumes it yet, and replacing avoids double counting).
2. The note is rated with stars and a section with thumbs, through one reusable widget (`partials/feedback.html` plus `feedback_context`) that the review
   workspace embeds per section. Export is `GET /api/feedback/export` as JSON or CSV; CSV neutralises leading `=`, `+`, `-`, `@`.
3. Meeting export builds note, transcript, plain-text transcript or a zip in memory from vault files (confined) and, for a job, the retained audio.
   "Export all app data" is a zip of the settings (masked), the tables `jobs`, `job_stages`, `recent_meetings` and `feedback` as JSON and each job's small
   artifacts. It excludes secrets, audio and voiceprints (biometric data is managed in the app, not exported by default).
**Alternatives.** Keep every rating event (more storage, needs an aggregation rule); include voiceprints in the export (a portable biometric file is a new risk).
**Status.** Accepted (2026-10-11, Phase 12).
**Consequences.** Anyone adding a table that holds user data must decide whether it joins `exporting.EXPORT_TABLES`; the voiceprint tables are absent by design.

## ADR-0022: Optional copy of the retained audio into the vault (R8)
**Context.** R8 promised an opt-in setting that copies the Opus audio into the vault so Obsidian can link it; Phases 04 to 11 did not build it, and Phase 12 adds
the setting to the UI.
**Decision.** `privacy.copy_audio_to_vault` (default off) and `vault.attachments_subfolder` (default `Meetings/attachments/`). After a job reaches `written`
and its audio is compressed, `jobs/vault_audio.copy_audio_to_vault` copies `audio.opus` to `<attachments>/<note stem>.opus` (temp file and rename, confined to the
vault) and sets the note's `mm3-audio` property through the note round-trip (`parse_note` / `render_note` with the parsed base, so the rest of the file is untouched).
A failure is logged and never fails the job. The copy is not removed by retention (it is the user's file); the UI warns about vault size and sync.
**Status.** Accepted (2026-10-11, Phase 12).

## ADR-0023: Stage-2 template library: shared section ids, one exception to AI Recommendations, type-aware eval
**Context.** Phase 13 adds the 17 remaining templates (spec A3). They have to stay consistent so
regeneration, ratings and the library UI treat them alike, and several handle sensitive material
(hiring, coaching, formal minutes).
**Decision.**
1. Templates reuse the common section ids and share the task-section structure, owner rule and "nothing
   here" sentences taught in Phase 09; type-specific ids are added where a section has no common
   equivalent. Prompts are written once per template; there is no inheritance or include mechanism
   (templates stay plain, editable Markdown files, ADR-0016/0017).
2. Exactly one built-in, `board-governance-minutes`, sets `params.ai_recommendations: false`: a legal
   record must not carry generated commentary. The exception is listed in the test that enforces the
   rule, so a new exception has to be added on purpose.
3. Guardrails for sensitive templates live in their `_system` blocks and are asserted by tests (the
   phrases that carry them), and checked on live output by the eval: `expected.forbidden` fails an
   interview note that mentions family status; `expected.sections` fails board minutes that guess a
   vote count.
4. The eval gains type-specific meetings (`templates:` in the YAML): a meeting only runs against the
   templates it is meant for, so adding templates does not multiply the run time. Meetings without the
   key still run against every template.
5. The template catalogue is generated from the files by a script and checked in CI, so it cannot drift.
**Consequences.** Small local models were checked on the five type-specific meetings and on the
other twelve templates with the general launch meeting (see the Phase 13 log). A prompt fix found by
the eval (copy the chair's own words for a vote result) is in the board template. Per-template quality
on real meetings is still Nick's judgement; templates can be edited in the vault without a release.

## ADR-0024: Review editor: textareas per note part instead of CodeMirror 6
**Context.** Phase 11 needs a Markdown editor for the whole note in which the section-marker lines are
de-emphasised and protected (R11), under the strict CSP of ADR-0019 (`script-src 'self'`,
`style-src 'self'`, no `eval`) and without a build step (ADR-0002). The phase prompt suggested vendoring a
prebuilt CodeMirror 6 bundle or a lighter alternative justified here.
**Options.**
| Option | Pros | Cons |
|---|---|---|
| CodeMirror 6, prebuilt bundle with Markdown mode | Syntax highlighting, one editor for the whole file, mature undo/search | No official single-file build: we would build and vendor ~400 KB with esbuild (a build step to maintain); injects styles at run time (CSP `style-src` needs constructable stylesheets or a nonce); markers are still ordinary text, so protection is a warning after the fact |
| One `<textarea>` with the whole file | Tiny, no dependency | Markers can be deleted with one keystroke; only a warning is possible |
| **Textareas per part** (chosen) | No dependency or build; CSP untouched; marker lines are not editable at all; per-section Regenerate controls and feedback slots sit next to their section; the server joins parts back byte-for-byte | No syntax highlighting; a section cannot be split or merged in the editor (do that in Obsidian) |
**Decision.** The note is split on the server (`markdown/editing.py`) into its frontmatter, the user text
before, between and after sections, and each valid section's content between its markers. Each part is a
`<textarea>`; the marker lines are shown as dimmed, non-editable labels. The browser sends the parts back
and the server re-inserts the original marker lines. A part that comes back unchanged (apart from the
browser's LF line endings) is restored byte-for-byte; a changed part takes the document's line ending.
A marker typed into a section is refused; a marker-like line added to or removed from user text (for
example while repairing a damaged section) needs an explicit "Save anyway". A rendered preview (server-side
`web/render.py`) replaces the editor on demand. Damaged sections are plain user text to the editor.
**Status.** Accepted (2026-10-11, Phase 11).
**Consequences.** No new third-party code. Highlighting can be added later without changing the save model.

## ADR-0025: Review workspace save model: base snapshots, conflict check, accept-then-save
**Context.** Edits made in the browser must reach the vault atomically, never overwrite changes made
elsewhere (Obsidian, sync, another tab) without asking, survive a closed tab, and keep text outside the
markers byte-identical through regeneration and template switches (R11, R12).
**Decision.**
1. Opening a note stores the exact text as a *base* in app data (`<data>/reviews/<mm3-id>/base-<sha256>.md`,
   newest 5 kept, folder `0700`). Every action names its base by SHA-256. A save joins the editor's parts
   against that base, checks that the result is still an MM3 note with the same `mm3-id`, and writes
   atomically only if the file on disk still has the base's hash. Otherwise it returns a conflict with a
   side-by-side and unified diff (vault version vs. yours) and the user chooses: keep mine (overwrite the
   exact version shown), take theirs (reload), or keep editing to merge by hand. A hash, not the mtime,
   decides, so touching a file without changing it is not a conflict.
2. Unsaved parts are autosaved (debounced) to `draft.json` in the same folder. Reopening offers to restore
   them when the note's sections still match; the draft is removed on save.
3. Regeneration is a preview computed from the editor's current copy of the section (unsaved edits
   included). Accept replaces the section's text in the editor; "Accept & archive previous" first writes
   the editor's previous version to the R12 section archive. The user then saves as usual. Appending a
   fresh copy of a damaged section, switching template and renaming speakers write the vault directly and
   therefore require a clean editor and an unchanged file.
4. A template switch generates the whole note in a preview (stored as `pending-<token>.md`), then archives
   the current note whole and writes the new one. Text outside the old sections is appended under
   "## Preserved notes" (an earlier such heading is not nested); user properties and links are kept.
5. Renaming speakers applies the Phase 07 cascade: companion transcript (headings and `mm3-speakers`), note
   `mm3-speakers` and `participants`, names inside MM3 sections (whole words, simultaneous), the
   Participants header line only if it is still exactly what MM3 wrote, and the job's speaker map if the
   job still exists. Voiceprints are not enrolled (the per-meeting embeddings no longer exist).
6. Migration 3 adds `recent_meetings.job_id`, so a re-opened note finds its job's audio; older notes fall
   back to scanning the jobs' `written.json`.
**Alternatives.** Applying accepted regenerations to the vault immediately (simpler, but a second save path
that competes with unsaved edits); comparing mtimes only (false conflicts from sync tools that touch files).
**Status.** Accepted (2026-10-11, Phase 11).
**Consequences.** Drafts and bases hold meeting text in the app data folder (documented in PRIVACY). An
archive written by "Accept & archive previous" exists even if the user never saves the new version.

## ADR-0026: Docker images: python:3.12-slim + torch's own CUDA wheels; host-network override for Ollama
**Context.** Phase 14 (R15, R16). The GPU image needs CUDA 12.8 and cuDNN 9 for torch 2.8.0 and CTranslate2.
**Decision.**
1. One multi-stage `docker/Dockerfile`, targets `runtime-gpu` and `runtime-cpu`, builder stages that `uv sync
   --frozen --no-dev --extra ml --extra bedrock` into `/opt/venv` (uv pinned by digest). The CPU target then
   reinstalls torch/torchaudio/torchvision from the PyTorch CPU index (same versions as `uv.lock`) and removes
   the `nvidia-*` wheels and triton.
2. **Base image (measured, uncompressed):** `nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04` alone is 2.86 GB,
   `python:3.12-slim` about 0.13 GB. torch's wheels depend on `nvidia-*-cu12` (4.2 GB in the venv), so the
   CUDA base would only duplicate libraries (about 16 GB total). We use `python:3.12-slim-bookworm`; the host
   needs only a driver supporting CUDA 12.8 (ADR-0014). Verified: CTranslate2 and torch both see the GPU.
3. **Measured sizes:** GPU image 13.3 GB on disk (4.57 GB compressed; venv 8.07 GB: nvidia wheels 4.2 GB,
   torch 1.7 GB, triton 0.5 GB), CPU image 3.51 GB (0.82 GB compressed; venv 2.07 GB, ffmpeg layer 0.47 GB).
   No model weights are present (`find` for *.safetensors/*.ckpt/.env in CI; models live in the `/models` volume).
4. The container runs as uid/gid 1000 (build args), read-only root, `tmpfs` /tmp, `cap_drop: ALL`,
   `no-new-privileges`, tini as PID 1, `HEALTHCHECK` on `/healthz`.
5. The app binds `0.0.0.0` inside the container and compose publishes `127.0.0.1:8765` only (S1).
6. **Host Ollama (R16), Nick's choice:** `docker/compose.host-network.yaml` runs the app with
   `network_mode: host` (binding 127.0.0.1, Ollama at 127.0.0.1:11434). No host service was changed. The default
   `compose.yaml` keeps the bridge network with `host.docker.internal` for people who expose Ollama.
   The Ollama backend is configured by `MM3_LLM__BACKENDS__OLLAMA__*` environment variables.
**Alternatives.** NVIDIA CUDA base (larger, no benefit); `OLLAMA_HOST=0.0.0.0` drop-in (exposes Ollama to the LAN);
bundled Ollama profile (shares 8 GB VRAM, re-downloads models; offered as an option).
**Status.** Accepted (2026-10-11, Phase 14).
**Consequences.** The GPU image is large because of torch; a slimmer image would need a different ML stack.
With host networking Docker does not isolate the port. The CI GPU image is built but never run.

## ADR-0027: Docker base image moves to Debian 13 (trixie); no curl or system pip at run time
**Context.** The Phase 15 trivy scan of the Phase 14 images (`python:3.12-slim-bookworm`) found 8 critical,
253 high and 492 medium OS-package findings, none with a fixed Debian 12 package, plus `pip` 25.0.1 (5 medium) in
the base image's system Python. ffmpeg, which parses every untrusted upload, had 47 open CVEs (16 high). `curl`
was installed only for the `HEALTHCHECK`.
**Options considered.**

| Option | Pros | Cons |
|---|---|---|
| Keep bookworm, accept the findings | No change; Phase 14's measurements stay valid | Older ffmpeg (5.1) with more open CVEs; 8 critical findings |
| `python:3.12-slim-trixie` (Debian 13) | Current stable; ffmpeg 7.1 (36 open CVEs, 16 high); 1 critical / ~215 high / ~297 medium; same size (3.48 vs 3.51 GB CPU) | Re-verify the GPU image; Debian 13 point releases still bring fixes over time |
| Distroless or Alpine | Fewer packages | No ffmpeg/glibc wheels story (CTranslate2, torch need glibc); large rebuild |

**Decision.** Base the images on `python:3.12-slim-trixie` (`ARG PYTHON_IMAGE`, so a user can still build on
bookworm). Remove `curl` (the healthcheck is a one-line Python `urllib` call) and uninstall the base image's
system `pip` (the app runs from `/opt/venv`, which has no pip). Re-verified: both images build, the CPU image
serves `/healthz`, and the GPU image transcribes and diarizes the AMI fixture on the RTX 2070 (Phase Log).
**Status.** Accepted (2026-10-12, Phase 15). Supersedes the base-image choice in ADR-0026 item 2 (the CUDA-wheel
reasoning there still holds).
**Consequences.** The remaining OS findings have no fixed packages; rebuild the images regularly to pick up
Debian security updates. If images are published (Phase 16), GPL source obligations apply to the Debian packages
(THIRD_PARTY_NOTICES "Docker images").

## ADR-0028: Phase 15 security hardening choices
**Context.** The Phase 15 review found a consent bypass, biometric data in exports, a YAML denial of service,
unmasked proxy credentials and a silent vault overwrite (SECURITY.md "Phase 15"). Several fixes needed a design
choice.
**Decisions.**
1. **Consent answers are single-use.** The generate stage deletes its input file on every run before deciding,
   and `JobRunner.resume(from_stage=...)` deletes the answers of every stage it resets. Alternative: bind each
   answer to a backend name; rejected as more state for the same guarantee.
2. **Vault YAML: cap alias expansion instead of banning aliases.** Phase 03 deliberately supports a simple alias
   across keys; a node-count cap (10 000 after expansion, memoised so it is linear) blocks "billion laughs"
   while keeping that. Values PyYAML cannot construct become ordinary frontmatter errors.
3. **Header values are secret by default.** Every `llm.backends.*.headers` value is masked and redacted except
   known attribution headers (`HTTP-Referer`, `Referer`, `X-Title`, `User-Agent`); passwords in `base_url` are
   masked too. Alternative: a list of sensitive header names; rejected because proxies use arbitrary names.
4. **ffmpeg defence in depth in the app, not only in ffmpeg.** `-protocol_whitelist file` and a refusal of
   playlist/list demuxers (`hls`, `concat`, `image2`, `tee`, ...), even though current ffmpeg versions already
   refuse the known tricks with our server-chosen file names. Resource limits (rlimits) were not added: setting
   them needs `preexec_fn`, which is unsafe in the threaded job runner; timeouts and the container's limits apply.
5. **Per-meeting voice embeddings are treated like audio.** Excluded from exports, deleted by retention pruning
   and by "delete all voiceprints" (`VoiceprintStore.wipe(jobs_root)`).
6. **Accessibility and e2e in CI.** axe-core 4.10.2 is vendored under `tests/e2e/vendor/` (test-only, MPL-2.0)
   rather than fetched at test time, so CI and offline runs are reproducible; a CI job runs the Playwright suite
   with the fake pipeline. `MM3_FAKE_OOM=1` simulates a GPU out-of-memory error for the e2e test.
**Status.** Accepted (2026-10-12, Phase 15).
**Consequences.** Re-run `scripts/pip_audit_ml.sh` and the GPU socket audit after any ML dependency change; the
`ml` advisories stay accepted until WhisperX lifts its pins (ADR-0014).

## ADR-0029: Check that a model can write notes before any work, and recover in place
**Context.** In Nick's first real run, no default Ollama model was set, so the new-meeting page filled in the
first installed model: `nomic-embed-text`, an embedding model with a 2,048-token window. The job transcribed for
15 minutes and then failed at *Generating notes* with `E_LLM_CONTEXT`. The hint ("raise
`generation.max_context`") could not help, and the UI had no way to change the model of a failed job.
**Options considered.**

| Option | Pros | Cons |
|---|---|---|
| Better error text only | Smallest change | Still fails late; the user still cannot change the model from the UI |
| Validate before work, and offer recovery on failure (chosen) | The common mistake never starts; any late failure is fixed in two clicks without re-transcribing | More code; needs the backend to report model capabilities |
| Hide every model without a known window | Simple | Hides usable cloud/OpenAI-compatible models whose window is unknown |

**Decision.** For Ollama, read `capabilities` and `*.context_length` from `/api/show` (`ModelInfo.can_generate`).
A model is *usable* unless it is known to be embedding-only, or its window is known and too small after the
`generation.max_context` cap (`window_is_workable`, the same budget the map-reduce step uses). Unknown means
usable, and only local backends are probed, so nothing leaves the machine before consent. Usability is enforced
in four places: the picker (filters, plus a suggested model, preferring the measured `qwen3:8b`), the submission
(`/api/jobs` and `mm3 process` refuse with `E_LLM_MODEL_UNSUITABLE` or `E_LLM_CONTEXT`), the generator itself, and
the failed-job panel. For any failure in the generate stage, that panel offers **Try another model**
(`POST /ui/jobs/{id}/retry-model`), which resumes from the generate stage with `backend`/`model` overrides and can
save the choice as the backend's `default_model`. Context errors now say whether the model or the setting is the
limit.
**Status.** Accepted (2026-10-12, pre-release fix outside the phase table).
**Consequences.** Opening the model list costs one `/api/show` call per installed model (cached per backend).
Older Ollama versions report no capabilities; their embedding models then fail at generation, with the same
recovery panel.

## ADR-0030: Interim tuning rounds between hardening and release are numbered 15a, 15b, 15c…
**Context.** After Phase 15, Nick processed real meetings and asked for an iterative series of tweaks before
GitHub publication (Phase 16), run through the same `/phase` model: prompt, plan row, claim, worktree, close-out.
The phase table had integer IDs only, and `/phase`, the claim protocol and branch names assumed `NN`.
**Options considered.**

| Option | Pros | Cons |
|---|---|---|
| `15.001`, `15.002`… | Room for many rounds | Noisy to type (`/phase 15.001`); dots in branch and worktree names; reads like a version |
| `15.1`, `15.2`… | Familiar | Ambiguous as numbers (`15.10` = `15.1`), so a tenth round sorts wrongly; reads like a version |
| `15a`, `15b`, `15c`… (chosen) | Short (`/phase 15a`); sorts correctly as text and by rule; clean branch and worktree names; clearly "between 15 and 16" | 26 rounds at most (ample) |
| Renumber 16 and insert new integer phases | No new ID shape | Rewrites history and every reference to Phase 16 |

**Decision.** A phase ID is two digits plus an optional lower-case letter. An interim round is a normal
phase: its row sits between 15 and 16, its prompt is `prompts/phase-15x-pre-op-tuning-N.md`, its branch
`phase-15x-pre-op-tuning`, and its worktree `../MeetingMaster3-phase-15x`. Each round depends on the
previous one, and Phase 16 depends on the last round. `/phase` and `prompts/_shared-instructions.md`
document the ID shape and the ordering (`15` < `15a` < `15b` < `16`).
**Status.** Accepted (2026-10-12).
**Consequences.** Adding a round means adding a row and a prompt, and moving Phase 16's "Depends on" to the
new round. The `phased-project` skill and the method note describe the same convention for other projects.

## ADR-0031: Readable transcript, dates without a year, two summaries and the note upgrade path (Phase 15a)
**Context.** Nick's first real meetings (round 15a): the companion transcript reads poorly in Obsidian
(the data block is most of the file and turns run for minutes), a file named `09-22 Interview_ ….mp3` left the
date at today, the one summary was too short, and the meetings already processed should gain the change.

**Decisions.**
1. **Readable transcript.** A second, generated file `<note stem> (Transcript).md` sits next to the note
   (`markdown/readable_transcript.py`, `vault/readable.py`). Per turn: a muted `m:ss` (or `h:mm:ss`) clock
   and the name in `<mark style="background: rgba(…,.35); font-weight: 600">` on one line, the text below,
   a blank line between turns. HTML highlights are used because Obsidian's `==…==` has one colour; the
   translucent dark-theme palette of the review screen (`.spk-0`…`.spk-7`, natural label order, the same
   index as the review pane) keeps the theme's text colour readable in light and dark themes. Unnamed
   speakers and undiarized text get a neutral grey. Turns are split into paragraphs at segment boundaries
   once a paragraph passes **90 seconds**, without repeating the heading. Spoken text is neutralised: `& < > "`
   become entities and Markdown/Obsidian punctuation (`\ ` * _ [ ] # $ % = ~ ^ |`) and a leading list or
   quote marker are backslash-escaped, so no transcript can create HTML, links, embeds, tags, comments,
   math or section markers (S3). The companion's own body has no such escaping and is unchanged
   (out of scope). Frontmatter: `mm3-id`, `mm3-kind: readable-transcript`, `mm3-note`,
   `mm3-transcript` (wikilinks), `duration`, `language`, `speakers`. Scanners classify by
   `mm3-kind`, never by name (a note may legitimately be called "… (Transcript)"): the picker,
   locate-transcript, re-open by id, regenerate, export and link-transcript all ignore it. The name never
   ends with `.transcript.md`. A file of that name that is not this meeting's readable transcript is never
   replaced: `(Transcript 2)`, `(Transcript 3)`… are tried. The file is never parsed back. It is rewritten
   when the job writes the note, on a speaker rename and on link-transcript (reprocess writes a new note
   through the job), and an unchanged file is not touched. The note links it from a header line
   `- **Transcript:** [[… (Transcript)|Read the transcript]]` (the link people click); `mm3-transcript`
   in the frontmatter still points at the companion. A template switch keeps that line. Setting
   `generation.readable_transcript` (default on) instead of the prompt's `notes.readable_transcript`:
   it sits next to `generation.write_companion`, and the Settings tab that shows both is already "Notes".
2. **Dates from file names.** Order: year first (existing), US numeric with a year (`09-22-2026`,
   `9-22-26`), a month name (`Sep 22`, `Sept 22nd`, `September 22, 2026`, `22 Sep`), then month and day
   (`09-22`, `9-22`, `09_22`, `09.22`). Month first; day first only when the first number is above 12 and
   the second is not. Not dates: numbers glued to letters or digits (`v2-10`, `x09-22`), parts of longer
   dotted/dashed numbers (`1.2.3`), impossible dates (`02-30`, `14-30` as a time), and number pairs next to a
   count word (`Top 10-12`, `Part 1-2`, `5-10 min`, `3-4 people`). **Year inference:** the current year in
   the server's local time zone, except that a date more than one day in the future takes the previous
   year (a recording cannot come from the future; `12-30` seen on 2027-01-02 is 2026-12-30). One day of
   slack covers time-zone differences; 29 February in a non-leap year also falls back a year. The matched
   date is removed from the guessed title, and a free-standing `_` (a `:` or `|` replaced by the recorder or
   browser) becomes ` - `. The form shows "From the file name" under the Date until the user edits it.
3. **Two summaries.** In all 22 built-ins the `summary` section keeps its id (notes, regeneration and ratings
   keep working) and is titled **Summary Succinct**; **Summary Detailed** (`summary-detailed`, narrative,
   `max_tokens: 1000`) follows it, with a prompt in each template's voice: prose only, typically three
   paragraphs (context and purpose; threads of discussion with who said what; outcomes, decisions and open
   questions), never fewer than two. Board minutes place both after Attendance & Quorum (formal minutes
   open with attendance); Just the Facts and Key Takeaways gain both at the top. The generator counts
   paragraphs in `summary-detailed`; fewer than two triggers one retry with a firmer instruction, then the
   better answer is kept with a job warning, never padded. Map-reduce needed no change: its reduce input
   already carries per-part summaries, up to 10 attributed points per part and every decision, action and
   question. Unedited vault copies of built-ins are now upgraded at app start (only files the user never
   edited, by the install manifest hash; a deleted built-in is not brought back), and an edited copy whose
   built-in changed is flagged in the library ("Reset to default" gets the new version).
4. **Upgrade path for older notes** (`review/upgrade.py`, "Update older notes" on Recent, `mm3 notes upgrade`).
   A dry-run planner (no writes; it sees the upgraded built-ins through `planning_library`) lists per note:
   the summary sections its template has and the note lacks, renaming a heading that is still exactly
   "Summary", and a missing readable transcript. Notes without a companion are skipped with the reason.
   Applying generates the sections with one prepared context (`NoteGenerator.write_sections`, the same
   ADR-0029 model check and S6 consent: a cloud default must be agreed to), inserts them after their
   template neighbours (`markdown/sections.insert_section`, a pure insertion), archives the whole previous
   note, and re-checks `mm3-id` and SHA-256 just before an atomic write; a note edited meanwhile is
   skipped and reported. Running it twice changes nothing. Custom templates are never changed (the user
   guide explains how to add the sections).
**Status.** Accepted (2026-10-12).
**Consequences.** Two extra LLM calls per note (Summary Detailed, plus the rare retry); measured in
`docs/PERFORMANCE.md`. The vault gains one more file per meeting. The `.txt` export now uses the readable
layout (time and name, then text, blank line) instead of one `[h:mm:ss] Name: text` line per turn.

## ADR-0032: The logo is committed, all rights reserved, and hidden on meeting pages (Phase 15a, Q6)
**Context.** Nick asked for a logo made from `~/Pictures/wiz.jpg`, a photo-composite of him as a wizard with
a crystal ball at a boardroom table. It shows a real person, and the repository becomes public in Phase 16.
**Decision.** Nick chose (Q6, 2026-10-12): commit only the cropped logo, never the original, excluded from
Apache-2.0 with a `NOTICE` line ("© 2026 Nick Antonizick, all rights reserved"). That option was offered
on the condition that he holds the rights to the image. The crop (340×430 at 320,32) keeps the head, hat and crystal ball and no background face;
it is a 4:5 portrait rather than square because a square crop either cuts the hat and ball or takes in a
colleague's face. `scripts/make_logo.py SOURCE` (ImageMagick, no Python dependency) writes rounded-corner
WebP and PNG at 32×40 and 64×80 with all metadata stripped into `web/static/brand/`. `base.html` shows it in
a `brand_logo` block left of "MeetingMaster3", `alt=""` (the link has text), size fixed in CSS, 26×32 below
30rem; `job.html`, `speakers.html`, `review.html` and `preview.html` override the block to nothing, so the
image is not even requested there. The CSP is unchanged (served from `/static`). `favicon.svg` is kept.
**Status.** Accepted (2026-10-12).
**Consequences.** Forks and redistributions must replace the logo; Phase 16 screenshots show it. *(Licence superseded by ADR-0035: CC0 1.0, 2026-10-14.)*

## ADR-0033: A large logo picture above "New meeting" (after Phase 15a)
**Context.** After 15a closed, Nick found the 32×40 header logo too small to make out. He asked to keep it
as it is and to add a rectangular picture with slightly rounded corners from `wiz.jpg` above the "New
meeting" heading. Asked which crop (2026-10-13), he chose the whole scene, knowing it includes the people
at the table, which ADR-0032 had kept out of the small crop.
**Decision.** `scripts/make_logo.py` also writes `hero.webp`, `hero@2x.webp`, `hero.png` and `hero@2x.png`:
the whole image, uncropped, resized to 320×230 and 640×460, corners rounded (12 px), all metadata stripped.
`new.html` shows it in a `<picture>` above the `<h1>`, with descriptive alt text, 320 px wide and
`max-width: 100%` so it fits a phone, centred in the content column. Only the New meeting page requests it. It is covered by the same
all-rights-reserved notice (`NOTICE`, `THIRD_PARTY_NOTICES.md`). The full-resolution original is still
never committed.
**Status.** Accepted (2026-10-13).
**Consequences.** About 40 KB of WebP on the New meeting page (PNG only for browsers without WebP). Forks
must replace these files too.

## ADR-0034: Inserting phases anywhere with `/phase-add` (generalises ADR-0030)
**Context.** Nick wants a repeatable way to add work to a phased plan after planning: feedback rounds
like 15a/15b, and also work that belongs earlier in the order, in this project and in future ones.
ADR-0030 allowed letter suffixes only for tuning rounds between 15 and 16, and the steps lived only in the
heads of the agents that did it (row, prompt, rewired dependencies, log, vault note).
**Options considered.**

| Option | Pros | Cons |
|---|---|---|
| Written checklist only | Nothing new to maintain | Steps get skipped (prompt grounding, rewiring the release phase, vault note); differs per session |
| `/phase add …` sub-mode of `/phase` | One command to remember | `/phase` executes phases and always claims; mixing planning into it blurs the claim rules |
| Separate `/phase-add` command + change-request template (chosen) | Planning-only by construction (no claim, no code); same steps every time; works from a file or pasted text; ships with the `phased-project` skill for every project | One more command file per repo |

**Decision.** `.claude/commands/phase-add.md` (from the skill template `phase-add-command.md`) turns a change
request into a planned phase: grounding in the code, one batched round of owner questions (decisions become
ADRs), placement, model choice, the prompt, the plan row and Phase Log planning entry, rewired dependents, edits
to later prompts, the vault note, and one `docs(plan): add phase <ID> …` commit on `main`. It never claims and
never pushes. **IDs:** a phase inserted after phase P is P plus the next free letter (`09` → `09a`; `15a` → `15b`),
for any P, never decimals and never renumbering. The intake template is `prompts/_change-request-template.md`
(optional; free text works).
**Status.** Accepted (2026-10-14).
**Consequences.** `/phase`, `prompts/_shared-instructions.md`, the skill's templates and the method note use the
general wording. Phase 15b is the first phase planned this way.

## ADR-0035: The logo and hero picture are released under CC0 1.0 (supersedes the licence in ADR-0032 and ADR-0033)
**Context.** ADR-0032 committed the logo as "© Nick Antonizick, all rights reserved", so forks had to replace
it. On 2026-10-14 Nick said the image is one he generated, that he does not mind people keeping and using it,
and that forks should not be forced to replace it.
**Options considered.**

| Option | Pros | Cons |
|---|---|---|
| CC0 1.0 (chosen) | Matches "free use"; no attribution or notice duties; standard for media | Anyone may reuse it in any context |
| CC BY 4.0 | Free reuse, credit required | Attribution duty on every fork and screenshot |
| Apache-2.0 like the code | One licence for the repo | A software licence, awkward for an image; NOTICE duties |

**Decision.** CC0 1.0 Universal for `web/static/brand/logo*` and `hero*`. The notice states that CC0 covers
copyright only and grants no trademark rights and no right to use the likeness of any person shown (for
example to suggest endorsement). The original `wiz.jpg` is still never committed. Implemented in Phase 15b
(`NOTICE`, `THIRD_PARTY_NOTICES.md`, README licence section, Phase 16 prompt).
**Status.** Accepted (2026-10-14); implementation in Phase 15b.
**Consequences.** Forks may keep the logo. ADR-0032's crop and placement and ADR-0033's hero picture are unchanged.


## ADR-0036: Review opens in Preview; the countdown shares the pruner's rule (Phase 15b, R26)
**Context.** Nick wanted the review screen to open on a readable note, and a way to keep a recording forever
with a visible "days left" line. The pin existed in the API (ADR-0006) but no page offered it.
**Decisions.**
1. **Preview first, rendered on the server** in the page response (same renderer and sanitiser as `/render`),
   so there is no flash of textareas. The editor stays in the page, hidden. Preview/Edit is a two-button
   group with `aria-pressed`. Preview of unsaved edits still calls `/render`; it is skipped when nothing changed.
   Switch template and Rename speakers work on the saved note and reload, so they do not force Edit
   (regenerate, accepting a section and restoring a draft do). The last mode is remembered in `localStorage`
   (try/catch); first visit is Preview.
2. **One expiry rule.** `jobs.retention.effective_expiry(job, privacy)` is used by `prune` and by
   `audio_retention_status`; there is no second copy of the maths. Days left are whole days rounded up, minimum 1;
   "due" means `expiry <= now`, the pruner's own test. The status is in `GET /api/jobs/{id}` and in the pin/unpin
   responses (`audio.retention`).
3. **Keep forever = the pin**, no new flag. The page uses `POST /ui/review/{mm3_id}/keep` (CSRF, path-confined
   like the other workspace actions), which calls the same `JobRunner.set_pinned` as the API and returns the
   server-rendered line, so the wording lives in one place (`review/retention_view.py`). Allow deletion asks
   first in a `<dialog>` and says when the recording would then go.
4. **Retention set to "forever":** the line says so and still offers a button ("Keep this one even if the setting
   changes"), because a later settings change would otherwise delete it.
**Alternatives.** Calling `/api/jobs/{id}/pin` straight from the page and building the text in JS (two copies of
the wording, and the JS would need the retention settings). Replaying the editor-first layout with a Preview
toggle (what existed).
**Consequences.** No change to retention defaults or the pruner's behaviour. Per-meeting custom retention periods
and a "kept forever" marker on Recent are ideas, not done.

---

## ADR-0037: Tuning round 3 is split into three phases; rename updates backlinks; a neutral, topic-based template (planning, 15c/15d/15e)
**Context.** On 2026-10-14 Nick asked for one more round before publication: progress feedback during a template
switch, renaming and re-dating an imported meeting with every link kept working, a "Plaud Clone" template modelled
on three Plaud notes of his own meetings, audio download and size on the review page, a Preview/Edit label that
follows the mode, and "Recent" renamed to "Meetings" with "Browse the vault" moved there and pagination. He also
asked for GitHub setup instructions (written as a vault note, not a phase).
**Options considered and decisions.**

1. **Phasing.** One large 15c (about three sessions of work; risk of a long, skimped session) or two phases, versus
   **three phases (chosen)**: 15c UI polish (Sonnet 5.5), 15d rename (Opus 5.5: multi-file state, links, no data
   loss), 15e template (Opus 5.5: prompt engineering). 15e touches only the template library and runs in parallel;
   15d follows 15c because both change the review toolbar and the Meetings page. Phase 16 depends on all three.
2. **Links in other vault notes when a meeting is renamed.**

   | Option | Pros | Cons |
   |---|---|---|
   | Update them after a backup (chosen) | Same result as renaming in Obsidian; nothing left broken | MM3 writes to files it did not create (until now it never did) |
   | Only MM3's own files, list the rest | MM3 never edits user files | The user must fix every link by hand |
   | Checkbox each time | Explicit | One more decision per rename for little gain |

   Each changed note is copied to app data first (`rename-backups/`, with a manifest), only the link target is
   rewritten, writes are atomic and SHA-checked, and the operation is journaled so an interruption can be completed
   or rolled back. Phase 15d records the detailed design in its own ADR.
3. **Template name.** "Plaud" is another company's product name, and built-in templates become public in Phase 16.
   The built-in gets a **neutral name** (default "Topic Briefing", id `topic-briefing`), with the style described in
   plain words. Nick may keep a personal vault copy called "Plaud Clone", which is never committed. Rejected: "Plaud
   Clone" as the built-in name (implies affiliation), or keeping it private only (forks would not get it).
4. **Template shape.** The three samples use three layouts. **Topic-based for every meeting (chosen)**: succinct and
   detailed summaries, meeting context, numbered topics dense with specifics, Q&A only when the meeting is mostly
   questions and answers, conclusion, action items in MM3's owner format. Rejected: adapting to interviews (fixed
   sections would sit empty on other meetings) and two templates (twice the maintenance).

**Also decided as defaults (the phase may change them with a reason in its ADR):** "Open a note" leaves the nav and
`/open` redirects to Meetings; the Preview/Edit toggle is one button labelled by its action; pagination is 10 rows
per section (25 in Browse the vault).
**Status.** Accepted (2026-10-14); to be implemented in Phases 15c, 15d and 15e.
**Consequences.** The built-in library grows to 23 templates (spec A3 amended in 15e). MM3 gains its first write
path into notes it did not create (15d), which goes into the threat model.

## ADR-0038: Long review actions are polled background tasks; recording download; Meetings page and paging (Phase 15c, R27)
**Context.** A template switch was one blocking POST that could take minutes with a local model; the only feedback
was a disabled button. Nick also asked for the recording's size and a download on the review page, a Preview/Edit
control that says what it does, and "Recent" merged with "Open a note" into a paged "Meetings" page.
**Options considered and decisions.**

1. **Transport for progress.**

   | Option | Pros | Cons |
   |---|---|---|
   | Poll `GET …/task/{id}` once a second (chosen) | No stream lifecycle (reconnects, heartbeats, proxies); reattaching after a reload is the same call; trivial to test; one reader | A second of latency on the bar |
   | SSE like job progress | Push updates | A stream per note to manage, the job `ProgressBus` is built around job ids and stages; more moving parts for a figure that changes every few seconds |

   The elapsed clock ticks in the browser between polls, so the page never looks frozen.
2. **Task model.** `review/progress.py`: an in-memory `LongTask` per note (`TaskRegistry`), one running task per
   note (a second start gets `E_TASK_RUNNING`, 409), the last finished one kept for an hour so a reloaded page can
   still fetch its result. The task runs as an `asyncio.Task` so **Cancel** interrupts the model call at once; the
   result (diff, apply token) is rendered by the result route, not by the task. Nothing is persisted: a server
   restart ends the task and the page says it is gone. `POST …/switch/preview` and `POST …/regenerate` now start a
   task; the apply, token, archive and `E_NOTE_CHANGED` checks are unchanged.
3. **Time left.** Until 5 % of the work is done: the hardware profile's `notes_rtf` midpoint for the transcript's
   duration, local backends only (else "estimating…"). After that: elapsed / fraction, smoothed (new = 0.6 old +
   0.4 measured) at each progress report. Past the estimate: "taking longer than expected", never 0:00. The
   generator reports a fraction at the *start* of each section and of each map chunk, so on a long meeting the bar
   can stand still for a minute or two; the step line ("Reading part 1 of 2"), the moving stripes and the clock
   cover that.
4. **Download.** `?download=1&name=<note stem>` on the existing audio route: `Content-Disposition: attachment` with
   RFC 5987 encoding (Starlette's `filename=`), the name from `sanitize_title` plus the file's own suffix. `name` only
   shapes the suggested file name; the path still comes from the job, so no client value reaches the filesystem.
5. **Meetings.** `GET /open` redirects (303) to `/meetings` (keeping `?dir=`); `/open/note`, `/ui/open/browse` and
   all links keep working; the Open page's "Recent notes" is dropped (Notes in your vault shows the same rows).
   Paging is server-side with one query parameter per section, HTMX swaps just the section from
   `/ui/meetings/{jobs,notes}` (and `/ui/open/browse` for the picker), links work without JavaScript, focus returns
   to the section heading, and removing or deleting a row re-renders its section (so an emptied last page falls
   back to the previous one). 10 rows for Jobs and Notes in your vault, 25 for Browse the vault.
6. **Preview/Edit.** One toggle labelled with its action plus a status label, instead of two `aria-pressed`
   buttons, which said nothing about what a click would do.

**Consequences.** The regenerate response shape changed (`{task}` first, then the old payload from the result
route). The progress widget is a shared module (`static/js/progress.js`) for later long actions. Two things to
watch: a task is lost on restart, and the fraction is coarse on map-reduce meetings.

## ADR-0039: Default Notes, a topic-based template that is also the default; sticky template choice; high-detail map-reduce (Phase 15e, R29)
**Context.** ADR-0037 asked for a built-in template that writes notes like those a commercial AI recorder produced
from three of the owner's meetings, under a neutral name. During the phase the owner chose the name **Default
Notes** (`default-notes`) instead of "Topic Briefing", asked for it to be the default on a first run, and asked that
the template picked on New meeting be pre-selected next time.

**Sample analysis (anonymised; the samples and transcripts stay private and were only used locally).**

| Sample | Meeting | Layout | Words | Topic part | Other parts |
|---|---|---|---|---|---|
| A | 59-min introductory call, 2 people | info block; 9 numbered `### N.` topics, each 2-3 `- Label:` points with a 2-5 sentence paragraph; conclusion; next steps as checkboxes | ~1 290 | ~1 000 words (75-210 per topic) | conclusion ~110, next steps ~100 |
| B | 113-min follow-up interview, 2 people | one-paragraph overview; 5 `##` topics of 2-3 prose paragraphs; action items grouped by person | ~1 180 | ~1 000 words (~200 per topic) | overview ~60, actions 7 items |
| C | 31-min panel interview, 4 people | interview assessment (history, expectations, strengths and concerns said vs self-reported, Q&A, to-dos) | ~2 870 | — | Q&A ~1 300 words, 16 questions with 1-6 sentence answers |

What they keep: figures and quantities (host counts, data volumes, alert counts, team sizes), product, vendor and
team names, dates of organisational changes, timelines and targets, and who said what. What they drop: greetings,
small talk, the order of minor asides. Two of the samples also contain errors (one person's career history given to
another person, inconsistent dates), so "never invent, never move a detail between people" stays a hard rule rather
than chasing every sample detail. Topic density does **not** scale with length: about 1 000 topic words for both a
59-minute and a 113-minute meeting.

**Decisions.**
1. **Name and default.** "Default Notes" is neutral (no other product's name) and becomes
   `generation.default_template` for new installs, replacing Executive Summary. A value already saved in
   `config.yaml` is kept.
2. **Sticky choice on New meeting.**

   | Option | Pros | Cons |
   |---|---|---|
   | Save the started meeting's template as `generation.default_template` (chosen) | One source of truth: Settings shows the same choice; works across browsers | A server-side write on upload |
   | Remember it in the browser (`localStorage`) | No config write | Settings and the page disagree; lost with site data |
   | Separate `last_template` setting | Keeps the "default" separate | Two settings that mean almost the same thing |

   The page sends `remember_template: true` with the upload options; the API removes it before the options are
   stored and saves the template only if it is a valid template in the library. API and CLI clients that do not
   send it change nothing. A failure to save is logged and never fails the upload.
3. **Shape** (as ADR-0037): Summary Succinct (1-2 sentences, at most about 50 words, stricter than other templates),
   Summary Detailed (R25), Meeting Context, **Discussion by Topic**, Questions & Answers (only when much of the
   meeting was questions; otherwise a fixed sentence), Conclusion, Action Items (MM3's owner format, grouped by
   owner, replacing the samples' `@Speaker` groups) and AI Recommendations. The interview guardrails of
   `job-interview-notes` are in `_system` and in `test_sensitive_templates_keep_their_guardrails`.
4. **High-detail map-reduce (`params.detail: high`).** On the reference 8 GB machine (`generation.max_context`
   16 384) a meeting longer than about 40 minutes goes through map-reduce with this template, whose map step kept 10 points of at most
   20 words per part. That leaves the topic section about 20 short facts for an hour and makes the model fill gaps
   with generic sentences. Options: raise the context (does not fit 8 GB next to the model), a template-specific
   generator path, or a **generic template parameter (chosen)**. With `detail: high` each part keeps up to 30
   points of up to 40 words, with a `topic` label and their specifics, plus up to 10 answered questions as
   structured `exchanges` (who asked, question, who answered, answer), and the map call gets 3 500 output tokens
   instead of 1 500 (so the parts are smaller). The reduce step sees `- [mm:ss] (topic) Name: text` and a
   "Questions and answers" list; when the notes must be cut to fit, points go first, then exchanges. It falls back to standard notes when
   the window is too small. Other templates are unchanged (standard is the default and its prompt is identical).

5. **Follow-up task candidates (`params.task_candidates: relevant`).** MM3's task sections list transcript
   sentences that sound like commitments and say "every commitment in the list is a task and must appear once,
   however small" (ADR-0017). In an informal call most "I'll …" sentences are conversation ("I'll put it that
   way", "I'll take it from there"), and the model turned them into tasks; the template's own prompt could not
   outweigh the list (v6, v7), and negative examples in the prompt made it worse.

   | Option | Result on the 31-minute meeting (3 runs each) |
   |---|---|
   | Strict list (all templates today) | 3 to 10 tasks, mostly conversation, varying run to run |
   | List shown, wording made advisory | 5 to 9 tasks, still conversation |
   | No list at all | stable 3 tasks, but the role's duties became tasks and the real follow-up was lost |
   | **Only candidates naming follow-up work (chosen)** | stable: exactly the one real follow-up, 3 runs out of 3 |

   The filter alone then missed real tasks in the synthetic business meetings ("I'll finish the migration", "I'll
   tell the exec team", "we should measure…"): 3 of 4 eval notes failed `actions_captured`. **Final form:** with
   `relevant` the candidates are split (`cues.split_follow_up`): those naming follow-up work (a broad verb list:
   send, schedule, review, prepare, finish, run, tell, ask, measure, negotiate, follow up…) are listed as likely
   tasks, the others under "may be only conversation; include one only if it is clearly work to be done after the
   meeting", and the "must appear" rule is dropped. The map step shows only the first group. The owner guard
   still uses every candidate. Every other template keeps one list and the strict wording (their golden prompts are
   unchanged), so their eval task recall is unaffected. Result: all expected actions found in all 4 eval notes
   (19/19), and the real meetings keep their real follow-ups without the conversational ones.

**Prompt iterations** (owner's three meetings, `qwen3:8b`, 16 384-token window; "specifics" = the share of the
sample's numbers and proper nouns that also occur in the transcript and appear in the generated note; the GPU was
shared with another session's test server, so times are high):

| Version | Change | 59-min call (map-reduce): topics / words / specifics | 31-min panel (full): topics / words / specifics | 113-min follow-up (map-reduce) |
|---|---|---|---|---|
| v1 | first draft, standard map step | 6 / 296 / 45 % | 4 / 347 / 66 % | not run |
| v2 | `detail: high`; "dense paragraph" wording | 5 / 355 / 60 % | — | — |
| v3 | structural counts: 6-9 topics, 3 bullets, 4-5 sentences each; placeholder example of that length; "do not stop early"; no banter | 6 / 742 / 63 % | 6 / 839 / 71 % | 5 / 1 118 / 59 % |
| v4 | answers attributed to the person who answered (prompt rule, "Asked by" text points); hypothetical steps and described practices are not tasks | — | — | 6 / 853 / 62 %; attribution fixed, but the map step wrote no "Asked by" points and Q&A paired questions with unrelated answers |
| v5 | structured `exchanges` in the high-detail map step; Q&A uses them and never re-pairs; advice is not a task, Unassigned only for agreed work | 6 / 971 / 66 % | 6 / 857 / 70 % | 6 / 871 / 70 %; answers now match their questions, but Q&A listed each exchange under both people and the tasks picked up small talk ("I'll …" remarks) |
| v6 | Q&A: one group per asker, third person; personal plans and small talk are not tasks (prompt only) | 5 / 729 / 65 %; tasks still listed small talk | 5 / 763 / 70 % | not run |
| v7 | `task_candidates: relevant`, first form: advisory wording; Q&A grew past its limit | 5 / 913 / 60 %; tasks still small talk | 6 / 867 / 70 %; 12 conversational tasks | not run |
| v8 | candidates filtered to follow-up work (prompt and map step); "after the meeting" task test; Q&A at most 12 questions | 5 / 897 / 65 %; tasks: exactly the two real follow-ups | 6 / 914 / 70 %; tasks: the one real follow-up | 5 / 786 / 68 %; tasks: the three real ones and one small-talk leftover the map step extracted itself |

v9 (shipped) splits the candidates instead of filtering them (see 5) and adds a general privacy paragraph to
`_system`; it changes only the task and privacy rules, so the v8 topic numbers stand. Its action items on the
owner's meetings: 31 min, the one real follow-up (2 runs out of 2); 59 min, only real follow-ups (one restated
twice); 113 min, the three real follow-ups plus four steps from the candidate's answers to hypothetical interview
questions and one small-talk remark. Task extraction from informal, interview-style conversations stays the
weakest part with an 8B model and varies from run to run; the owner can edit or regenerate the section.

**Known limitation (owner's decision, 2026-10-14: document it).** On the synthetic introductory call, where the
candidate volunteers a family reason for asking about flexible hours, qwen3:8b keeps that remark in Discussion by
Topic despite the privacy rules; five more prompt variants (rule last in the section prompt, "business reasons"
only, privacy-first in `_system`) did not remove it and cost other specifics, so they were reverted. A deterministic
sentence filter was rejected (it would delete legitimate sentences, e.g. about a children's product). The eval
records this note as failing `nothing_forbidden` (and, in that run, `type_content`: 8 of 10 specifics), and the
user guide recommends **Job Interview Notes** for hiring interviews. Final eval for Default Notes: 3/4 notes pass
every check; actions 19/19; Summary Detailed 2-4 paragraphs in all four.

Final (v8), for comparison with the samples: about 800-900 topic words in 5-6 topics where the samples have
about 1 000 in 5-9; 65-70 % of the samples' specifics that were said in the meeting appear; Summary Succinct 26-41
words; every action item has an owner. Spot checks against the transcripts found no invented facts in the topics;
the remaining errors are of the kind the samples also make (one figure attached to the wrong group in a Q&A answer,
an ambiguous word read in its everyday sense). **The owner read the 59-minute call's note beside its sample and
judged it "Plaud-like"** (2026-10-14, v6; v7-v8 changed only the action items and the Q&A length). Times: see
`docs/PERFORMANCE.md` (about 2.5-3 times Executive Summary).

Lessons: word targets alone do not lengthen an 8B model's answer; counts of topics, bullets and sentences, with a
placeholder example of the same length, do. Map-reduce detail was the main limit on long meetings. Interviews need
an explicit rule that an answer belongs to the person who gave it, or the summary credits the interviewer; a JSON
field is followed where a free-text convention ("Asked by …") is ignored.
**Status.** Accepted (2026-10-14).
**Consequences.** 23 built-ins (spec A3, R29). Default Notes is the slowest built-in (more and longer sections;
see `docs/PERFORMANCE.md`). Template schema version stays 1 (`detail` is an optional parameter; an older app would
reject a template that sets it).

## ADR-0040: Renaming and re-dating a meeting: plan, journal, backlinks, folder rule, backups (Phase 15d, R28)
**Context.** A meeting's title and date are in its note's properties, H1 and header, in the companion and readable
transcripts, in the names and link properties of every MM3 file (note, companion, readable, archives, vault audio
copy), in links from the user's other notes, and in the database. ADR-0037 decided that a rename also updates the
other notes' links after backing them up. Renaming touches up to a dozen files and a database, so it must not leave
a half-renamed meeting.

**Decision.**
1. **Plan, then apply.** `review/retitle.py:plan_retitle` reads the vault and returns every file change (old and new
   name, SHA of what it read, the new text, a list of visible changes), every linking note, the warnings and the
   reasons it cannot be applied. It writes nothing. The UI and the CLI show it; the apply re-plans and compares a
   digest of all inputs and outputs with the one previewed, then re-checks each file's SHA. Edits are line-level on
   the raw text with the raw-chunk frontmatter renderer (ADR-0011), so unchanged bytes (unknown keys, comments, CRLF,
   BOM) survive. The readable transcript is regenerated (it is a generated file, R25).
2. **Journal with one commit point.** Before the first write, `<data>/rename-backups/<stamp>-<mm3-id>/` gets
   `journal.json` (the files with old/new names and SHAs, the DB rows before and after), `manifest.json` and a copy of
   every changed text file (`files/<vault path>`) and of the new texts (`new/`, removed at the end). Order: write every
   new name (atomic, never over an existing file) → re-point the database and `written.json` in one transaction (the
   commit point, recorded as `phase: committed`) → remove the old names (only if their SHA is still the one read).
   Recovery is simple and idempotent: before the commit point, roll back (remove new files whose SHA is ours, restore
   from `files/`, put the DB rows back); after it, finish (DB again, remove old names). An `Exception` during the apply
   rolls back at once; a crash is handled at the next start (`create_app` lifespan, and before every CLI rename). A
   second recovery is a no-op. The vault audio copy (large, binary) is hard-linked (copied where links are not
   supported) rather than backed up.
3. **Backlink matching follows Obsidian** (`vault/links.py`). Bare names resolve by file name across the vault,
   case-insensitively; when several files share a name the linking note's own folder wins, otherwise the link is
   ambiguous and is left alone with a warning. Path-qualified links resolve by vault path, then relative to the
   linking note, then by a unique path suffix. Markdown links resolve relative to the linking note, then to the vault
   root, and keep their style (`%20` encoding, `<…>`, relative vs absolute, with or without `.md`). Only the target
   text is replaced; alias, heading, block, embed mark and table `\|` escapes are kept. A rewritten link is
   path-qualified when its new name is not unique in the vault. Links inside fenced or inline code are ignored, MM3
   archives and hidden folders are skipped, and the scan is bounded (20 000 notes, 2 MB per note) and runs in a worker
   thread. Archive bodies are not rewritten: they are historical copies (their link properties are).
4. **Folder rule.** The files move to the new date's output folder only if the note is in the old date's output
   folder (`vault.output_subfolder` expanded for the old date) and the two differ. A note the user moved stays.
5. **Backups go to app data, not the vault**, so Obsidian does not index duplicates; the manifest is enough to undo a
   rename by hand. An "Undo last rename" button was not built (deferred).
6. **Scope choices.** A collision is refused (no silent ` (2)`). A case-only rename is supported (on a
   case-insensitive file system the file is renamed in place). Time: the CLI keeps the old time unless `--time` is
   given (`none` clears it); the dialog is prefilled with the current time and an empty field means "unknown". The
   `date` property keeps its YAML shape (datetime, date or text). The review page also offers the action for
   read-only and note-only notes, because it only needs readable properties. The Meetings page has no row action:
   its rows open the review page, where the dialog is.

**Alternatives.** Renaming in place with `os.rename` and no journal (simplest, but a crash between files breaks
links); asking Obsidian to rename (needs Obsidian running and a plugin; MM3 must work without it); backups inside the
vault (`.trash`-like folder; Obsidian would index or sync them); rewriting archive bodies (they are a record of what
was there).

**Status.** Accepted (2026-10-14).
**Consequences.** A new write path across the whole vault (threat model T-RENAME). Old names disappear from Obsidian's
"recent files"; Obsidian follows the changes on its next index. Links to the meeting from inside archives point at the
old names.

## ADR-0041: Verifying the cloud backends live before release (planning, Phase 15g)
**Context.** The MVP promises that Bedrock and OpenRouter work with the user's own keys, but Phase 08 tested them
only with a botocore Stubber and respx, and Phase 15 deferred the live run because there were no keys. Nick asked for
a live test before release ("AWS Bedrock at a minimum, And ideally … open router") and for plain-language guidance
on how and where to set AWS credentials. Grounding found that AWS keys cannot be entered in Settings, and that
Bedrock silently falls back to an 8192-token window.

**Options considered (credentials).**

| Option | Pros | Cons |
|---|---|---|
| A. Dedicated IAM user, access key + secret, least-privilege policy | What Nick has used before; no host install; works the same natively and in Docker (env or `.env`); easy for a newcomer to follow | Long-lived keys must be guarded, rotated and revoked |
| B. AWS CLI profile / IAM Identity Center (SSO) | Short-lived credentials | Needs the AWS CLI on the host (an OS change) and more steps for a newcomer; awkward in Docker |
| C. Bedrock API key (bearer token) | One value to paste | Newer mechanism the app does not support or document; Bedrock-specific |

**Decision.** (1) **A** is the documented primary path, with a policy limited to invoking models and listing models
and inference profiles (plus `GetFoundationModelAvailability` if boto3 has it). Keys can be entered in Settings
(write-only, masked, `config.yaml` mode 0600) or the environment, which overrides the file. B keeps working through
the existing `profile:` setting and is documented as the alternative; C is out of scope. (2) Test data: the synthetic
eval meetings and the committed CC fixture, **plus one of Nick's real meetings**, which Nick allowed knowing its
transcript is sent to AWS (and OpenRouter if tested). Its outputs stay in the private-eval folder and only numbers go
into docs. (3) Bedrock is required; OpenRouter is tested if Nick provides a key, otherwise recorded as untested,
without blocking the release. (4) Spend ceiling about USD 5 per provider, estimated before each run.

**Status.** Accepted (2026-10-15, planning). Phase 15g appends the results: models, measurements, spend and quirks.
**Consequences.** A new secret entry point in Settings (threat model update in 15g). Nick revokes or rotates the
test keys after the phase.

**Results (Phase 15g, 2026-10-15).** Both providers verified live with Nick's keys; details in
`tests/eval/cloud-results.md`.
- **Credentials:** option A as planned. AWS keys entered in Settings (new write-only fields) worked; Nick's backend
  also carried an AWS profile. The IAM policy in `llm-backends.md` was enough for listing, invoking and streaming.
  OpenRouter: key with a credit limit, entered in Settings.
- **Budget:** Nick lifted the ~$5 Bedrock ceiling during the phase ("all bedrock models that would accomplish the
  function are in scope"). Estimated spend: Bedrock about $12, OpenRouter about $1.
- **Measured (eval, synthetic meetings):** Claude Haiku 5.5 73/75 on Bedrock and 74/75 on OpenRouter at about
  $0.003 per note and 17-18 s; Sonnet 5.5 71/75 at $0.07 and 26 s; Opus 5.5 9/27 on a 7-template subset (good
  content, ignores the summary style rules) at $0.15 and 42 s. Llama 4 Maverick, Qwen3 32B, GLM-5, Mistral Large
  (2402) and GPT-5.5 on Bedrock 6/7 each; Nova Lite 4/7, Nova Micro 2/7; DeepSeek R1 and gpt-oss-20b on Bedrock
  mostly empty answers (reasoning-only). A 151 800-token meeting ran through map-reduce in 2 parts on both providers.
- **Real meeting (31 min, Default Notes, private):** Haiku 31 s (about $0.01), Sonnet 58 s ($0.23, two
  length-limit warnings), Opus 91 s ($0.49), local qwen3:8b 116 s. In the agent's reading Sonnet gave the most useful note
  (the private comparison was left for Nick and deleted at close-out; no text kept).
- **Web UI walk-through (Nick, Bedrock):** decline consent sends nothing, allow writes the note, template switch and
  section regeneration work, remembered consent skips the prompt.
- **Docker:** the CPU image with a temporary `.env` passed `mm3 llm test` and processed the CC clip with Bedrock.
- **Bugs found and fixed:** Claude 5.x rejected `temperature` (every note failed) and reasoned by default
  (empty sections) on both providers; Bedrock was planned at the 8 192 fallback window; the Settings Edit form
  collapsed when models loaded; an empty answer was written as an empty section; tasks without list markers;
  a 4xx error hid the provider's reason (ADR-0044, ADR-0045 and its addendum).
- **Not supported, recorded for later:** Fable 5.1 on Bedrock (needs a data-retention mode), Mistral 7B/Mixtral
  (no system prompt), reasoning-only models without extra `params`, OpenRouter's Qwen3 32B (its provider ignores the
  reasoning switch), unknown windows for GLM, Gemma, Nemotron and GPT-5.x/6 on Bedrock.

## ADR-0042: A filtered cloud model picker with prices and measured recommendations (planning, Phase 15h)
**Context.** Nick wants each provider's model drop-down to list only models that can do MeetingMaster3's job, to show
costs where practical, and to recommend both "the least expensive model with decent performance" and "the top
performing model but it is expensive". Today the pickers list everything the provider returns, and
`cloud_recommendations.yaml` deliberately has no prices (a Phase 08 choice recorded only in that file's comment;
spec §6 asks for "clear cost/privacy notes").

**Options considered (prices).**

| Option | Pros | Cons |
|---|---|---|
| A. Live OpenRouter prices from `/models`; dated Bedrock price table in a data file | OpenRouter is always current; Bedrock needs no extra permission or API; a cost-per-meeting estimate works for both | Bedrock prices can go stale between releases (shown with an "as of" date and a pricing link) |
| B. Live prices for both (AWS Price List API) | Always current | Extra IAM permission (`pricing:GetProducts`), brittle product filtering, slow |
| C. Cost tiers only (today) | Never wrong | Does not give the guidance Nick asked for |

**Decision.** (1) **A.** This supersedes the Phase 08 "no prices" rule. (2) Recommendations are stored as dated data
taken from measured results (15g's eval quality and cost per note), at least **Best value** and **Best quality** per
provider, never computed from price alone. A recommended id that is no longer listed is dropped. (3) One filter
decides "capable" for every picker. (4) The work is split: 15g verifies and measures, 15h builds the picker, so the
recommendations rest on numbers.

**Phase 15h implementation (2026-10-16).**
- *Filter* (`templates/model_check.py:assess`, one rule for every picker): generates text (`can_generate`), text in and
  out (`text_only`, OpenRouter `architecture`), callable as listed (`callable`: a Bedrock Provisioned-only model, or a
  profile-only model without a profile, is hidden), account access not `denied` (the Bedrock listing does not report
  access, so this stays unknown there), not in the `unsuitable` list of `cloud_recommendations.yaml` (15g's measured
  failures), and a workable window after the local cap. Hidden models carry a reason and appear under "Show all".
- *Data files.* `bedrock_models.yaml` gained `prices_as_of` and `prices` (longest prefix, as for context windows). Only
  the Claude 5.5 family is priced (Anthropic list prices as used in ADR-0041); other families show no price rather than
  an unverified one, and rows are added as they are checked. `cloud_recommendations.yaml` is version 2: `picks` per
  backend kind (badge, model, why, measured date) and `unsuitable` (kinds, id prefix, reason); a file with another
  version still serves the generic list. A Bedrock pick matches by base id, so it finds whichever `us.`/`eu.`/`global.`
  profile the account lists; an unlisted pick is dropped; `suggest()` pre-selects Best value for a cloud backend.
- *Tokens-per-minute source* (`llm/cost.py`): 300 transcript tokens per minute of meeting, 700 tokens of prompt overhead
  per call and 350 output tokens per section, fitted to 15g's two measurements (about 80 000 input tokens for a 31-minute
  real meeting through Default Notes' 8 sections; 2 500-3 000 output tokens per note). The estimate is one call per
  section re-sending the transcript, or map-reduce (the generator's `map_budget`) when the window is too small. A
  60-minute note estimates $0.016 with Haiku 5.5 and $0.33 with Sonnet 5.5, against 15g's measured $0.02 and $0.45 per hour.
- *Listing and UI.* Bedrock collapses base and profile ids (`collect_models`; the Region's own profile before `global.`).
  The picker is server-rendered (`templates/picker.py`, `settings/_model_picker.html`) as a native grouped `<select>` that
  fills the model input (`app.js`, no inline script); the input stays the submitted value, so a custom id works.
- *Deviation.* "Lists only models his account can call" is met as far as the API allows (on demand or via a profile);
  checking entitlement would need one call per model.

**Status.** Accepted (2026-10-15, planning). Phase 15h appends the filter rules and data-file formats.
**Consequences.** Someone must refresh the Bedrock price table (and the recommendations) before each release;
Phase 16 checks the `as_of` date.

## ADR-0043: Right-sized `num_ctx` from measured token counts; Ollama settings for small GPUs (Phase 15f)
**Context.** On the 8 GB reference laptop Ollama never exceeds VRAM; it runs whatever does not fit on the CPU,
several times slower. Phase 15e found that map-reduce asked for `usable_tokens(window) + reserve` (Default Notes
15 360, Executive Summary 13 312 on a 16 384 window), although the map prompts and the reduce notes were already
sized to fit in `usable`: the output reserve was counted twice. The same double count hid two underestimates:
the 4-characters-per-token estimate had never been checked against qwen3's tokenizer, and the map chunker did not
count the `[mm:ss]` stamp each turn gets in the prompt (map calls ran up to 3 % over their budget). Retries were
not sized either: a map repair repeats up to 4 000 characters of the failed reply, and Summary Detailed's paragraph
retry repeats up to 8 000 characters of its answer, so in full mode a retry could exceed `num_ctx` (a 31-minute
Executive Summary asked for 9 216 with a largest first call of 8 345 tokens). Ollama silently drops the start of a
prompt that does not fit, so the safety margin must live inside `num_ctx`. The owner had already enabled flash
attention and an 8-bit KV cache on the host Ollama (OSMods "Ollama VRAM Tuning", 2026-10-14).

**Measurement (2026-10-15).** Notes-only runs of Default Notes and Executive Summary on the owner's 31-, 59- and
113-minute meetings (private; script outside the repo, deleted at close-out), old and new code, logging for every
call the estimate of everything sent, the `num_ctx`, Ollama's `prompt_eval_count` and output count, and `ollama ps`.
108 calls: real tokens / estimated tokens averaged **1.005**. Calls of 6 000+ estimated tokens (transcripts and map
chunks, the ones that set `num_ctx`) ranged **0.97-1.011**. Smaller calls were denser: the merged map-reduce notes
(timestamps, names, short lines) reached **1.06-1.115**, and a short final map chunk 1.115 (fixed chat-template
overhead). `prompt_eval_count` reports the whole prompt even when Ollama reuses its prompt cache.

**Options considered.**

| Option | Pros | Cons |
|---|---|---|
| Keep `usable + reserve` | No change | Asks for 1-2k unused tokens; hides the underestimates by accident |
| `usable × margin` for every map-reduce note | Simple | Still guesses; does not cover retries; full mode unchanged |
| **Largest real call × margin, everything known before the first call** | Tight and provably sufficient; same value for every call (ADR-0017) | Map prompts are built before the first call (cheap); a few more lines |
| Size each call separately | Tightest | Ollama reloads the model on every change of `num_ctx` (ADR-0017) |

**Decision.**
1. `num_ctx = ceil(largest call × 1.10 / 1 024) × 1 024`, floored at 4 096 and capped by the window, one value per
   note. A **section call** counts the shared system message and context, the section's prompt tail and its
   `max_tokens`; Summary Detailed adds its paragraph retry (its answer, up to its `max_tokens`, plus the firmer
   instruction); a **regeneration** counts its previous body and feedback. In **map-reduce** every map prompt is
   built first (chunks and task candidates are known), and a map call counts its prompt, its output room and a
   repair turn (the repair prompt plus 250 tokens of the failed reply); the reduce side needs at least the system
   message, the largest section and 512 tokens of notes.
2. The **margin is 10 %** (`CONTEXT_MARGIN`): the calls that set `num_ctx` measured at most 1.011. The **reduce notes**
   are fitted into what the chosen `num_ctx` leaves and counted at **1.15** real tokens per estimated token
   (`NOTES_DENSITY`), because they measured up to 1.115.
3. **Retries repeat only what fits**: the failed map reply (at most 4 000 characters) and the short Summary Detailed
   (at most 8 000) are cut to the room left inside `num_ctx`.
4. The chunker counts 3 tokens per turn for the stamp and line break (`TURN_STAMP_TOKENS`), so map prompts keep to
   `map_budget`. The 70 % map-reduce trigger, `map_budget` and `generation.max_context` are unchanged.
5. **Ollama settings** are documented, never applied by the app: `OLLAMA_FLASH_ATTENTION=1` and
   `OLLAMA_KV_CACHE_TYPE=q8_0` (user guide `hardware.md`, with systemd drop-in, Docker and `ollama ps` checks). The
   bundled Docker `ollama` service sets both (overridable from `.env`); the CPU override inherits them, which is
   harmless because Ollama keeps the f16 cache where flash attention is unsupported.

**Result.** On a 16 384 window, long meetings now ask for **13 312** with both templates (Default Notes was 15 360;
Executive Summary is unchanged, its reserve was small). Full mode can ask for more than before when Summary
Detailed's retry needs it (31-minute Executive Summary 9 216 → 11 264), which closes a silent-truncation gap. No
call in the 14 measured notes had `prompt_eval_count + output > num_ctx`. Paired run (59 minutes, Default Notes, back
to back): old code 339 s with 11 % of qwen3:8b on the CPU, new code 229 s entirely on the GPU (32 % faster). The
eval is unchanged between old and new code on the same Ollama; three notes that find one item fewer than the Phase 15
baseline do so with the old code too (host settings), and the baseline was updated. Details: `docs/PERFORMANCE.md`.

**Status.** Accepted (2026-10-15).
**Consequences.** Every generation call has a provable fit. A model whose tokenizer is much less efficient on
English than qwen3 (more than about 1.1 tokens per 4 characters on transcripts) would need a larger margin; the
measurement script's method is described here so it can be repeated. Default Notes' long meetings hold about
150 MB less KV cache, which on 8 GB keeps more of the model on the GPU.

## ADR-0044: Bedrock context windows from a dated family table (Phase 15g)
**Context.** Bedrock's API reports no context window, so every Bedrock model was planned with the 8 192-token
fallback unless the user set `context_window`: a 200k Claude split a one-hour meeting into many small map-reduce
parts. Model cards list windows, but there is no API for them.

| Option | Pros | Cons |
|---|---|---|
| A. A small data file of model-family prefixes, smallest window per family, dated | Works offline; one place to update; 15h can extend it | Goes stale; new families are unknown until added |
| B. Per-model exact table | Exact | Hundreds of ids (188 listed in one account), constant upkeep |
| C. Probe the window with a test call | Always current | Costs money and time; Bedrock gives no clean signal |

**Decision.** **A.** `llm/bedrock_models.yaml` maps id prefixes (`anthropic.claude`, `amazon.nova-pro`, `meta.llama3`
…) to the family's smallest window, checked against the AWS model cards on 2026-10-15; the longest prefix wins, and
a cross-Region profile's geography (`us.`, `eu.`, `apac.`, `global.`…) is ignored. Claude is capped at 200 000 even
where cards say 1M, so prompts stay out of the long-context price tiers (Haiku 5.5 bills prompts over 100k at 5×).
A configured `context_window` still wins. An unknown model keeps 8 192 and **Test** says so with a hint. The model
list carries the window too (`ModelInfo.context_window`) for 15h.
**Status.** Accepted (2026-10-15). Verified live: a 151 778-token meeting on `us.anthropic.claude-haiku-5-5` ran
through map-reduce in 2 parts (the 8 192 fallback would have needed about 25).
**Consequences.** Unknown families seen in one account (GLM, Gemma, Nemotron, OpenAI GPT-5.x/6 on Bedrock) need a
row or a manual window; 15h may add them. OpenRouter reports windows itself but lists Claude 5.x at 1M; its `anthropic/claude*` models are
planned at the same 200 000 for the same price reason (`openai_compat.CLAUDE_WINDOW`; a configured window still wins).

## ADR-0045: Bedrock adapts to what a model rejects; empty answers are errors (Phase 15g)
**Context.** The first live calls failed in ways the Stubber tests could not show. Claude 5.x on Bedrock rejects
`temperature` (HTTP 400, "`temperature` is deprecated for this model"), as do OpenAI GPT-5.x/6 ("doesn't support the
temperature field"), and the app sends one on every call. Haiku 5.5 thinks by default, ignored
`generation.think: false`, and spent a whole section's `max_tokens` on hidden reasoning: an empty section. How to
turn thinking off differs by model: Haiku 5.5 and Claude 4.x take `thinking: {type: disabled}`, Sonnet 5.5 asks for
`between_tools`, Opus 5.5 for `output_config.effort`; non-Claude models reject the unknown key.

| Option | Pros | Cons |
|---|---|---|
| A. Per-model capability table (no temperature; thinking switch) | Explicit, no failed calls | Breaks on every new model; dozens of rows |
| B. Repeat a rejected call as the model's error advises, once, and remember per model | Survives new models; a 400 is not billed | One extra (free) round trip per model per run; depends on AWS wording |
| C. Never send temperature or thinking fields | Simplest | Loses temperature where it works (Llama, Mistral, Claude 4.x) and leaves thinking on, which empties sections |

**Decision.** **B**, limited to fields the app itself adds: when a `ValidationException` names `temperature`, the
call is repeated without it; when it names thinking, the switch moves to `between_tools` (if the message says so),
then `output_config: {effort: low}` (if it names effort), then nothing. The choice is remembered for the model, and at
most three attempts are made. Thinking fields in the backend's `params` are never touched, and `generation.think:
true` sends none. Separately, `check_answer` (all cloud backends, streaming too) turns an **empty answer that ended
on `length` or a content filter into `E_LLM_BAD_RESPONSE`** with a hint, instead of an empty section; a cut-off
answer that has text is returned and the generator still warns. Bedrock's `stopReason` is normalised to `stop` /
`length`. The real validation texts (base id of a profile-only model, Provisioned-only model, unknown id, other
model complaints) map to `E_LLM_CONFIG` with a remedy.
**Status.** Accepted (2026-10-15). Verified live on Haiku 5.5, Sonnet 5.5 and Opus 5.5 (9/9 live checks each) and in
the eval.
**Consequences.** If AWS rewords these messages, the adaptation stops and the clear `E_LLM_CONFIG` error appears
instead (no silent failure). Each recorded message has a unit test.

**Addendum (OpenRouter, 2026-10-15).** OpenRouter's Claude 5.x also reasons by default and emptied sections the same
way (Haiku 5.5: 278 characters of text for 800 output tokens). `generation.think` now maps to OpenRouter's unified
`reasoning: {enabled: …}` switch (OpenRouter backends only; `reasoning` in the backend's `params` wins). Sonnet 5.5 and
Opus 5.5 refuse it ("Reasoning is mandatory for this endpoint and cannot be disabled"), so on that message the call
is repeated once with `reasoning: {effort: low}` and 4 096 extra output tokens, remembered per model, like Bedrock's
`THINKING_ROOM`. A 4xx from any HTTP backend now shows the provider's own short reason (redacted, 300 characters)
instead of only "returned HTTP 400". Verified live: 9/9 checks on OpenRouter Haiku, Sonnet and Opus 5.5.

