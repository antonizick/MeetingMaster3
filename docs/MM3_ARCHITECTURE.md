# Architecture

> **Status:** skeleton from Phase 01. Expanded by every phase that adds a component. The canonical
> design is [`MM3_SPECIFICATION.md`](MM3_SPECIFICATION.md) (section 15 amendments win over sections 1-14).

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
- Map-reduce note generation when the transcript exceeds about 70% of the context window (R6); a template
  with `params.detail: high` (Default Notes) gets richer, topic-labelled map notes (R29).
- Audio normalised to 16 kHz mono WAV, kept as Opus for 90 days by default (R7, R8).
- Strict section markers so regeneration never touches content outside them (R11).
- Security baseline S1-S8 applies to every component.

## Target layout
```
src/meetingmaster3/
  config/ domain/ markdown/ vault/ storage/ jobs/ audio/ hardware/
  transcription/ speakers/ llm/ templates/ feedback/ web/ starter_templates/
```
Full tree: `prompts/MM3_shared-instructions.md` section 2. ML imports are lazy, inside
`transcription/` and `speakers/` only.

## Deployment (Phase 14)
`docker/Dockerfile` builds `runtime-gpu` and `runtime-cpu` from the same locked environment; compose adds the
vault bind mount, the `/config`, `/data` and `/models` volumes, a GPU reservation and the loopback-only port.
The app reaches the host's Ollama by `host.docker.internal` or, with `compose.host-network.yaml`, by `127.0.0.1`.
See ADR-0026 and `docs/user-guide/install-docker.md`. Since Phase 15 the base is Debian 13 (`python:3.12-slim-trixie`)
without curl or system pip (ADR-0027).

## Security and performance (Phase 15)
The threat model, with trust boundaries and every mitigation mapped to code and a test, is
[`THREAT_MODEL.md`](THREAT_MODEL.md); the control → test table and scan results are in `SECURITY.md`. Vault YAML is
read through `markdown.frontmatter.load_untrusted` (capped alias expansion); media goes through `audio.ingest` with a
file-only protocol whitelist. Measured speed and memory on the 8 GB reference GPU: [`PERFORMANCE.md`](PERFORMANCE.md).

