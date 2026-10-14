# MeetingMaster3 – Product Specification

Version 1.1 · 2026-10-11 (the v1.0 PrePlan plus the §15 amendments)
Status: Implementation-ready specification. **This is the canonical spec for the build.**

> **How to read this document.** Sections 1–14 are the original PrePlan v1.0 (reformatted only).
> **§15 Amendments** records decisions and refinements made during planning; **where §15 conflicts
> with §1–14, §15 wins.** Appendix A is the full template catalogue and Appendix B the common note
> header, both from the design pre-notes. Change this document only through §15 (add an amendment)
> and record the decision in `docs/DECISIONS.md`.

### 1. Product Vision, Goals, and Non-Goals

Vision  
MeetingMaster3 is a free, open-source, self-hostable AI meeting intelligence platform that transforms raw meeting audio into polished, professional Markdown notes the way a skilled secretary or chief of staff would. It produces accurate speaker-attributed transcripts, then generates structured executive summaries, technical deep-dives, decision logs, action-item lists with owners and deadlines, open questions, next steps, and AI recommendations. Output is Markdown-first and Obsidian-native. Data remains under full user ownership and leaves the machine only when the user explicitly chooses a cloud backend.

Goals (MVP)

- Deliver secretary-grade structured notes from uploaded audio with minimal friction.
- Support fully local processing (preferred) while allowing selective BYOK cloud backends.
- Integrate bidirectionally with an Obsidian vault so notes remain first-class Markdown files.
- Be hardware-aware and practical on 8 GB VRAM machines.
- Remain simple to extend (templates and backends).
- Preserve privacy as a first-class quality attribute.

Non-Goals (MVP)

- Multi-user, team sharing, or concurrent editing.
- Live meeting capture or calendar integration.
- Non-English language support.
- Full bidirectional sync conflict resolution beyond explicit regeneration with diffs.
- Mobile apps or Windows-first packaging.
- Automatic vault scanning or proactive processing.
- Complex plugin marketplace or dynamic backend loading at runtime.

### 2. Target Users and Primary Jobs-to-be-Done

Primary user  
Privacy-conscious individual professional (knowledge worker, engineer, founder, researcher) who already uses or is willing to use Obsidian, values data ownership, and processes their own meetings. Hardware ranges from modest (8 GB VRAM) to high-end local GPUs; CPU-only is supported but secondary.

Primary jobs-to-be-done

1. Upload a meeting recording and receive a clean, named-speaker transcript plus structured professional notes.
2. Quickly review, edit, and selectively regenerate sections while preserving personal edits.
3. Have the final notes and transcript live as native Markdown files inside a chosen Obsidian vault folder.
4. Re-open prior meetings later to regenerate sections or apply a different template without losing the original transcript.
5. Run everything locally by default, with optional high-quality cloud models when desired.

### 3. Detailed Feature Specifications and User Flows

Core user flow (happy path)

1. User opens local web UI → selects or confirms vault path and output subfolder (e.g., `Meetings/2026/`).
2. Uploads audio file (MP3, WAV, M4A, etc.). Optional thin filename parser pre-fills title/date.
3. System shows hardware profile + recommended transcription settings; user accepts or overrides.
4. Job starts: progress bar with stages (Transcribing → Aligning → Diarizing → Speaker suggestions → Generating notes → Writing).
5. Name Speakers UI appears with auto-suggestions from voiceprint store; user confirms/renames. Mapping cascades.
6. Side-by-side view: audio player + timestamped transcript | editable structured Markdown.
7. User reviews, edits, regenerates individual sections (diff shown; option to archive prior draft).
8. User chooses template (or keeps default) and clicks Write to Vault. Main note + companion transcript written; links created.
9. Optional: rate note or sections for future improvement.

Key supporting features

- Explicit re-open of existing notes (file picker or recent list).
- Partial regeneration with unified/side-by-side diff and archive option.
- Template library: favorite, edit, duplicate, create.
- Lightweight feedback (thumbs / 1–5 + optional comment) stored locally.
- Job controls: cancel, resume (where checkpointed), OOM retry with smaller-model suggestion.

Edge cases and error states

- Non-English audio detected → clear warning, proceed with English models or abort.
- OOM during transcription → automatic one-time retry with reduced batch/compute type or smaller model; then user prompt.
- Vault path unwritable or missing → blocking error with remediation steps.
- User edits outside marked sections → preserved; system only rewrites marked sections on regeneration.
- Very long audio (>2–3 h) on low hardware → progress estimates + option to process in segments (future).
- Missing companion transcript on re-open → graceful degradation (regeneration limited or prompt to re-transcribe).

### 4. System Architecture and Major Components

High-level architecture (single-user, local web)

