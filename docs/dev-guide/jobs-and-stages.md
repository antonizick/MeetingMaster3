# Jobs, stages and checkpoints

Phase 04 built the job system that every processing step runs on. Code: `src/meetingmaster3/jobs/`,
`audio/`, `storage/` and `web/api/jobs.py`. Spec: §3 step 4, §15.2 R4, R5, R7 and R8, ADR-0013.

## Overview
```
POST /api/jobs ──▶ upload streamed to <data>/jobs/<id>/original.<ext> ──▶ ffprobe ──▶ job row (queued)
                                                                                    │
JobRunner dispatcher ◀── asyncio.Queue ◀────────────────────────────────────────────┘
   │  up to jobs.max_concurrent jobs in flight
   ▼
for each stage from the first incomplete one:
   GPU stage?  acquire the global GPU semaphore (held across consecutive GPU stages)
   run stage.run(ctx) in a worker thread ──▶ artifact file in the job folder
   record artifact + status in job_stages ──▶ ProgressBus ──▶ SSE /api/jobs/<id>/events
```

## Job states
```mermaid
stateDiagram-v2
    [*] --> queued: upload accepted
    queued --> running: dispatcher picks it up
    queued --> cancelled: cancel
    running --> waiting_for_input: a stage raises InputRequired
    running --> written: every stage completed (audio re-encoded to Opus)
    running --> failed: a stage raised (after its retry hook declined)
    running --> cancelled: cancel (cooperative)
    running --> interrupted: server stopped mid-stage
    waiting_for_input --> queued: POST /input
    waiting_for_input --> cancelled: cancel
    interrupted --> queued: resume
    interrupted --> cancelled: cancel
    failed --> queued: resume (optionally with option overrides)
    cancelled --> queued: resume
    written --> [*]
```
The table is `jobs.models.TRANSITIONS`; `JobRepository.set_status` refuses anything else with
`E_JOB_STATE` (HTTP 409). A test walks every pair of states.

Stage states: `pending`, `running`, `waiting`, `completed`, `failed`, `cancelled`, `interrupted`.

### Startup and shutdown
- **Startup** (`JobRunner.recover`): jobs left `running` by a crash become `interrupted` with error
  code `E_INTERRUPTED`, and their running stage becomes `interrupted`. Jobs still `queued` are queued
  again. Interrupted jobs are **not** resumed automatically; the user resumes them (a job that crashed
  the server should not crash it again on every start).
- **Shutdown** (`JobRunner.stop`, called from the app lifespan): running stages are asked to stop
  (`ctx.check_cancelled()` raises), their jobs become `interrupted`, and the runner waits up to 10 s.

## The Stage protocol
```python
class Stage(Protocol):
    name: str  # stable id stored in job_stages.stage
    display_name: str  # shown in the UI ("Transcribing")
    uses_gpu: bool  # serialised by the global GPU semaphore

    def run(self, ctx: StageContext) -> Path: ...  # in a worker thread
    def should_retry(self, ctx: StageContext, exc: Exception) -> bool: ...  # retry hook
```
Subclass `jobs.stage.BaseStage` for the defaults (no retry, CPU, display name from `name`).

`StageContext` gives a stage:

| Member | Use |
|---|---|
| `job`, `job_id`, `job_dir`, `settings` | The job row, its folder and the app settings. |
| `options` | The job's options (`JobOptions` as a dict). Changes made in `should_retry` are saved. |
| `artifacts` | Paths of completed earlier stages' artifacts, keyed by stage name. |
| `attempt` | 1 on the first run of this stage in this run of the job. |
| `progress(fraction, message, eta_seconds=None)` | Live progress; the ETA is estimated from the rate when omitted. |
| `check_cancelled()` | Call between chunks of work; raises `JobCancelled`. |
| `sleep(seconds)` | Cancellable sleep. |
| `artifact(name)`, `write_json(name, data)` | A path in the job folder; atomic JSON write. |
| `input()` | The answer to this stage's `InputRequired`, once submitted. |
| `db` | The app `Database` (for repositories such as `RecentMeetingsRepository`). |
| `warn(message)` | A user-visible warning that does not fail the stage (Phase 06). It is published as progress, kept in the stage's `detail.warnings` on completion or failure, and listed in `GET /api/jobs/{id}` as `warnings: [{stage, message}]`. |