## Implemented so far (Phases 02 to 11)
| Module | Responsibility |
|---|---|
| `app.py` | `create_app(settings, paths)` factory. Middleware order (outermost first): TrustedHost, security headers, CSRF. The lifespan opens `mm3.db`, starts/stops the `JobRunner` and the `SearchService` (Phase 15i; its start-up scan runs in the background). |
| `cli.py` | Typer CLI `mm3`: `serve`, `version`, `doctor`, `process`, `config path`, `config show`, `llm list`, `llm test`, `jobs list`, `jobs prune [--dry-run]`, `models status`, `models download`, `voiceprints list|delete|wipe`, `templates list|validate|install`, `search "<text>"|index [--rebuild]|status` (Phase 15i). |
| `headless.py` | `mm3 process`: runs a `JobRunner` in its own event loop for one recording and answers its questions from arguments or the terminal. |
| `config/paths.py` | XDG directories with `MM3_*_DIR` overrides; created `0700`. |
| `config/settings.py` | Pydantic `Settings`. Precedence: defaults < `config.yaml` < `MM3_*` env. Atomic `0600` save. Secrets are `SecretStr`. |
| `errors.py` | `MM3Error(code, message, hint, details=)` and a JSON/HTML exception handler chosen by `Accept` (FastAPI imported lazily). |
| `domain/transcript.py` | `Word`, `Segment`, `Transcript`, `SpeakerMap` (stable `Speaker N` placeholders, `apply`), `Turn`/`group_turns`, `CompanionTranscript`. Immutable pydantic models. |
| `domain/meeting.py`, `domain/note.py` | `MeetingMeta` (frontmatter fields, normalised); `Note` = metadata + ordered `TextBlock`/`Section` blocks; marker grammar constants. |
| `domain/filenames.py` | `parse_filename`: date, time and title from recorder file names. |
| `markdown/sections.py` | Strict marker scanner (`scan_sections`, `MarkerError`), `replace_section`, `append_section`, `list_sections`; byte-preserving. |
| `markdown/frontmatter.py` | Frontmatter split/parse; per-key raw chunks; MM3-style emitter with verified fallbacks. |
| `markdown/note_parser.py`, `note_writer.py` | `parse_note` → `ParsedNote`; `build_note`, `render_note(note, base=)` (reuses unchanged bytes). |
| `markdown/transcript_format.py` | Companion transcript render/parse, hidden JSON-lines data block, `rename_speakers`. |
| `markdown/readable_transcript.py` | The readable transcript `<note> (Transcript).md` (Phase 15a, R25): colour-highlighted speakers in the review screen's palette, 90 s paragraphs, `neutralise` for spoken text. Writer only; never parsed back. |
| `markdown/diff.py` | `unified_diff`, `side_by_side` rows, `diff_stats` (stdlib difflib). |
| `vault/naming.py`, `paths.py`, `io.py`, `archive.py` | R13 names and collisions; vault root checks and confinement; atomic non-clobbering writes and exact reads; R12 archives. |
| `storage/db.py`, `migrations.py`, `repositories.py` | One shared WAL SQLite connection; forward-only numbered migrations (`schema_version`); `JobRepository` (enforces the job state machine), `StageRepository`, `RecentMeetingsRepository`. See [`dev-guide/storage.md`](dev-guide/storage.md). |
| `audio/ingest.py`, `audio/stage.py` | Streamed upload save with size limit, ffprobe validation, 16 kHz mono WAV normalisation, Opus re-encode; the `ingest` stage. |
| `jobs/models.py`, `stage.py`, `pipeline.py` | Job/stage states and transitions, `JobOptions`, `ProgressEvent`; the `Stage` protocol, `StageContext`, `InputRequired`; the canonical meeting pipeline and `register_stage`. |
| `jobs/runner.py`, `progress.py`, `retention.py`, `files.py`, `fakes.py` | `JobRunner` (dispatcher, GPU semaphore, resume, cancel, input pauses, retry hooks); `ProgressBus` with ETA; R8 retention and pruning; job folders and path confinement; fake stages (`MM3_FAKE_PIPELINE=1`). |
| `web/api/jobs.py` | `/api/jobs` routes: streamed multipart upload, list, get, cancel, resume, input, delete, pin/unpin, audio (HTTP Range; `?download=1` for an attachment), SSE events. |
| `web/api/speakers.py` | `GET/POST /api/jobs/{id}/speakers` (confirmation), `/api/voiceprints` (list, delete one, two-step wipe). |
| `speakers/embeddings.py` | Overlap-free segment selection, snippets, `SpeakerProfile`, `PyannoteEmbedder` (WeSpeaker from the cached diarization snapshot; lazy imports). |
| `speakers/match.py`, `vectors.py` | Max-cosine scoring, Hungarian one-to-one assignment, threshold and margin; pure-Python vector helpers and float32 BLOBs. |
| `speakers/store.py` | `VoiceprintStore` over migration 2 (opt-in writes, model-id isolation, cap, physical delete, wipe tokens). |
| `speakers/stages.py`, `cascade.py` | `speaker_suggest` and `await_speaker_confirmation` stages (enrollment, merges); one `SpeakerMap` per job applied to transcript, note metadata and companion transcript. |
| `logging.py` | Logging setup: secret redaction, then a bounded queue and writer thread so a stalled terminal can never block the event loop (ADR-0046). |
| `web/security.py` | Security-headers and CSRF middleware. |
| `hardware/detect.py` | `HardwareInfo`: nvidia-smi, then torch.cuda (only if importable), then CPU/RAM from `/proc`. Cached; `get_hardware(refresh=True)` re-detects. |
| `hardware/profiles.py` | `cpu`, `vram8`, `vram16`, `vram24plus`, chosen from total VRAM or `hardware.profile`. |
| `hardware/recommend.py` + `recommendations.yaml` | Per-profile transcription and local-LLM recommendations, ETA estimates and risk warnings. All numbers are data, tagged estimated or measured. |
| `hardware/doctor.py` | Environment checks for `mm3 doctor` (ffmpeg, Python, transcription engine, cached models, HF token, Ollama, vault, data dirs). |
| `transcription/stages.py` | The `transcribe`, `align` and `diarize` stages (Phase 06): plan resolution, language gate, one-shot OOM retry, fallbacks, per-stage model release. |
| `transcription/engine.py` | `Engine` protocol and `WhisperXEngine` (lazy whisperx/torch/pyannote imports; library logging and warnings quieted before import). |
| `transcription/models.py` | Model cache (`MM3_MODELS_DIR` = `HF_HOME`), model ids, cache checks, downloads, HF token, telemetry off, OOM detection, `free_gpu_memory`. |
| `transcription/convert.py`, `handoff.py` | WhisperX results to `domain.Transcript` (with speaker-change splitting); the R5 Ollama unload before transcription. |
| `web/hardware.py` | `GET /api/hardware`, `POST /api/hardware/refresh`. |
| `web/routes.py` | `GET /healthz`, `GET /` (Jinja2 base layout, placeholder page). |
| `llm/base.py` | `LLMBackend` protocol, request/result types, error codes (`E_LLM_*`), `is_local_url`. |
| `llm/ollama.py`, `openai_compat.py`, `bedrock.py` | The three adapters (Phase 08). Bedrock is lazy-imported; sync boto3 calls run in threads. |
| `llm/_http.py` | Shared httpx send with bounded jittered retries (429/5xx) and error normalisation. |
| `llm/registry.py` | Kind to factory map and `BackendRegistry` (config to cached backend instances). |
| `llm/budget.py`, `llm/consent.py` | 70% context budgeting and speaker-turn chunking; cloud-egress consent check. |
| `llm/recommendations.py` + `cloud_recommendations.yaml` | Local (Phase 05) plus cloud suggestions, and the dated measured Best value / Best quality picks and the models known to be unsuitable (Phase 15h, ADR-0042). |
| `llm/pricing.py`, `llm/cost.py`, `templates/picker.py` | Model prices (live OpenRouter, dated Bedrock table in `bedrock_models.yaml`), the per-meeting cost estimate from measured token rates, and the grouped picker data shared by New meeting, Settings and the review page. The capable-model filter is `templates/model_check.py:assess`. |
| `web/llm.py` | `/api/llm/*` routes (masked config, test, models, recommendations). |
| `llm/fake.py` | `FakeLLMBackend`: deterministic, offline (tests and `MM3_FAKE_PIPELINE`). |
| `templates/schema.py`, `loader.py` | Template file parser with line-numbered validation; library of built-ins (`starter_templates/*.md`) and vault templates (override by id); non-clobbering install with a hash manifest. |
| `templates/assembler.py`, `cues.py` | Prompt assembly (global rules, template, meeting facts, `[mm:ss] Name: text` transcript); tagged task candidates and the owner guard. |
| `templates/generator.py`, `mapreduce.py`, `postprocess.py` | `NoteGenerator` (consent, fit check, per-section calls, map-reduce, checkpoints, `regenerate_section`); chunk extraction, JSON repair, merge; output clean-up and deadline dates. |
| `templates/model_check.py` | Whether a model can write notes (embedding-only, or too little context), checked when a job is submitted, the model the UI suggests, and the models offered by **Try another model** on a failed job (ADR-0029). |
| `templates/stages.py`, `regenerate.py` | The `generate` and `write` stages; preview of one section's regeneration for a vault note. |
| `web/api/templates.py` | `GET /api/templates`, `POST /api/templates/install`, `POST /api/jobs/{id}/generate`, `POST /api/notes/regenerate-section`. |
| `markdown/editing.py` | Split a note into editable parts (frontmatter, user text around sections, section contents) and join edited parts back with the original marker lines and line endings (ADR-0024). |
| `vault/picker.py` | Vault browser for re-opening notes (folders and `mm3-id` notes only, archives and transcripts skipped, confined); `find_companions` searches the vault for a moved transcript. `read_identity` classifies a file (`is_note`, `is_transcript`, `is_readable` by `mm3-kind`). |
| `vault/relink.py` | Re-link Meetings entries whose notes moved (ADR-0047): `index_vault` reads note identity across the vault, `find_match` matches an entry by `mm3-id` (file name breaks ties), `plan_relink` / `apply_clear_matches`; `RecentMeetingsRepository.relink` updates or merges the entry. Used by the Meetings page (`/ui/recent/relink*`) and `mm3 notes relink`. |
| `vault/readable.py` | Write/refresh the readable transcript next to a note; never replaces a file that is not this meeting's (`(Transcript 2)`…); `refresh_readable` after a rename or link-transcript (Phase 15a). |
| `review/retention_view.py` | The review screen's recording line ("deleted in 23 days", "kept forever") built from `jobs.retention.audio_retention_status`, the rule the pruner uses (Phase 15b, R26). |
| `review/progress.py` | Long review actions (switch, regenerate) as in-memory background tasks: `LongTask`, `TaskRegistry` (one running per note, cancel, prune), the time-left model (`eta`, `smooth_total`) (Phase 15c, R27, ADR-0038). |
| `review/store.py` | Per-meeting working files in app data: base snapshots by SHA-256, the autosaved draft, a pending template switch. |
| `review/workspace.py` | Locate a note by `mm3-id` (Meetings list or a vault path), load it with its companion transcript, job and audio state; transcript view model; degradation modes. |
| `review/retitle.py`, `vault/links.py` | Rename and re-date a meeting (Phase 15d, R28, ADR-0040): `plan_retitle` (pure: every file rename/move, in-file change, backlink, warning and refusal), `apply_retitle` (journal + backups in `<data>/rename-backups/`, new names, DB + `written.json` commit point, old names removed), `recover_renames` (at start-up and before each CLI rename). `vault/links.py` finds and rewrites wikilinks and Markdown links to renamed files the way Obsidian resolves them. Used by "Title & date…" (`web/review.py`, `static/js/retitle.js`) and `mm3 meetings rename`. |
| `review/upgrade.py` | "Update older notes" (Phase 15a): dry-run planner per note, applier (generate missing summaries with `NoteGenerator.write_sections`, `sections.insert_section`, `rename_heading`, readable transcript, archive, SHA + `mm3-id` re-check, atomic write), model choice, the background `UpgradeRun`. Used by `web/upgrade_ui.py` (card on Recent) and `mm3 notes upgrade`. |
| `review/save.py`, `rename.py`, `switch.py` | Save with the hash check and conflict (ADR-0025); speaker renaming through the Phase 07 cascade; whole-note template switch with "Preserved notes". |
| `web/review.py` | `/open` (redirects to Meetings), `/open/note`, `/ui/open/browse`, `/meetings/{mm3_id}` and the workspace's JSON actions under `/ui/review/{mm3_id}/` (including `keep`, the per-meeting Keep forever pin, and `task/…`, the polled switch/regenerate tasks). `web/paging.py` pages the Meetings sections. The note opens server-rendered in Preview. |
| `config/editing.py` | UI settings edits: validate a dotted-path patch per section, apply it only if all of it is valid, write `config.yaml` (Phase 12). |
| `web/settings_ui.py`, `settings_fields.py`, `model_downloads.py` | The tabbed Settings screen (`/settings/<tab>`): declarative field list and form parsing, write-only secrets, backend add/edit/test, retention preview, voiceprint management with the two-step wipe, diagnostics, background model downloads. `transcription/hf_check.py` tests the Hugging Face token. |
| `templates/manage.py`, `web/templates_ui.py` | Template library management (favourite = one frontmatter line, duplicate, create, validated save, delete with archive, reset built-in); the `/templates` screens. |
| `feedback/store.py`, `context.py`, `web/api/feedback.py`, `web/feedback_ui.py` | Local ratings (migration 3, table `feedback`), the CSV/JSON export, and the rating widget (`partials/feedback.html`, embedded with the `fb` variable from `feedback_context`). |
| `exporting.py`, `web/api/export.py` | Meeting export (note, transcript, plain text, zip with audio) and "export all app data" (no secrets, audio or voiceprints). |
| `jobs/vault_audio.py` | The optional copy of the retained audio into the vault with an `mm3-audio` link (R8), run by the runner after a job is written. |

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

