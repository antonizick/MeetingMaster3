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

## Implemented so far (Phases 02, 03, 04, 05 and 08)
| Module | Responsibility |
|---|---|
| `app.py` | `create_app(settings, paths)` factory. Middleware order (outermost first): TrustedHost, security headers, CSRF. The lifespan opens `mm3.db` and starts/stops the `JobRunner`. |
| `cli.py` | Typer CLI `mm3`: `serve`, `version`, `doctor`, `config path`, `config show`, `llm list`, `llm test`, `jobs list`, `jobs prune [--dry-run]`. |
| `config/paths.py` | XDG directories with `MM3_*_DIR` overrides; created `0700`. |
| `config/settings.py` | Pydantic `Settings`. Precedence: defaults < `config.yaml` < `MM3_*` env. Atomic `0600` save. Secrets are `SecretStr`. |
| `errors.py` | `MM3Error(code, message, hint)` and a JSON/HTML exception handler chosen by `Accept` (FastAPI imported lazily). |
| `domain/transcript.py` | `Word`, `Segment`, `Transcript`, `SpeakerMap` (stable `Speaker N` placeholders, `apply`), `Turn`/`group_turns`, `CompanionTranscript`. Immutable pydantic models. |
| `domain/meeting.py`, `domain/note.py` | `MeetingMeta` (frontmatter fields, normalised); `Note` = metadata + ordered `TextBlock`/`Section` blocks; marker grammar constants. |
| `domain/filenames.py` | `parse_filename`: date, time and title from recorder file names. |
| `markdown/sections.py` | Strict marker scanner (`scan_sections`, `MarkerError`), `replace_section`, `append_section`, `list_sections`; byte-preserving. |
| `markdown/frontmatter.py` | Frontmatter split/parse; per-key raw chunks; MM3-style emitter with verified fallbacks. |
| `markdown/note_parser.py`, `note_writer.py` | `parse_note` → `ParsedNote`; `build_note`, `render_note(note, base=)` (reuses unchanged bytes). |
| `markdown/transcript_format.py` | Companion transcript render/parse, hidden JSON-lines data block, `rename_speakers`. |
| `markdown/diff.py` | `unified_diff`, `side_by_side` rows, `diff_stats` (stdlib difflib). |
| `vault/naming.py`, `paths.py`, `io.py`, `archive.py` | R13 names and collisions; vault root checks and confinement; atomic non-clobbering writes and exact reads; R12 archives. |
| `storage/db.py`, `migrations.py`, `repositories.py` | One shared WAL SQLite connection; forward-only numbered migrations (`schema_version`); `JobRepository` (enforces the job state machine), `StageRepository`, `RecentMeetingsRepository`. See [`dev-guide/storage.md`](dev-guide/storage.md). |
| `audio/ingest.py`, `audio/stage.py` | Streamed upload save with size limit, ffprobe validation, 16 kHz mono WAV normalisation, Opus re-encode; the `ingest` stage. |
| `jobs/models.py`, `stage.py`, `pipeline.py` | Job/stage states and transitions, `JobOptions`, `ProgressEvent`; the `Stage` protocol, `StageContext`, `InputRequired`; the canonical meeting pipeline and `register_stage`. |
| `jobs/runner.py`, `progress.py`, `retention.py`, `files.py`, `fakes.py` | `JobRunner` (dispatcher, GPU semaphore, resume, cancel, input pauses, retry hooks); `ProgressBus` with ETA; R8 retention and pruning; job folders and path confinement; fake stages (`MM3_FAKE_PIPELINE=1`). |
| `web/api/jobs.py` | `/api/jobs` routes: streamed multipart upload, list, get, cancel, resume, input, delete, pin/unpin, audio (HTTP Range), SSE events. |
| `logging.py` | Logging setup with a secret-redaction filter on the handler. |
| `web/security.py` | Security-headers and CSRF middleware. |
| `hardware/detect.py` | `HardwareInfo`: nvidia-smi, then torch.cuda (only if importable), then CPU/RAM from `/proc`. Cached; `get_hardware(refresh=True)` re-detects. |
| `hardware/profiles.py` | `cpu`, `vram8`, `vram16`, `vram24plus`, chosen from total VRAM or `hardware.profile`. |
| `hardware/recommend.py` + `recommendations.yaml` | Per-profile transcription and local-LLM recommendations, ETA estimates and risk warnings. All numbers are data, tagged estimated or measured. |
| `hardware/doctor.py` | Environment checks for `mm3 doctor` (ffmpeg, Python, ML extras, HF token, Ollama, vault, data dirs). |
| `web/hardware.py` | `GET /api/hardware`, `POST /api/hardware/refresh`. |
| `web/routes.py` | `GET /healthz`, `GET /` (Jinja2 base layout, placeholder page). |
| `llm/base.py` | `LLMBackend` protocol, request/result types, error codes (`E_LLM_*`), `is_local_url`. |
| `llm/ollama.py`, `openai_compat.py`, `bedrock.py` | The three adapters (Phase 08). Bedrock is lazy-imported; sync boto3 calls run in threads. |
| `llm/_http.py` | Shared httpx send with bounded jittered retries (429/5xx) and error normalisation. |
| `llm/registry.py` | Kind to factory map and `BackendRegistry` (config to cached backend instances). |
| `llm/budget.py`, `llm/consent.py` | 70% context budgeting and speaker-turn chunking; cloud-egress consent check. |
| `llm/recommendations.py` + `cloud_recommendations.yaml` | Local (Phase 05) plus cloud model suggestions, no prices. |
| `web/llm.py` | `/api/llm/*` routes (masked config, test, models, recommendations). |

All other packages are empty placeholders with a docstring, filled in by later phases.

### Note round-trip (Phase 03)
```
file text ──parse_note──▶ ParsedNote { note: Note, frontmatter chunks, raw sections, errors }
                                 │ edit the Note (with_section / with_meta)
                                 ▼
               render_note(note, base=parsed) ──▶ text: unchanged bytes reused verbatim
```
`domain` and `markdown` are pure (no I/O); `vault` does all filesystem work. The format is
normative in [`dev-guide/note-format.md`](dev-guide/note-format.md).

### Jobs (Phase 04)
```
browser/curl ──POST /api/jobs (multipart, streamed)──▶ <data>/jobs/<id>/original.<ext> ──ffprobe──▶ jobs row (queued)
JobRunner (asyncio, in the app lifespan)
  dispatcher ──▶ up to jobs.max_concurrent job tasks
     each stage: [GPU semaphore if uses_gpu] ──▶ worker thread: stage.run(ctx) ──▶ artifact in job folder
                 job_stages row updated ──▶ ProgressBus ──▶ GET /api/jobs/<id>/events (SSE)
  InputRequired ──▶ waiting_for_input ──POST /input──▶ queued again
  all stages done ──▶ audio re-encoded to Opus ──▶ written ──▶ pruner deletes it after retention
```
The job state machine, the Stage protocol, checkpoint artifacts and the SSE format are specified in
[`dev-guide/jobs-and-stages.md`](dev-guide/jobs-and-stages.md); ADR-0013 records the design choices.

_To be expanded in Phases 06-15 (transcription, generation and UI data flow, sequence diagrams)._
