# Phase 04: Job Orchestration, Storage & Audio Ingest

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 03 · **Branch:** `phase-04-jobs-orchestration`

## Read first
`CLAUDE.md`, `prompts/_shared-instructions.md`, and `docs/SPECIFICATION.md` §3 (flow step 4, job controls), §4, §10, §15.2 (R3–R5, R7, R8) and §15.3 (S4). Audio retention is decided (Q1, ADR-0006, spec R8): Opus re-encode at `written`, 90-day default, per-meeting pin.

**Phase 03 interfaces you will use:** `meetingmaster3.domain.transcript.Transcript` (serialise artifacts with `model_dump_json()` / `Transcript.model_validate_json()`), `domain.filenames.parse_filename` for upload pre-fill, and `vault.io.atomic_write_text` for any atomic file write. Domain models are frozen pydantic models; `model_copy(update=...)` skips validation, so build new instances when values come from outside.

## Goal
A robust background job system: an upload becomes a job, the job runs an ordered list of stages with live progress, survives restarts (resume from the last checkpoint), can be cancelled, and runs at most one GPU-heavy job at a time. Fake stages prove the machinery end to end before any ML exists.

## Tasks
1. **`storage/`:** SQLite via stdlib `sqlite3` (or SQLAlchemy Core if justified in an ADR), in WAL mode, at `<data>/mm3.db`. A small forward-only migration runner (`schema_version` table). Tables: `jobs` (id, created_at, status, title, meeting_date, source_filename, audio_path, settings_json, error_code, error_message, current_stage), `job_stages` (job_id, stage, status, started_at, finished_at, artifact_path, attempt, detail_json), `recent_meetings` (note_path, transcript_path, mm3_id, title, date, last_opened). Repository classes with typed methods. Leave `voiceprints` and `feedback` to their own phases, but make the migration runner support them.
2. **`audio/ingest.py`:** stream the upload to `<data>/jobs/<job-id>/original.<ext>` (never trust the client filename for paths), enforce the max size, run `ffprobe` (duration, codec, channels, sample rate; reject anything that isn't audio or video with an audio track), then normalise with `ffmpeg` to `audio.wav` (16 kHz mono PCM). Wrap subprocesses with timeouts and no shell. If `ffmpeg` is missing, raise `MM3Error` with an install hint.
3. **`jobs/`:**
   - `Stage` protocol: `name`, `display_name`, `uses_gpu: bool`, `run(ctx) -> artifact path`, cooperative `ctx.check_cancelled()`, and `ctx.progress(fraction, message)`.
   - `Pipeline`: an ordered list of stages per job type. Canonical order: `ingest → transcribe → align → diarize → speaker_suggest → (await_speaker_confirmation) → generate → write`. **`await_speaker_confirmation` is a human-in-the-loop pause.** The job enters the `waiting_for_input` status and resumes when the API receives the mapping.
   - `JobRunner`: an asyncio-managed worker. GPU stages run in a thread or subprocess so the event loop stays responsive. A **global GPU semaphore** of size 1, a CPU-stage pool, a startup scan that marks interrupted jobs `interrupted` (resumable), `resume(job_id)` from the first non-complete stage (R4), `cancel(job_id)`, and per-stage retry hooks (Phase 06 uses them for OOM).
   - `ProgressBus`: in-process pub/sub. Events carry `{job_id, stage, status, fraction, message, eta_seconds?}`. ETA is a simple rate estimate per stage.
4. **API (`web/api/jobs.py`):** `POST /api/jobs` (multipart upload plus JSON options; returns the job id), `GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel`, `POST /api/jobs/{id}/resume`, `DELETE /api/jobs/{id}` (removes artifacts and respects retention), and `GET /api/jobs/{id}/events` (**SSE** stream that replays current state, then live events, with a heartbeat). All state-changing routes go through Phase 02's CSRF protection.
5. **Retention (R8, ADR-0006):** when a job reaches `written`, re-encode the audio to Opus mono at about 24 kbps (`audio.opus`), delete the original and the WAV, and record `audio_expires_at` (written + `privacy.audio_retention_days`, default 90; `null` means forever; `0` means delete now). Add a `jobs.audio_pinned` column and a pin/unpin API. Run the pruner at startup and every 24 h, and on demand with `mm3 jobs prune [--dry-run]`. Pinned jobs are never pruned. The audio endpoint returns a clear `E_AUDIO_EXPIRED` once the audio has been pruned. Tests: expiry maths, pin respected, dry run, and an Opus file produced from a short generated tone.
6. **Fake stages** (`jobs/fakes.py`): `FakeTranscribe`, `FakeGenerate` and others that sleep and emit progress, used in tests and enabled with `MM3_FAKE_PIPELINE=1` for UI development in Phase 10.

## Tests
State transitions (a table-driven state-machine test); resume after a simulated crash (kill mid-stage, restart the runner, and the job resumes at the right stage without redoing completed ones); cancel; GPU semaphore exclusivity (two jobs, so GPU stages must not overlap); SSE event ordering and replay; upload size limit; ffprobe rejection of a non-audio file; normalisation of a short generated tone (create it with ffmpeg in the test; mark `slow` if needed); path safety of job dirs.

## Out of scope
Real transcription, LLM, UI pages.

## Acceptance criteria
- With `MM3_FAKE_PIPELINE=1`, `curl` can upload a file and stream SSE events through to `waiting_for_input`. Posting a mapping finishes the job.
- Killing the server mid-job and restarting resumes correctly.
- All tests pass and CI is green.

## Phase-specific docs
`docs/dev-guide/jobs-and-stages.md` (state machine diagram in Mermaid, how to add a stage, checkpoint artifacts); `docs/dev-guide/storage.md` (schema and migrations); README (ffmpeg prerequisite); SECURITY and PRIVACY (where audio is stored and its retention); configuration doc (upload limit, retention). Then the standard close-out checklist.
