# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Review workspace (Phase 11) at `/meetings/{mm3-id}`: the recording with play/pause, ±5 s, speed
  0.75-2× and keyboard shortcuts (Space/K, J, L; not while typing); the transcript with speaker colours,
  click-to-seek on any word or timestamp, the playing segment highlighted and followed (pauses when you
  scroll), and search; a resizable splitter that stacks on narrow screens. The note is edited as parts
  with protected section markers, autosaved as a draft, previewed rendered (with clickable `[mm:ss]`
  references) and saved atomically, with a diff and keep-mine / take-theirs when the file changed
  elsewhere. Per-section regeneration with instructions, model choice, side-by-side and unified diffs,
  Accept, Accept & archive previous (R12) and Discard; "append as a new section" for damaged markers
  (R11); whole-note template switch with an archive and "Preserved notes"; renaming speakers after the
  fact (transcript, properties, header and generated sections); **Open a note**: a vault browser and the
  Recent list; note-only mode when the transcript is missing (locate and link it, or transcribe the
  retained recording again) and read-only mode for notes without markers. Feedback slots for Phase 12.
  Guide: `docs/user-guide/reviewing-and-editing.md`. ADR-0020, ADR-0021, spec R23.
- Database migration 3: `recent_meetings.job_id`.
- Web UI, core flow (Phase 10): first-run vault setup with live validation and a preview of the output
  path, upload with drag and drop and progress, hardware confirmation with an ETA and advanced
  overrides, template and model pickers with a local/cloud badge and a cloud consent dialog, live job
  progress over SSE (cancel, retry, "retry with smaller model", language question, cloud-consent
  question), the Name Speakers screen (audio samples, suggestions, "same person as", "remember this
  voice"), a completion page with an `obsidian://` link, a sanitised read-only note preview, and the
  Recent list (resume, delete). Vendored HTMX 2.0.11 and the CSP build of Alpine.js 3.17.4; no CDN and
  no build step. Playwright browser smoke test (`e2e` marker).
- `markdown-it-py` is now a direct dependency (note preview); `playwright` is a dev dependency.

### Security
- Review workspace (Phase 11): no change to the strict CSP (no editor library); every action is CSRF
  checked, re-confines the note path to the vault and checks its `mm3-id`; writes are atomic and refused
  when the file changed since it was opened; section-marker lines are never accepted from the browser.
- Strict CSP for the UI (`script-src 'self'`, `style-src 'self'`, no inline script, no `eval`; HTMX runs
  with `allowEval=false`); every UI action is an HTMX request carrying the CSRF header. The note preview
  renders Markdown with raw HTML disabled, images off and only http(s)/mailto links, and only opens
  `.md` files that resolve inside the vault.
- Note generation enforces cloud-egress consent (S6) before any request: a job using a cloud backend
  without consent pauses with a `cloud_consent` question, and declining sends nothing. Template files
  and model output are treated as untrusted (strict validation; forged section markers are stripped).
- Voiceprints (biometric data, S7) are opt-in, stored only for speakers the user marks "remember", never
  returned by the API or CLI, and physically erased on delete: SQLite `secure_delete` is now on for
  `mm3.db` and voiceprint deletes truncate the WAL. Deleting all voiceprints over the API needs a
  single-use confirmation token.
- pyannote.audio 4 sends usage telemetry to `otel.pyannote.ai` by default; MeetingMaster3 now always
  disables it (`PYANNOTE_METRICS_ENABLED=false`) together with Hugging Face Hub telemetry (spec S6).
- Cached whisper and diarization models load without contacting Hugging Face, so a transcription job
  makes no network calls (verified with a socket audit).

### Changed
- "Review & edit" on the job page and the notes in **Recent** now open the review workspace;
  `/preview` is the read-only view for files that are not MeetingMaster3 notes (and links MM3 notes to
  the workspace). The main menu gains **Open a note**.
- The `generate` and `write` stages are built in (no longer placeholders). `MM3_FAKE_PIPELINE=1` now
  runs the real generation stage with an offline fake model and writes the note to the vault when one
  is configured.
- `JobRunner.resume()` takes `from_stage` to re-run completed stages; `JobRunner.update_options()`
  changes a queued or waiting job's options; stages may decide their GPU use per job (`gpu_for`).
- `GenerateRequest.think` turns reasoning on or off for Ollama models that support it.
- The note header shows only the date when the meeting time is unknown (stored as midnight).
- The `await_speaker_confirmation` stage moved to `speakers.stages.SpeakerConfirmationStage` (Phase 07).
  It normalises answers to `{label: {"name", "person_id", "enroll"}}`, refuses unknown fields, completes
  without asking when the transcript has no speakers, and its artifact is now `speakers.confirmed.json`.
- `speaker_suggest` is built in (no longer a placeholder); the fake pipeline's version uses a
  deterministic fake embedder.
- `MM3Error` takes optional `details` (machine-readable extras such as suggested resume overrides), stored
  in the failed stage's `detail.error.details`.
- `StageContext.warn()` records user-visible stage warnings; `GET /api/jobs/{id}` lists them as `warnings`.
- `UnavailableStage` accepts a custom message and hint.
- `mm3 doctor`: "ML extras" became "Transcription engine", plus checks for the cached whisper, alignment
  and diarization models.
- `hardware/recommendations.yaml`: the `vram8` speed is now measured (14-16x real time, was estimated 15-30x).
- `.gitignore`: the app-data `jobs/` rule is anchored to the repository root (`/jobs/`); it was also
  hiding the `meetingmaster3.jobs` package.
- CI installs ffmpeg so the audio ingest tests run.
- `errors.py` imports FastAPI lazily, so the pure `domain`/`markdown`/`vault` layers can raise `MM3Error`
  without depending on the web stack.

### Added
- Templates and note generation (Phase 09): template file format with line-numbered validation
  (`docs/dev-guide/template-format.md`); five built-in templates (Executive Summary, Technical
  Deep-Dive, Decision Log, Action-Focused, Just the Facts) copied into the vault on first use without
  ever overwriting edited copies; vault templates override built-ins; prompt assembly with a
  prompt-cache-friendly shared prefix; one LLM call per section with temperatures by section kind;
  map-reduce for meetings that exceed the context window (per-chunk JSON extraction with repair and
  retry, merge and dedupe); tagged task candidates and an owner guard against invented owners;
  deadline dates computed from the meeting date; section checkpoints so failed generation resumes;
  `generate` and `write` stages (note + companion transcript linked both ways, recent meetings,
  idempotent after a crash); `mm3 process` (headless audio → vault note) and `mm3 templates
  list|validate|install`; `GET /api/templates`, `POST /api/templates/install`,
  `POST /api/jobs/{id}/generate`, `POST /api/notes/regenerate-section`; settings `generation.*`; job
  options `meeting_time`, `participants`, `tags`, `location`, `instructions`; a generation eval
  (`tests/eval/`). Docs: `docs/user-guide/templates.md`. ADR-0016 to ADR-0018, spec R22.
- Speaker naming and opt-in voiceprints (Phase 07): per-speaker talk time, overlap-free speech and sample
  clips; WeSpeaker embeddings from the cached diarization model; matching by max cosine similarity with a
  one-to-one (Hungarian) assignment, threshold and margin (ADR-0015); `GET/POST /api/jobs/{id}/speakers`
  (merging labels, enrolling voices); `GET /api/voiceprints`, `DELETE /api/voiceprints/{id}` and a
  two-step `DELETE /api/voiceprints`; `mm3 voiceprints list|delete|wipe`; database migration 2
  (`voiceprints`, `voiceprint_embeddings`); `speakers.cascade` applies one speaker map to the transcript,
  note frontmatter and companion transcript; settings `speakers.match_threshold`, `match_margin`,
  `max_embeddings_per_person`; user guide `docs/user-guide/speakers.md`; spec amendment R21.
- Transcription and diarization (Phase 06): the `ml` extra (`whisperx==3.8.6`, torch 2.8.0 with CUDA 12.8
  wheels, pyannote.audio 4.0.7); real `transcribe` (faster-whisper), `align` (wav2vec2) and `diarize`
  (`pyannote/speaker-diarization-community-1`) job stages producing `transcript.json`, `aligned.json`,
  `diarization.json` and `transcript.final.json`; non-English detection that pauses the job for
  proceed/abort; one automatic retry on CUDA out-of-memory, then `E_OOM` with a smaller-model suggestion;
  non-diarized fallback with a clear warning when there is no Hugging Face token or diarization fails;
  segments split at speaker changes; models freed after each stage and a local Ollama asked to unload
  before transcription (R5); `mm3 models status|download`; settings `transcription.compute_type`,
  `batch_size`, `device`, `language`, `on_non_english`, `diarization_model`, `offline`, `unload_ollama`;
  job options `transcription_model`, `compute_type`, `batch_size`, `language`, `on_non_english`; a 60 s
  CC-BY-4.0 AMI Meeting Corpus test clip and GPU integration tests. Docs:
  `docs/user-guide/transcription.md`. ADR-0014, spec R20.
- Job orchestration and audio ingest (Phase 04): SQLite storage in WAL mode with forward-only migrations
  (`jobs`, `job_stages`, `recent_meetings`); streamed multipart upload into a per-job folder with a size
  limit, ffprobe validation and ffmpeg normalisation to 16 kHz mono WAV; a `Stage` protocol, the
  canonical meeting pipeline and a stage registry; `JobRunner` with one global GPU semaphore, resume from
  the first incomplete stage (R4), cooperative cancel, human-in-the-loop `waiting_for_input`, retry hooks
  and startup recovery of interrupted jobs; `ProgressBus` with ETA estimates; `/api/jobs` (upload, list,
  get, cancel, resume, input, delete, pin/unpin, audio with HTTP Range, SSE events with replay and
  heartbeat); audio retention (R8): Opus re-encode at `written`, expiry, pinning, pruning at startup,
  every 24 h and with `mm3 jobs prune [--dry-run]`; `mm3 jobs list`; fake stages behind
  `MM3_FAKE_PIPELINE=1`; settings `audio.max_upload_mb`, `audio.opus_bitrate_kbps`,
  `jobs.max_concurrent`, `jobs.prune_interval_hours`. Docs: `docs/dev-guide/jobs-and-stages.md`,
  `docs/dev-guide/storage.md`. ADR-0013, spec R19.
- Data model and Markdown round-trip (Phase 03): pydantic domain models (`Transcript`, `Segment`, `Word`,
  `SpeakerMap`, `MeetingMeta`, `Note` as ordered text/section blocks, `CompanionTranscript`); a strict
  section-marker scanner with structured `MarkerError`s and byte-preserving `replace_section` /
  `append_section`; raw-preserving YAML frontmatter (unknown properties, order and comments kept); note
  writer/parser with the Appendix B header and AI Recommendations last; the companion transcript format
  with a hidden lossless data block and in-place speaker renaming; vault naming (R13), path confinement,
  atomic non-clobbering writes and R12 archives; unified and side-by-side section diffs; a recorder
  filename parser. Normative format: `docs/dev-guide/note-format.md`. ADR-0010 to ADR-0012, spec R18.
- Tests: Hypothesis round-trip properties (500 examples each), every R11 marker failure mode, path-escape
  and atomic-write tests, golden note/transcript fixtures in `tests/fixtures/notes/`.
- Hardware awareness (Phase 05): GPU/VRAM detection (nvidia-smi, torch.cuda if present, CPU fallback; no ML extras needed),
  hardware profiles `cpu`/`vram8`/`vram16`/`vram24plus` with a `hardware.profile` override, data-driven transcription
  and local-LLM recommendations (`recommendations.yaml`, marked estimated vs measured), ETA estimates, risk warnings,
  `GET /api/hardware` and `POST /api/hardware/refresh`, and the `mm3 doctor` command.
- LLM backend abstraction (Phase 08): `LLMBackend` interface; Ollama, OpenAI-compatible (OpenRouter, OpenAI and custom presets) and AWS Bedrock (Converse/ConverseStream, optional `bedrock` extra) adapters; `BackendRegistry`; typed `llm.backends` config with masked API keys; context budgeting (70% rule) and speaker-turn chunking; cloud-egress consent check; `/api/llm/*` endpoints; cloud model suggestions data file; `mm3 llm list` and `mm3 llm test`; Ollama `unload_all()` for VRAM handoff.
- Python scaffold (Phase 02): `uv` project pinned to Python 3.12, `src/meetingmaster3` package tree, `mm3` CLI
  (`serve`, `version`, `config path`, `config show`) and a FastAPI app factory serving `/` and `/healthz`
  on `127.0.0.1:8765`.
- Configuration: pydantic `Settings` (defaults < `config.yaml` < `MM3_*` env), XDG paths with overrides,
  atomic `0600` saves, masked `SecretStr` secrets, `MM3Error` with JSON/HTML handler.
- Security middleware: Host allowlist (DNS rebinding), security headers and CSP, double-submit CSRF with
  Origin check; log secret-redaction filter.
- Quality gates: ruff, strict mypy, pytest (markers registered, 26 tests), coverage, pre-commit (gitleaks,
  audio-file guard, large-file guard), `ci.yml` workflow (lint, types, tests, `pip-audit`, gitleaks).
- `scripts/gen_third_party.py` generates the runtime-dependency table in `THIRD_PARTY_NOTICES.md`.
- Docs: configuration reference, installation and developer setup guides; ADR-0005 verified, ADR-0007 added.
- Project governance files: `LICENSE` (Apache-2.0), `NOTICE`, `THIRD_PARTY_NOTICES.md`, `README.md`,
  `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`.
- Repository hygiene: `.gitignore` (audio, secrets, models and local data excluded),
  `.editorconfig`, `.gitattributes`, `.env.example`.
- GitHub scaffolding: issue forms, pull request template, Dependabot config and a Markdown link
  check workflow.
- Documentation skeleton: `docs/ARCHITECTURE.md`, `docs/PRIVACY.md`, user and developer guide indexes.
- Planning artifacts from Phase 00: specification v1.1, ADR log, implementation plan and phase prompts.