Rules:
- **The artifact must be a file inside the job folder** (`E_STAGE_ARTIFACT` otherwise). A stage that
  writes elsewhere (the vault) records what it wrote in a JSON artifact (Phase 09's `write` stage).
- **Write artifacts atomically** (`ctx.write_json`, `vault.io.atomic_write_text`, or write a temp file
  and `os.replace`), so a crash never leaves a half-written checkpoint.
- **Lazy-import ML libraries inside `run`**, never at module import.
- **Cancellation is cooperative.** Call `ctx.check_cancelled()` at least every few seconds of work
  (between chunks or batches where the library allows).
- **Retries:** after `run` raises, the runner calls `should_retry(ctx, exc)` with `ctx.attempt`. Return
  True to run again (for example after CUDA OOM: lower `ctx.options["batch_size"]`, retry once). Return
  False to fail the job with the exception's `MM3Error` code (or `E_STAGE_FAILED`). An `MM3Error`'s
  optional `details` dict is stored with the stage's error (`detail.error.details`), e.g. the
  transcription stages' `{"suggested_overrides": {"transcription_model": "medium"}}` after a second
  out-of-memory error.
- **Human input:** raise `InputRequired(kind, payload)`. The stage becomes `waiting`, the job
  `waiting_for_input`, and the GPU slot is released. `POST /api/jobs/{id}/input` validates the answer
  with the stage's optional `validate_input(data)`, saves it as `input.<stage>.json` and queues the job;
  the stage runs again and finds the answer with `ctx.input()`. `AwaitInputStage` packages this
  pattern; `SpeakerConfirmationStage` is the `await_speaker_confirmation` stage.

## Adding a stage
1. Implement the stage (see above) in its own package, e.g. `transcription/stages.py`.
2. Register it, typically from that package's setup code: `jobs.pipeline.register_stage("generate",
   lambda settings: GenerateStage(settings))`. Until a stage is registered, `UnavailableStage`
   stands in and fails with `E_STAGE_UNAVAILABLE` and an install hint. (`transcribe`, `align` and
   `diarize` are built in: `transcription.stages.build_stage` returns the WhisperX stage when the `ml`
   extra is installed, otherwise an `UnavailableStage` saying "Transcription engine not installed".)
3. Use the canonical name from `jobs.pipeline.MEETING_STAGES`. Adding a **new** stage name to that list
   changes the stage list of new jobs only; older jobs whose stored stages differ fail resume with
   `E_PIPELINE_CHANGED`.
4. Test it with a `StageContext` built by hand (see `tests/unit/jobs/test_ingest.py`) and through the
   runner with a custom pipeline factory (`tests/unit/jobs/helpers.py`).

## Canonical pipeline and checkpoint artifacts
| # | Stage | GPU | Artifact (in `<data>/jobs/<id>/`) | Implemented in |
|---|---|---|---|---|
| 1 | `ingest` | no | `audio.wav` (16 kHz mono PCM) | Phase 04 |
| 2 | `transcribe` | yes | `transcript.json` | Phase 06 |
| 3 | `align` | yes | `aligned.json` | Phase 06 |
| 4 | `diarize` | yes | `transcript.final.json` (a serialised `domain.Transcript`; `diarization.json` alongside) | Phase 06 |
| 5 | `speaker_suggest` | yes | `speakers.json` | Phase 07 |
| 6 | `await_speaker_confirmation` | no | `input.await_speaker_confirmation.json` (the user's mapping) | Phase 04, extended in 07 |
| 7 | `generate` | no* | `notes.draft.md` | Phase 09 |
| 8 | `write` | no | a JSON record of the vault files written | Phase 09 |

\* Phase 09 should mark `generate` as a GPU stage when the backend is a local Ollama on the same GPU.

### Transcription stages (Phase 06)
Implemented in `transcription/stages.py` (user guide: [`../user-guide/transcription.md`](../user-guide/transcription.md);
ADR-0014). Each stage loads its own model through `transcription.engine.Engine` and frees it before
returning (`del`, `gc.collect()`, `torch.cuda.empty_cache()`), so after `diarize` nothing is left on
the GPU.

| Artifact | Content |
|---|---|
| `transcript.json` | `language`, `language_detected`, `language_probability`, `model`, `compute_type`, `batch_size`, `device`, `duration`, `segments` (`start`, `end`, `text`, `avg_logprob`) |
| `aligned.json` | the same, plus `aligned` (bool) and per-segment `words` (`word`, `start`, `end`, `score`; NaN becomes `null`) |
| `diarization.json` | `status` (`ok`, `disabled`, `skipped`, `failed`, `empty`, `no_speech`), `model`, `turns` (`start`, `end`, `speaker`), `speakers` (seconds per label), and `error` (`code`, `message`, `hint`) on a fallback. No voice embeddings. |
| `transcript.final.json` | `domain.Transcript`. Segments are split where the word-level speaker changes (WhisperX segments are VAD chunks of up to 30 s); `diarized=false` and no labels when diarization did not run. |

Behaviour:
- **Options** (job option > setting > hardware recommendation): `transcription_model`, `compute_type`,
  `batch_size`, `language`, `on_non_english`, `diarize`, `min_speakers`, `max_speakers`. The job
  option `model` is the LLM model, not the transcription model.
- **Language gate:** after loading the model, `transcribe` detects the language from the first 30 s.
  For non-English audio with `on_non_english: ask` it raises `InputRequired("language", {detected,
  language_name, probability, choices: ["proceed", "abort"], message})`. Answer with
  `POST /api/jobs/{id}/input` `{"action": "proceed"}` (optionally `"language": "en"`) or
  `{"action": "abort"}` (the job becomes `cancelled` and the answer is forgotten, so resuming asks again).
  Policy `abort` fails with `E_NOT_ENGLISH`; `proceed` continues with a warning.
- **Out of memory:** any stage catches CUDA OOM (torch `OutOfMemoryError`, CTranslate2 messages) and raises
  `MM3Error("E_OOM")`; `should_retry` frees memory and retries once (`transcribe`: half the batch size,
  `int8_float16`). A second OOM fails `transcribe` with `E_OOM` and `details.suggested_overrides`;
  for "Retry with a smaller model" call `POST /api/jobs/{id}/resume` with
  `{"overrides": {"transcription_model": "medium"}}`. A second OOM in `align` or `diarize` falls back
  (no word timings / no speakers) with a warning instead.
- **Fallbacks** never fail the job: alignment unavailable keeps segment timestamps; no token (and no
  cached model), refused access, an error or `diarize: false` gives a non-diarized transcript with a
  warning.
- **VRAM handoff:** on CUDA, `transcribe` first calls `transcription.handoff.release_local_llm`, which
  asks the job's LLM backend to unload (`OllamaBackend.unload_all()`) only if it is an Ollama on this
  machine (`transcription.unload_ollama`).
- **Cancellation:** WhisperX and pyannote progress callbacks call `ctx.check_cancelled()`, so a cancel
  stops at the next chunk.
- **Network:** cached models load without contacting Hugging Face; library telemetry is forced off.

Other files in a job folder: `original.<ext>` (the upload; the extension comes from an allowlist,
otherwise `.bin`), `audio.opus` (after `written`), `input.<stage>.json` (answers).

**Resume (R4):** the runner restarts at the first stage that is not `completed` **or whose artifact
file is missing**, and resets that stage and every later one to `pending`. Completed stages before it
are never run again.

## GPU exclusivity (R5)
One `asyncio.Semaphore(1)` is shared by all jobs. A job acquires it before its first GPU stage and
keeps it across consecutive GPU stages (`transcribe → align → diarize → speaker_suggest`), so another
job can never load models in between and push an 8 GB card out of memory. It is released before the
next CPU stage, on pause, on failure and on cancel. CPU stages of other jobs run in parallel (up to
`jobs.max_concurrent` jobs in flight).

## Progress and SSE
`ProgressBus` is an in-process pub/sub. Every event goes through the event loop's FIFO queue, gets a
per-job sequence number (`seq`) and is fanned out to subscribers; the latest event per stage is kept
for replay.

`GET /api/jobs/{id}/events` sends:
1. `event: snapshot`: the full job (`GET /api/jobs/{id}` body), with `seq` = the last event included.
2. `event: stage`: `{job_id, stage, status, fraction, message, eta_seconds, kind: "stage", seq, data}`.
   `fraction` is 0 to 1 or `null` (indeterminate). `status` `pending` with message "Waiting for the
   GPU" means the job is queued behind another job's GPU work.
3. `event: job`: job status changes (`kind: "job"`); `data.error` carries `{code, message, hint}` on
   failure, `data.input` the question when waiting.
4. A `: heartbeat` comment every 15 s.

Events with `seq` ≤ the snapshot's `seq` are skipped, so a reconnecting client never sees duplicates.
The stream ends after a `written`, `failed` or `cancelled` job event (resuming a job needs a new
stream). ETA: `elapsed × (1 − f) / f`, shown once a stage has at least 2 % progress and 1 s elapsed.

## Audio ingest (R7)
- The upload is parsed as a stream (`python_multipart.MultipartParser`) and written straight to the job
  folder with mode `0600`, so audio never lands in `/tmp`. The size limit (`audio.max_upload_mb`,
  default 2048) is enforced while streaming and from `Content-Length` (HTTP 413, `E_UPLOAD_TOO_LARGE`).
- `ffprobe` must find an audio stream with a positive duration (`E_AUDIO_UNSUPPORTED`, HTTP 422),
  otherwise the job folder is removed and no job is created.
- The `ingest` stage converts to 16 kHz mono 16-bit WAV. ffmpeg and ffprobe run from an argument list
  (no shell), with `-nostdin`, `--` before the input path, a timeout (60 s for probing, duration +
  120 s for transcoding) and output written to a temporary `.part` file and renamed.
- Missing ffmpeg raises `E_FFMPEG_MISSING` with install commands.

## Retention (R8, ADR-0006, ADR-0013)
At `written`, the runner re-encodes the best audio file (WAV, else the upload) to mono Opus at
`audio.opus_bitrate_kbps` (24) and deletes the upload and the WAV. If the encode fails, the
uncompressed audio is kept and a warning is logged. `jobs.audio_expires_at` = `written_at` + the
retention period. The pruner (`jobs.retention.prune`) runs at startup, every
`jobs.prune_interval_hours` (24) and on `mm3 jobs prune [--dry-run]`:
- it applies the **current** `privacy.audio_retention` setting to every written job (so switching to
  `forever` keeps old audio), and updates the recorded expiry;
- unfinished jobs (failed, cancelled, interrupted, waiting) keep their audio until
  `audio_retention_days` after their last change, unless retention is `forever`;
- pinned jobs (`POST /api/jobs/{id}/pin`) and queued or running jobs are never pruned;
- only audio files are deleted; transcripts and other artifacts stay. The audio endpoint then
  answers `410 E_AUDIO_EXPIRED`.

`delete_after_write` prunes the job's audio as soon as it is written.

## API summary
| Method and path | Purpose |
|---|---|
| `POST /api/jobs` | multipart `file` + optional JSON `options` (`JobOptions`: `title`, `meeting_date`, `diarize`, `min_speakers`, `max_speakers`, `template`, `backend`, `model` (LLM), `cloud_consent`, `transcription_model`, `compute_type`, `batch_size`, `language`, `on_non_english`, plus any extra keys). Title and date are pre-filled from the filename. 201 + the job. |
| `GET /api/jobs?status=…&limit=&offset=` | List jobs, newest first. |
| `GET /api/jobs/{id}` | Job, stages (with live fraction, message, ETA, `detail.warnings`, `detail.error.details`), `waiting_for` and `warnings` (all stages' warnings). |
| `POST /api/jobs/{id}/cancel` | Cancel a queued, running, waiting or interrupted job. |
| `POST /api/jobs/{id}/resume` | Resume a failed, cancelled or interrupted job; body `{"overrides": {...}}` optional. |
| `POST /api/jobs/{id}/input` | Answer a waiting job, e.g. `{"speakers": {"SPEAKER_00": "Alice"}}` or, for the language question, `{"action": "proceed"}`. |
| `DELETE /api/jobs/{id}?force=` | Delete the job folder and rows (409 while active; pinned needs `force=true`). Vault notes are not touched. |
| `POST /api/jobs/{id}/pin`, `/unpin` | Keep the audio regardless of retention. |
| `GET /api/jobs/{id}/audio` | The best audio file, with HTTP Range (`audio/ogg` for Opus). |
| `GET /api/jobs/{id}/events` | SSE (above). |

All POST and DELETE routes need the CSRF header (S2). Errors use the standard
`{code, message, hint}` body.

## Fake pipeline
`MM3_FAKE_PIPELINE=1 uv run mm3 serve` replaces every ML and LLM stage with a fake from
`jobs/fakes.py` (the real ffmpeg `ingest` still runs). Each fake takes `MM3_FAKE_STAGE_SECONDS`
(default 2) and writes plausible artifacts, including a two-speaker transcript; `FakeWrite` never
touches the vault. Try it:
```bash
MM3_FAKE_PIPELINE=1 uv run mm3 serve &
curl -s -c /tmp/cj http://127.0.0.1:8765/ -o /dev/null
TOKEN=$(awk '/mm3_csrf/{print $7}' /tmp/cj)
ID=$(curl -s -b /tmp/cj -H "X-CSRF-Token: $TOKEN" -F "file=@meeting.m4a" \
     -F 'options={"title":"Demo"}' http://127.0.0.1:8765/api/jobs | jq -r .id)
curl -N http://127.0.0.1:8765/api/jobs/$ID/events      # streams until waiting_for_input
curl -s -b /tmp/cj -H "X-CSRF-Token: $TOKEN" -H 'Content-Type: application/json' \
     -d '{"speakers":{"SPEAKER_00":"Alice","SPEAKER_01":"Bob"}}' \
     http://127.0.0.1:8765/api/jobs/$ID/input        # the job finishes
```