### Transcription (Phase 06)
```
audio.wav ─▶ transcribe: [Ollama unload] → faster-whisper (VAD chunks, language check) ─▶ transcript.json
          ─▶ align:      wav2vec2 word timings (fallback: segment timings)      ─▶ aligned.json
          ─▶ diarize:    pyannote community-1 → speakers per word → split turns  ─▶ transcript.final.json
                         (fallback: no speakers + warning)                         + diarization.json
each stage: load model ─▶ work (progress callbacks check cancel) ─▶ del + empty_cache
CUDA OOM ─▶ E_OOM ─▶ should_retry (once: batch/2, int8_float16) ─▶ then fail with a smaller-model hint
```
The GPU semaphore is held from `transcribe` through `speaker_suggest`; models are not shared between
stages (ADR-0014). Details: [`dev-guide/jobs-and-stages.md`](dev-guide/jobs-and-stages.md).

### Speakers (Phase 07)
```
transcript.final.json + diarization.json
  ─▶ speaker_suggest: per label: talk time, overlap-free speech, ≤3 snippets
        [privacy.voiceprints_enabled] windows (2-10 s, ≤45 s) ─▶ WeSpeaker ─▶ centroid
                                       ─▶ VoiceprintStore.known_people(model_id) ─▶ max cosine
                                       ─▶ Hungarian + threshold + margin ─▶ candidates
  ─▶ speakers.json (+ speaker_embeddings.json, voiceprints on)   ─▶ waiting_for_input
GET/POST /api/jobs/{id}/speakers ─▶ await_speaker_confirmation:
        enroll (merge labels per person) ─▶ voiceprints, voiceprint_embeddings (mm3.db)
        SpeakerMap ─▶ speaker_map.json, transcript.named.json ─▶ speakers.confirmed.json
        delete speaker_embeddings.json
speakers.cascade.apply_speaker_map ─▶ named transcript (Phase 09 context), note meta
        (participants, mm3-speakers), companion transcript; Phase 11 renames through it
```
Voiceprint vectors stay inside `VoiceprintStore` and the job folder until confirmation; ADR-0015.