- Frontend: Local web UI (recommended: modern lightweight SPA or server-rendered with HTMX/Alpine for simplicity). Communicates with backend via REST + WebSocket/SSE for progress.
- Backend: Python (FastAPI preferred). Orchestrates jobs, file I/O, template rendering, LLM calls.
- Transcription engine: WhisperX (faster-whisper + wav2vec2 alignment + pyannote diarization).
- LLM layer: Backend abstraction (Ollama, AWS Bedrock, OpenRouter).
- Storage: Markdown files in user vault (source of truth). Local app data directory for config, voiceprint store, job state, feedback.
- Job runner: Background tasks with progress reporting and checkpointing (Celery optional; simple asyncio/thread pool sufficient for MVP).

Major components

1. Upload & job orchestration service.
2. Transcription + diarization pipeline.
3. Speaker mapping & voiceprint store.
4. Template engine & prompt assembler.
5. LLM backend abstraction + model recommender.
6. Markdown writer / parser (round-trip).
7. Settings & config manager.
8. Feedback collector.

### 5. Data Model and Markdown/YAML Conventions

File naming

- Main: `YYYY-MM-DD - Meeting Title.md`
- Companion: `YYYY-MM-DD - Meeting Title.transcript.md`

Main note YAML frontmatter (stable minimal set)

```yaml
---
title: Product Sync
date: 2026-10-11T14:00:00
participants: [Alice, Bob, Charlie]
tags: [meeting, product]
location: Zoom
mm3-version: 1
mm3-template: executive-summary
mm3-transcript: "[[2026-10-11 - Product Sync.transcript]]"
mm3-speakers:
  SPEAKER_00: Alice
  SPEAKER_01: Bob
---
```

Section markers (machine-readable, human-invisible)

```markdown
<!-- mm3:section:summary -->
## Summary
...
<!-- /mm3:section:summary -->
```

Companion transcript contains full timestamped diarized output + speaker map in its YAML.

Archive convention  
Prior drafts saved as `YYYY-MM-DD - Meeting Title.section.archive-YYYYMMDD-HHMM.md` or in an `Archive/` subfolder.

### 6. Template System Design

Templates live inside the vault at a user-configurable path (default `MeetingMaster3/templates/`).

Each template is a Markdown file with YAML frontmatter defining metadata and section list, plus body containing `<!-- mm3:prompt:section-id -->` blocks that supply LLM instructions and structural examples.

Starter templates (shipped and copied on first run):

- Executive Summary
- Technical Deep-Dive
- Decision Log
- Action-Focused
- Just the Facts

Users can favorite, edit in Obsidian or in-app, duplicate, and create new ones. Engine assembles prompts from the template + transcript + speaker map + any user instructions.

### 7. Transcription and Diarization Approach

Default pipeline: WhisperX.

- Transcription: faster-whisper (user-selectable model: large-v3, large-v3-turbo, medium, etc.).
- Alignment: wav2vec2 for word-level timestamps.
- Diarization: pyannote (requires one-time Hugging Face token + model acceptance; thereafter fully local).

Speaker persistence: Local voiceprint store (embeddings extracted via pyannote). On new meetings, suggest matches above similarity threshold; user always confirms. Store lives in app data directory (not vault).

Quality considerations: Clear UI warnings for expected accuracy/speed trade-offs. Support for min/max speakers hints. Fallback to non-diarized transcription if pyannote fails or user prefers.

Hardware recommendation table (presented in UI):

|Profile|Recommended Model|Diarization|Approx. RTF|Notes|
|---|---|---|---|---|
|8 GB VRAM|large-v3-turbo or medium|Yes (low batch)|15–30×|Balance; fallback on OOM|
|16 GB VRAM|large-v3|Yes|30–50×|Comfortable|
|24 GB+|large-v3|Yes (high batch)|40–70×|Best quality/speed|
|CPU-only|small/medium (int8)|Optional|0.5–2×|Slow but functional|

### 8. LLM Backend Abstraction, Model Recommendation, and Prompting

MVP backends: Ollama (local, preferred), AWS Bedrock, OpenRouter (highly desired, OpenAI-compatible).

Thin abstraction layer: each backend implements a common interface (`generate(prompt, model, params)`). Config stores endpoint, API key (if any), and default model per backend.

Prompting strategy: Template-driven. System assembles context (transcript excerpt or full, speaker map, section-specific instructions, prior content if regenerating). Temperature and other params exposed per template or globally. AI Recommendations always generated into the dedicated bottom section.

Model recommendations: Separate from transcription; UI suggests local Ollama models by size/quality or cloud models by capability, with clear cost/privacy notes.

### 9. Obsidian Vault Integration Details