_To be expanded in Phases 09-15 (generation and UI data flow, sequence diagrams)._

### Note generation (Phase 09)
```
transcript.named.json + template (vault override > built-in) + MeetingMeta (job options, speaker map)
  ─▶ generate: [cloud backend?] consent ─▶ InputRequired("cloud_consent") until answered (S6)
       NoteGenerator.prepare:
         system = global rules + template _system + meeting facts + today
         fits 70% of min(model window, generation.max_context)?
           yes ─▶ context = "[mm:ss] Name: text" transcript
           no  ─▶ map: chunk on speaker turns ─▶ JSON extraction per chunk (repair, 1 retry)
                  merge + dedupe ─▶ context = merged notes                       (ADR-0016)
         num_ctx = largest real call (map prompt + output + repair, or section
                   prompt + output + retry) × 1.1, reduce notes cut to fit       (ADR-0043)
       per section (same system + context prefix, one num_ctx):
         tail = section prompt [+ tagged task candidates] [+ instructions / previous + feedback]
         LLM (temperature by kind, think off) ─▶ clean-up ─▶ due dates ─▶ owner guard (ADR-0017)
         ─▶ generate.partial.json (resume point)
       ─▶ notes.draft.md (build_note + render_note), generation.json
  ─▶ write: allocate stem (write.intent.json) ─▶ companion .transcript.md ─▶ note .md (atomic, vault-confined)
       ─▶ recent_meetings ─▶ written.json                                         (ADR-0018)
```
The built-in library has 23 templates (`starter_templates/`; the default is `default-notes`, R29; list in
[`user-guide/template-catalogue.md`](user-guide/template-catalogue.md), generated by
`scripts/gen_template_catalogue.py`). The template format is normative in [`dev-guide/template-format.md`](dev-guide/template-format.md);
stage details in [`dev-guide/jobs-and-stages.md`](dev-guide/jobs-and-stages.md).

### Web UI (Phase 10)
```
browser ── GET pages (Jinja, server-rendered) ──────────────▶ web/pages.py ─▶ views.py (view models)
   │                                                                │
   ├─ HTMX: partials (hardware panel, vault check, job panel) ◀────┤  /ui/* actions call JobRunner directly
   ├─ EventSource /api/jobs/{id}/events ─ "something changed" ─▶ re-fetch /ui/jobs/{id}/panel
   ├─ XHR multipart ─▶ /api/jobs (upload, progress bar)           └─ /preview ─▶ render.py (markdown-it, no raw HTML)
   └─ Alpine (CSP build): upload form state, consent dialog, speaker samples; app.js holds all script
```
The page is always rendered from `JobRunner.describe`, so a reload or reconnect shows the true state;
SSE only decides *when* to re-render. Pages: `/setup`, `/` (new meeting), `/jobs/{id}`,
`/jobs/{id}/speakers`, `/meetings` (paged; `/open` redirects to it), `/preview`, `/templates`, `/settings` (read-only until Phase 12).
Decision record: ADR-0019.

### Review workspace (Phase 11)
```
/meetings ── jobs, notes, picker (vault/picker.py) ──▶ /open/note?path= ──▶ /meetings/{mm3_id}?path=
                                                                       │ review/workspace.py: note, companion,
                                                                       │ job + audio; base snapshot (review/store.py)
browser: transcript.js (player, binary-search sync, search, splitter, shortcuts)
         review.js (parts editor, autosave draft, save/conflict, preview, dialogs)
   │  JSON to /ui/review/{mm3_id}/...  (path + base SHA in every call; CSRF header)
   ├─ draft · render · save ───────────────▶ markdown/editing.py join ─▶ review/save.py (hash check, atomic write)
   ├─ regenerate ─▶ templates/regenerate.regenerate_text (editor's copy) ─▶ diff partial + new section text
   ├─ archive-section ─▶ vault/archive.archive_section (R12)      append-section ─▶ sections.append_section (R11)
   ├─ switch/preview|apply ─▶ review/switch.py (NoteGenerator) ─▶ archive_note + write
   ├─ speakers/preview|apply ─▶ review/rename.py (speakers.cascade) ─▶ companion + note + job speaker map
   ├─ retitle/preview|apply ─▶ review/retitle.py plan (vault/links.py backlinks) ─▶ journal + backups in
   │                           <data>/rename-backups/ ─▶ new names ─▶ DB commit point ─▶ old names removed
   └─ locate · link-transcript · reprocess (note-only mode)
```
The editor never sends marker lines; the server re-inserts them from the base, and unchanged parts keep their
exact bytes. `/preview` remains the read-only view for files that are not MM3 notes. Decision records: ADR-0024
(editor), ADR-0025 (save model). Pages added: `/open`, `/meetings/{mm3_id}`.