- User specifies vault root and output subfolder.
- System creates folders as needed.
- Writes main note + companion transcript; inserts wiki-style link in YAML and optionally in body.
- Re-open: user selects file → parser extracts sections via markers → loads companion transcript → enables side-by-side and regeneration.
- All content remains plain Markdown; no proprietary lock-in.

### 10. Hardware Awareness and Performance Expectations

System detects GPU/VRAM (or accepts user declaration) on startup or job start. Presents recommendations and warns on risky combinations. Job progress includes stage and rough ETA. OOM recovery path documented and implemented. Expectations set clearly in UI: “On 8 GB VRAM a 60-minute meeting may take 2–5 minutes with recommended settings.”

### 11. Deployment Options

Primary: Docker Compose (Linux).

- Multi-stage Dockerfile (Python slim base, pinned dependencies).
- Volumes: vault mount, config/app-data mount, model cache mount.
- Anti-bloat: no models baked in, explicit prune guidance, `.dockerignore`, multi-stage builds.
- Documented single-container alternative.

Windows packaging: nice-to-have (future).

Config file (YAML) lives in app data volume; UI provides “Open config file” / path reveal.

### 12. Extensibility Points and Future Roadmap

Extensibility (MVP-friendly)

- New templates: drop Markdown file in templates folder.
- New backends: implement interface + register in config (minimal code change).
- Section markers and YAML keys stable for future parsers.

Roadmap beyond MVP

- Multi-language support.
- Improved speaker re-identification and enrollment UI.
- Partial transcript editing and re-alignment.
- Optional Obsidian plugin for tighter integration.
- TIM-style feedback loop using collected ratings.
- Windows packaging and simple installer.
- Segmented processing for very long recordings.
- Additional backends (Anthropic, Google, etc.).

### 13. Risks, Open Questions, and Recommended Next Steps

Risks

- pyannote gating and model download friction.
- Round-trip parsing fragility if users heavily edit marked sections.
- Performance variability on diverse hardware.
- Voiceprint quality on noisy or short segments.

Open questions (minor)

- Exact frontend framework (recommendation below).
- Precise checkpointing strategy for resume.
- Default temperature and context-window handling per model size.

Recommended next steps

1. Scaffold Python FastAPI project + Docker Compose skeleton.
2. Implement WhisperX pipeline wrapper and basic job queue with progress.
3. Build Markdown parser/writer with section markers and companion file handling.
4. Create Name Speakers UI and voiceprint store prototype.
5. Implement one full template end-to-end and side-by-side review view.
6. Add settings page + config file round-trip.
7. Test on 8 GB and 16 GB profiles with real meeting audio.

### 14. Suggested Tech Stack and Rationale

- Core / Backend: Python 3.11+ with FastAPI. Excellent ecosystem for WhisperX, pyannote, and LLM clients; easy local development and Docker packaging.
- Transcription: WhisperX (wraps faster-whisper + pyannote). Current practical standard for local diarized transcripts.
- Frontend: Lightweight option preferred for MVP speed — either a simple React/Vue SPA or server-rendered templates with HTMX + Alpine.js. Avoid heavy frameworks initially.
- Config: Pydantic settings + YAML file.
- Job progress: FastAPI WebSocket or Server-Sent Events.
- Embeddings / voiceprints: pyannote.audio utilities already in the stack.
- Packaging: Docker multi-stage + docker-compose.

Assumptions flagged

- User has Docker and sufficient disk for model caches.
- Hugging Face token is acceptable for diarization models.
- Obsidian vault is locally accessible (or mounted) by the container.
- English-only is sufficient for first release.

### 15. Amendments (v1.1, 2026-10-11)

These amendments supersede conflicting text in §1–14. Each amendment that records a decision has an entry in `docs/DECISIONS.md`.

#### 15.1 Decisions confirmed by the project owner