### Meeting index and search (Phase 15i)
```
vault ──(walk, mtime/size, sha256)──▶ search/index.py Indexer ──▶ search/chunking.py (sections; transcript windows)
  ▲  vault/changes.py hook                     │ passages                    │
  │  (atomic_write_text, rename)               ▼                             ▼
writers ──────────────────────▶ SearchService ─▶ search/store.py  <data>/search.db (0600, own schema version)
  start-up · every 10 min · Settings buttons    documents · passages · passages_fts (FTS5: body, head) · vectors
  · stale check on search · mm3 search index           ▲                                ▲
                                                        │ BM25 (head weight 0.3)        │ cosine (brute force)
                        /search · mm3 search · 15j ─▶ search/query.py Searcher ─ RRF (k = 60) ─▶ SearchResult
                                                        │                                │ group_by_meeting,
                         embedder.py ── backend.embed() (Ollama /api/embed; Bedrock Titan/Cohere; /embeddings)
                         GPU gate: JobRunner.background_gpu (only while no job is active) · cloud consent check
```
- **Store** (`search/store.py`): a separate, rebuildable SQLite file next to `mm3.db`, never migrated: a different
  schema version is dropped and rebuilt. Vectors are float32 blobs tagged with the embedding model id
  (`<kind>:<model>`); a different model empties the table first, so vectors are never mixed (ADR-0050).
- **Indexer** (`search/index.py`): incremental. Unchanged files cost one `lstat`; a file whose sha256 matches a
  vanished document with the same `mm3-id` and kind is re-pointed (a move keeps its vectors); a re-chunked document
  keeps the vectors of passages whose text is unchanged. `indexable()` is the one place that decides what is
  indexed (live notes and companion transcripts). Embedding runs in batches of 32 behind a `GpuGate`.
- **Query** (`search/query.py`): `fts_query` quotes every token of the user text (no FTS syntax survives); word
  candidates within 30 % of the best BM25, vector candidates within 0.08 cosine of the best (tuned on the corpus and
  Nick's vault), fused by reciprocal rank. Results carry snippets as (text, matched) pieces for safe rendering.
- **Service** (`search/service.py`): one per process (`app.state.search`); debounced updates (2 s) after vault
  writes, a periodic rescan, one update at a time as a `LongTask` (progress, cancel); `JobsTableGate` gives the CLI
  the same GPU rule by reading `mm3.db`.
- **Pages:** `/search` (`web/search_ui.py`), Settings → Search & Ask (`web/settings_ui.py`, `/settings/search/*`).
  Decision records: ADR-0049, ADR-0050.