| ID | Topic | Decision |
|---|---|---|
| A1 | License | **Apache-2.0** (explicit patent grant). Compatible with WhisperX (BSD-2), faster-whisper (MIT) and pyannote.audio (MIT). Model weights have their own terms; see `THIRD_PARTY_NOTICES.md`. |
| A2 | Frontend | **Server-rendered Jinja2 + HTMX + Alpine.js.** No Node build step. All JS/CSS (HTMX, Alpine, CodeMirror 6 bundle or equivalent, diff renderer) is **vendored** into `static/vendor/` with its version and license recorded. **No CDN loads at runtime**, so the app works offline and leaks nothing. |
| A3 | Templates | **22 templates, shipped in two stages** (23 and a new default since R29). Stage 1 (Phase 09): the 5 PrePlan starters (Executive Summary, Technical Deep-Dive, Decision Log, Action-Focused, Just the Facts). Stage 2 (Phase 13): the remaining 17 from Appendix A (Appendix A's "Executive Summary", "Decision Log" and "Action-Item / Task-Oriented" are already covered by stage 1). Default template: **Executive Summary**. |
| A4 | LLM backends (MVP) | **Ollama** (local, default), **AWS Bedrock** (Converse API), and a generic **OpenAI-compatible** adapter with an **OpenRouter preset**. The generic adapter also covers OpenAI, LM Studio, vLLM, llama.cpp server, etc. through a custom base URL. Native Anthropic and Google adapters go on the roadmap. |

#### 15.2 Technical refinements

- **R1 Python runtime.** Python **3.12** pinned, managed with **uv** (`.python-version`, `uv.lock`). The host system Python (3.14) is likely unsupported by the torch/WhisperX/pyannote stack. Phase 02 verifies this and records the result.
- **R2 Package and layout.** Import package `meetingmaster3`, `src/` layout, CLI entry point `mm3` (`mm3 serve`, `mm3 doctor`). Default port **8765**.
- **R3 App data locations (XDG).** Config: `$XDG_CONFIG_HOME/meetingmaster3/config.yaml` (default `~/.config/...`). Data: `$XDG_DATA_HOME/meetingmaster3/` holds `mm3.db` (SQLite: jobs, stage checkpoints, recent meetings, voiceprints, feedback), `jobs/<job-id>/` (audio and stage artifacts) and `logs/`. Model cache: `$XDG_CACHE_HOME/meetingmaster3/models` (HF_HOME points here). In Docker these are the `/config`, `/data` and `/models` volumes. All paths can be overridden with `MM3_*` env vars.
- **R4 Checkpointing and resume** (resolves the §13 open question). Each pipeline stage writes its output artifact (`transcript.json`, `aligned.json`, `diarization.json`, `speakers.json`, `notes.draft.md`) plus a row in SQLite. Resume restarts from the first stage that did not complete. Cancel is cooperative between stages and at chunk boundaries where the library allows.
- **R5 One GPU job at a time.** A single-worker GPU queue. **VRAM handoff on 8 GB:** WhisperX and pyannote models are unloaded (`del`, `gc.collect()`, `torch.cuda.empty_cache()`) before the LLM stage. When the LLM backend is a local Ollama on the same GPU, the app asks Ollama to unload (`keep_alive: 0`) before transcription starts. Without this, an 8 GB card will OOM.
- **R6 Context-window handling and defaults** (resolves the §13 open question). Estimate tokens, using roughly 4 chars per token unless the backend provides a tokenizer. If the transcript plus prompt exceeds about 70% of the model's context window, use **map-reduce**: chunk the transcript on speaker-turn boundaries, extract per-chunk notes, then generate sections from the merged extractions. Default temperature is **0.2** for extraction-style sections (decisions, action items, open questions, facts) and **0.4** for narrative sections (summary, AI recommendations). Templates may override both.
- **R7 Audio ingest.** ffmpeg is a required dependency, in the Docker image and on the host. Uploads are probed (ffprobe) and normalised to 16 kHz mono WAV. Configurable max upload size (default 2 GB). Accepted formats: whatever ffmpeg decodes, with an allowlist of extensions in the UI.
- **R8 Audio retention** (owner decision 2026-10-11, ADR-0006). The pipeline uses the normalised 16 kHz WAV while the job runs. When the job reaches `written`, the audio is re-encoded to **Opus mono at about 24 kbps** (`jobs/<id>/audio.opus`, roughly 11 MB per hour), and the original upload and the WAV are deleted. The kept audio is **auto-deleted 90 days** after the job was written. The retention setting offers *forever* / *N days* (default **90**) / *delete after write*, and each meeting can be **pinned** to keep its audio regardless. Pruning runs at startup and every 24 h, and on demand with `mm3 jobs prune`. When audio has expired, the review screen shows a notice and the transcript stays fully usable. An opt-in setting, off by default, copies the Opus audio into a vault attachments folder so Obsidian can link it (`mm3-audio` frontmatter key). The settings UI warns that this enlarges the vault and that a synced vault will upload the audio to other devices.
- **R9 Frontmatter additions.** Add `mm3-id` (UUIDv4 linking the note to app data), `mm3-generated` (ISO-8601 timestamp), `mm3-backend` and `mm3-model` (provenance), and optionally `mm3-audio`. The companion transcript frontmatter includes `mm3-id`, `mm3-note` (wikilink back), `mm3-speakers`, `duration`, `language`, `mm3-transcription-model`.
- **R10 Common note header.** Every template renders the Appendix B header (Date & Time, Participants, Tags, Location/Context) directly under the H1, outside any regenerable section.
- **R11 Section-marker robustness.** The parser is strict. If a section's open/close markers are missing, duplicated or mis-nested, regeneration of that section is refused with a clear message and offers: (a) append a fresh section at the end, or (b) cancel. Content outside markers is never modified.
- **R12 Archive convention** (choosing between the two options in §5). Section archives go to `<output folder>/Archive/YYYY-MM-DD - Meeting Title.<section-id>.YYYYMMDD-HHMM.md`. Whole-note archives (template switch) go to `<output folder>/Archive/YYYY-MM-DD - Meeting Title.YYYYMMDD-HHMM.md`.
- **R13 Filename safety.** Titles are sanitised for Obsidian- and filesystem-forbidden characters (`* " \ / < > : | ? # ^ [ ]`, control chars, leading/trailing dots and spaces) and length-limited. On collision, append ` (2)`, ` (3)`, … and never overwrite silently.
- **R14 Diarization model.** Use the pyannote pipeline that the pinned WhisperX version supports (e.g. `pyannote/speaker-diarization-3.1` or `pyannote/speaker-diarization-community-1`). Phase 06 verifies and records the exact model IDs and licence-acceptance URLs. After the first download, setting `HF_HUB_OFFLINE=1` guarantees no network calls.
- **R15 Container base image.** A plain `python:3.12-slim` base cannot run CTranslate2 on GPU without CUDA/cuDNN runtime libraries. Phase 14 picks one of: `nvidia/cuda:*-cudnn-runtime` as the runtime base, or slim + pip `nvidia-*-cu12` wheels. The choice is based on measured image size and is recorded as an ADR. Two build targets: `gpu` and `cpu`. The GPU target requires NVIDIA Container Toolkit on the host.
- **R16 Ollama connectivity.** By default the app uses the host's Ollama: `http://host.docker.internal:11434` with `extra_hosts: host-gateway`. The docs note that Ollama must listen on an interface the container can reach. An optional compose profile runs Ollama as a container.
- **R17 Performance expectations.** "60-minute meeting in 2–5 minutes on 8 GB" is a target, not a promise. Laptop GPUs such as the RTX 2070 Max-Q, with diarization enabled, may be slower. Phase 15 measures real RTF on the reference machine, and the UI and README publish measured numbers.
- **R18 Note format details** (Phase 03; normative description in `docs/dev-guide/note-format.md`, ADR-0010 to ADR-0012). The companion transcript also carries `mm3-version` and `mm3-diarized`, and ends with one hidden `<!-- mm3:transcript-data v1 ... -->` JSON-lines block that is the lossless source of truth for segments, words and timings. Line endings are preserved per file (new files LF). Archives carry `mm3-archived` and `mm3-archived-from` (section archives have no `mm3-id`), and re-open pickers skip them. The output-folder template also accepts `{dd}`. A note's `date` may be absent in a hand-edited file; `mm3-id` is the only required property.
- **R19 Job states and retention details** (Phase 04, ADR-0013). Job states are `queued`, `running`, `waiting_for_input`, `interrupted`, `failed`, `cancelled` and `written`; failed, cancelled and interrupted jobs can be resumed, with optional option overrides. Interrupted jobs are resumed by the user, not automatically. Retention follows the **current** setting for every job, and the audio of jobs that never reach `written` is also deleted `audio_retention_days` after the job last changed (unless retention is *forever*). Pinned jobs are always kept. Uploads larger than `audio.max_upload_mb` are refused while streaming.

- **R20 Transcription details** (Phase 06, ADR-0014). The diarization model is `pyannote/speaker-diarization-community-1` (pyannote.audio 4, CC-BY-4.0, gated; terms at https://huggingface.co/pyannote/speaker-diarization-community-1); English alignment is torchaudio `WAV2VEC2_ASR_BASE_960H`. The §3 non-English choice "proceed" transcribes in the **detected** language (or one the user names) with a warning, rather than forcing English decoding; `transcription.on_non_english` (`ask`/`proceed`/`abort`) can pre-answer it. The transcription model is the job option `transcription_model` (`model` is the LLM model). A non-diarized transcript carries no speaker labels. Transcript segments are split at word-level speaker changes. Library telemetry (pyannote's OpenTelemetry metrics, Hugging Face Hub) is always disabled, and cached models load without any network access, so model downloads are the only network calls transcription makes.
- **R21 Speaker naming and voiceprints** (Phase 07, ADR-0015). Speaker embeddings come from the WeSpeaker ResNet34 model inside the cached diarization pipeline; matching uses the maximum cosine similarity over a person's stored embeddings, a one-to-one (Hungarian) assignment, a threshold (`speakers.match_threshold`, default 0.6) and a margin over the second-best person (`speakers.match_margin`, 0.1). With `privacy.voiceprints_enabled` false (the default), no embeddings are computed and nothing is stored; naming works the same way without suggestions. Voices are remembered only for speakers the user marks `enroll`; labels confirmed as the same person are merged. The confirmed speaker map is stored with the job (`speaker_map.json`) and every named view derives from it (`speakers.cascade.apply_speaker_map`). A transcript without speakers skips the confirmation pause. Deleting all voiceprints is a two-step call with a confirmation token; deletes are physical (`secure_delete`).
- **R22 Templates and note generation** (Phase 09, ADR-0016 to ADR-0018; normative format in `docs/dev-guide/template-format.md`). Template schema version 1: YAML frontmatter (`mm3-template`, `id`, `name`, `description`, `tags`, `favorite`, `sections` with `kind` narrative/extraction and `format` markdown/tasks/bullets, `params`) plus `<!-- mm3:prompt:<id> -->` blocks including a required `_system` block; validation reports line-numbered issues and invalid templates are listed, not fatal. `ai-recommendations` must be the last section unless `params.ai_recommendations: false` (for templates where it is inappropriate). Built-in templates are copied into the vault's templates folder on first use and never replace a user-edited file (hash manifest in app data); vault templates override built-ins by `id`. Each section is one LLM call with a shared prefix (prompt-cache friendly); the model writes deadlines as said and code adds weekday dates; task sections get tagged candidate sentences and an owner guard that un-assigns tasks whose named owner only suggested or declined them. Local models plan for at most `generation.max_context` tokens (default 16 384); reasoning models run without "thinking" unless `generation.think`. Cloud backends without consent pause the job with a `cloud_consent` question (S6) instead of failing. A note's header shows a date without a time when the meeting time is unknown (stored as midnight). The companion transcript can be turned off (`generation.write_companion`, Q2), with a warning that regeneration and renaming are then unavailable.
- **R23 Review workspace** (Phase 11, ADR-0024, ADR-0025). The workspace lives at `/meetings/{mm3-id}`. The editor edits the note as parts (properties, user text around sections, each section's content); section-marker lines are never editable there, and the server re-inserts them, so unchanged bytes stay identical. Saves are atomic and refused when the vault file's hash differs from the version the editor was opened from (the user then keeps theirs, takes the file's, or merges). Unsaved edits are autosaved to app data. Regeneration diffs against the editor's current text; "Accept & archive previous" archives that version (R12) before replacing it in the editor; the user then saves. A damaged section (R11) can be appended as a fresh section (a numeric suffix is added to its id) while its damaged text stays put. A template switch shows the new note first, then archives the old one whole; text outside the old sections is kept under "## Preserved notes". Renaming speakers rewrites names only inside MM3 sections, in the companion transcript and in the properties, plus the Participants header line if unedited; it does not enroll voiceprints. The vault picker lists only files with `mm3-id` that are not archives or transcripts. Without a companion transcript a note opens note-only (no regeneration, switch or rename, with options to locate the transcript or transcribe the retained audio again); a note without markers opens read-only.

- **R24 Hardening** (Phase 15, ADR-0027, ADR-0028; threat model `docs/THREAT_MODEL.md`). A cloud-consent answer is single-use: it is consumed by the generate run that reads it, resuming from a stage clears the answers of the stages it resets, and a reprocessed meeting asks again (S6). Per-meeting voice embeddings are never exported and are deleted with the audio or by "delete all voiceprints" (S7). YAML read from the vault allows aliases but caps their expansion at 10 000 nodes; unbuildable values are frontmatter errors. Backend header values (except attribution headers) and passwords in base URLs are secrets (S5). ffmpeg/ffprobe inputs are limited to local files and playlist/list formats are refused. The optional audio copy into the vault never replaces a file (R13). Docker images are based on Debian 13 without curl or system pip. R17 is measured on the 8 GB reference GPU (`docs/PERFORMANCE.md`): transcription with diarization 13-16x real time, notes with a local 8B model about 15-21x; the pre-job estimate includes the notes when the default backend is local.
- **R26 Pre-operational tuning, round 2** (Phase 15b, ADR-0036, ADR-0035). (a) The review screen opens the note **rendered (Preview)**, server-side; **Edit** is one click away and is chosen automatically by actions that need it; the last mode is remembered per browser. (b) Beside the player, one line states how long the meeting's recording is kept: days left (whole days, rounded up) and date under `privacy.audio_retention`, or "kept forever". The days come from the pruner's own expiry rule (`jobs.retention.effective_expiry`), so they cannot disagree with it. **Keep forever** sets the existing per-meeting pin (R8, `jobs.audio_pinned`) and **Allow deletion** clears it (with a confirmation); no second flag. (c) Amends R25(f): the logo and hero picture are released under **CC0 1.0** (copyright only; no trademark or likeness rights); the original `wiz.jpg` is never committed.
- **R25 Pre-operational tuning, round 1** (Phase 15a, ADR-0031, ADR-0032). (a) Besides the companion, every meeting gets a **readable transcript** `<note stem> (Transcript).md` next to the note, laid out like the review screen (muted clock and colour-highlighted name, text below, paragraphs every ~90 s of a long turn), with spoken text neutralised (S3), `mm3-kind: readable-transcript` in its frontmatter, never parsed back, rewritten whenever the companion is written, never replacing a file MM3 did not write, linked from the note's `- **Transcript:**` header line, and ignored by every vault scanner; `generation.readable_transcript` (default on). The `.txt` export uses the same layout. (b) File names: month-day dates (`09-22`, `Sep 22`, `22 Sep`…) and US dates with a year (`09-22-2026`, `9-22-26`) are recognised; a date without a year takes the current year, or the previous one when it would be more than a day in the future; the form says "From the file name". (c) Every built-in template has **Summary Succinct** (`summary`, formerly "Summary") followed by **Summary Detailed** (`summary-detailed`): prose, typically three paragraphs, never fewer than two (enforced by one retry, then a warning). Unedited vault copies of built-ins are upgraded at start. (d) **Update older notes** (Recent, `mm3 notes upgrade`) adds what older notes lack after a dry run, archiving each note first and never overwriting a concurrent edit. (e) The job page says quietly whether leaving it is safe, and the tab title follows the job. (f) A logo (not Apache-2.0; released under CC0 1.0 by R26) is shown on navigation pages only; the New meeting page also shows the whole picture above its heading (ADR-0033).
- **R29 Default Notes, the 23rd built-in template and the default** (Phase 15e, ADR-0039; amends A3's count and default). `default-notes` ("Default Notes") writes a briefing for someone who missed the meeting, one structure for every kind of meeting: Summary Succinct (1-2 sentences, at most about 50 words), Summary Detailed (R25), Meeting Context (purpose and each person's stated role), **Discussion by Topic** (4-9 numbered `### N. <Topic>` headings in the order discussed, each with 2-4 bold-labelled, timestamped paragraphs dense with figures, names, dates and attributions; about 1 000-1 500 words for an hour), Questions & Answers (only when much of the meeting was questions and answers; otherwise a fixed sentence), Conclusion (one paragraph), Action Items (`format: tasks`, grouped by owner) and AI Recommendations. Its `_system` carries the interview guardrails of `job-interview-notes`. Its name is neutral (no other product's name). It is the **default template on a new install** (`generation.default_template: default-notes`, replacing Executive Summary); the template chosen on the New meeting page becomes the saved default for the next meeting (the page sends `remember_template`; API and CLI clients that do not send it change nothing). A new template parameter `params.detail: standard | high` (default `standard`) lets a template ask the map-reduce step (R6) for richer notes: up to 30 points of up to 40 words per part, with their specifics and a topic label, plus up to 10 answered questions with who asked and who answered, and 3 500 output tokens per map call; `default-notes` uses `high`, and falls back to `standard` when the window is too small. A second optional parameter,
`params.task_candidates: all | relevant` (default `all`), changes which task-candidate sentences (R22) the model sees:
`relevant` shows only those that name follow-up work (send, schedule, review, prepare…), as hints, and drops the "every
commitment must appear" rule; `default-notes` uses it.

#### 15.3 Security and privacy baseline (new; applies to every phase)

- **S1 Network exposure.** Bind `127.0.0.1` by default. Binding elsewhere requires an explicit setting and shows a warning. There is no auth in MVP (single-user, local), so exposure is the main control.
- **S2 Browser-origin attacks on localhost.** A Host-header allowlist defends against DNS rebinding. Every state-changing request needs a CSRF token and an Origin check. Use `SameSite=Strict` cookies.
- **S3 Output rendering.** Rendered Markdown and transcript text are HTML-sanitised. A strict Content-Security-Policy is possible because all assets are vendored.
- **S4 Filesystem.** All vault writes resolve inside the configured vault root; anything that resolves outside (`..`, symlinks) is rejected. Writes are atomic (temp file + `os.replace`). Uploads are stored under app data with server-generated names.
- **S5 Secrets.** API keys and the HF token come from env vars or from `config.yaml`, which is created with mode `0600`. Secrets are never logged, never returned in full by the API (masked), and never written to the vault.
- **S6 Cloud egress consent.** The UI shows a clear "local" or "cloud: <provider>" badge for the selected backend. The first use of a cloud backend in each job needs explicit confirmation, which can be remembered per backend. No telemetry, ever.
- **S7 Voiceprints are biometric data.** The voiceprint store is opt-in and local only, never written to the vault. The UI can list and delete any stored speaker or wipe the whole store, and the docs explain what is stored.
- **S8 Supply chain.** Pinned, locked dependencies (`uv.lock`), `pip-audit` in CI, Dependabot, and licence inventory in `THIRD_PARTY_NOTICES.md`.

#### 15.4 Repository and publication requirement (new, mandatory success criterion)

The project lives in a single Git repository that is ready to publish on GitHub, and it must contain and keep accurate: `README.md`, `LICENSE` (Apache-2.0), `NOTICE`, `THIRD_PARTY_NOTICES.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md` (Keep a Changelog), `.gitignore`, `.dockerignore`, `.editorconfig`, `.github/` (CI workflows, issue and PR templates, Dependabot), and `docs/` (spec, architecture, decisions, user and developer guides). Private data (audio, vault content, tokens, `.env`) must never be committed; `.gitignore` and a pre-commit secret scan enforce this.

#### 15.5 Owner questions (status as of 2026-10-11)

1. **Decided.** Audio retention (R8): keep the audio compressed for 90 days, then auto-delete. Per-meeting pin, configurable period, opt-in copy to the vault. See ADR-0006.
2. **Decided.** Companion transcript: always written (needed for re-open and regeneration), or optional per the design notes' "transcript and/or summary according to user preference"? Decision: always written by default, with a setting to disable it that warns about losing regeneration.
3. **Deferred to Phase 16.** GitHub: repository owner/name and public vs private at first push. The owner provides these then.
4. **Decided.** Test audio: a Creative Commons multi-speaker clip plus recordings the owner provides that are cleared for sharing. Short clips (≤ 60 s, ≤ 2 MB) are committed as `tests/fixtures/audio/<name>.fixture.<ext>`, with source, licence and speaker consent recorded in `tests/fixtures/README.md`. Long recordings (10–60 min, for performance tests) are **not** committed, to avoid permanent repo bloat. They are read from `MM3_PRIVATE_TEST_AUDIO`, and can optionally be published later as a GitHub release asset with a download script.
5. **Deferred to Phase 16.** Personal machine details in `CLAUDE.md` move to an untracked `CLAUDE.local.md` before publishing.

---

### Appendix A. Template catalogue (from the design pre-notes)

1. **General Discussion Summary**: neutral, balanced overview of topics, main points and flow.
2. **Executive Summary**: short, high-level brief on outcomes, key decisions and implications. *(Stage 1)*
3. **Strategic Meeting Summary**: long-term goals, strategic options, alignment or misalignment, recommended directions.
4. **Action-Item / Task-Oriented**: tasks, owners, deadlines, status. *(Stage 1, as "Action-Focused")*
5. **Detailed Meeting Minutes**: comprehensive, near-verbatim structured notes in order.
6. **Job Interview Notes**: candidate strengths, concerns, answers to key questions, culture-fit signals, hiring recommendation.
7. **Multi-Participant Project Team Sync**: contributions by person or role, status, blockers, dependencies, milestones.
8. **Decision Log**: decisions, rationale, alternatives considered, owners. *(Stage 1)*
9. **Brainstorming / Ideation Capture**: ideas, clusters, energy or consensus, promising directions.
10. **Sales / Client Call Summary**: needs, pain points, objections, commitments, next steps, relationship signals.
11. **Agile Stand-up Notes**: by person: done, planned, blockers.
12. **One-on-One / Coaching Notes**: goals, progress, feedback, career topics, follow-ups.
13. **Formal Board / Governance Minutes**: attendance, motions, votes, resolutions, compliance language.
14. **Workshop / Training Recap**: concepts, exercises, learnings, questions, applications.
15. **Retrospective / Lessons Learned**: went well, didn't, root causes, improvements.
16. **Q&A Extraction**: questions and answers as a clean FAQ.
17. **Speaker-Attributed Notes**: points attributed to specific speakers.
18. **Chronological Timeline**: events, updates and decisions in order, with timestamps.
19. **Risks, Issues & Mitigations**: problems, severity, owners, mitigations.
20. **Key Takeaways + Next Steps**: only the key insights and immediate actions.

Plus from the PrePlan (Stage 1): **Technical Deep-Dive** and **Just the Facts**.

Typical sections, included as the template and content warrant: Summary/Overview, Key Points or Viewpoints, Decisions Made (with rationale), Action Items (owner, description, deadline, checkbox `- [ ]`), Next Steps, Open/Unresolved Items, Conclusion, AI Recommendations (always last; grounded in the discussion).

### Appendix B. Common note header

```markdown
# [Meeting Title]
- **Date & Time:** 2026-10-11 09:00
- **Participants:** Nick, Caleb, Michelle
- **Tags:** #interview #soc #hiring
- **Location / Context:** [optional]
```
