# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Ask AI agent** (Phase 15j, R31, ADR-0049, ADR-0051): an **Ask** page (`/ask`) and `mm3 ask "<question>"`
  answer broad questions from the meetings on file ("how many times did we discuss X, who led it and in what role,
  and a table of the meetings, dates and attendees"). A fixed, bounded pipeline: the model plans 2-6 searches,
  15i's hybrid search finds the meetings, the model reads each one (its header, Meeting Context and matching
  passages with neighbours, fitted to the window), one more search round if few are relevant, then answers from
  the findings. **Facts come from the files**: which meetings and how many, their dates, links and attendees are
  computed by code; people and quotes the model gives are kept only if they are in what it read; links to meetings
  it was not shown and tables it draws are removed. Local `qwen3:8b` by default (each call waits for the GPU
  between jobs), Bedrock or OpenRouter after consent. Progress with steps, ETA and Cancel; date and person filters.
- **Answers are kept and linked**: each answer is written to `MM3 Answers/YYYY-MM-DD HHMM - <question>.md` in the
  vault (atomic, never overwrites; `mm3-kind: answer`, `mm3-answer-id`, `mm3-sources` wikilinks, `#mm3/answer`),
  with the answer, a table of meetings, a People table, Sources with links to the moments, and how it was answered.
  The Ask page lists every answer (paged) with **Open in Obsidian**, **Ask again**, **Ask a follow-up** and
  **Delete** (note and record); a moved answer note is found again by its id, a deleted one offers **Forget**. A
  meeting's review page lists **Answers that cite this meeting**; Obsidian's backlinks show them too, and renaming
  a meeting updates the links. History in `mm3.db` (migration 5: `answers`, `answer_sources`).
- **Ask consent switch** (S6): a cloud backend needs a tick for each question (`mm3 ask --allow-cloud`) unless its
  new **Always allow Ask AI agent to send meeting excerpts to this backend** (`ask_consent_remembered`) is on; the
  note-writing consent does not cover Ask. The Ask page says what is sent where and shows an estimated cost.
- Settings → Search & Ask gains the **Ask AI agent** section: backend and model, most meetings read per question
  (`ask.max_meetings`, 25), keep every answer (`ask.keep_history`) and the answers folder (`ask.answers_subfolder`).
- `tests/eval/ask_eval.py`: scores the agent on a synthetic eight-meeting corpus (`tests/ask_corpus.py`) for the
  meeting set, count, table rows, people and roles, and citations, with time, tokens and cost per question.
- **Search your meetings by meaning and by words** (Phase 15i, R30, ADR-0049, ADR-0050): a **Search** page
  (`/search`) and `mm3 search "<question>"` find the passages most related to a question in every meeting note and
  companion transcript, grouped by meeting, with the matched words highlighted, date and person filters, and links
  to the meeting or straight to the transcript moment. Hybrid retrieval: an SQLite FTS5 word index plus meaning
  vectors from a local embedding model (Ollama `nomic-embed-text`, `ollama pull nomic-embed-text`), fused by
  reciprocal rank; without the model the search works by words only and says why. Any typed text is safe (quotes,
  `*`, `NEAR`, `:` are plain words).
- **Meeting index** `<data>/search.db` (0600, outside the vault, rebuildable), kept current by itself: at start-up
  in the background, seconds after the app writes or renames a meeting, every 10 minutes and on a stale search for
  edits made in Obsidian. Only changed files are re-read; a moved note keeps its vectors; editing one section
  re-embeds only that section. Indexing never competes with a transcription for the GPU (it runs only while no job
  is active). Settings → **Search & Ask** shows the embedder, meetings, passages, vectors, size, last update and
  problems, with **Update index**, **Rebuild index** and **Delete index**; `mm3 search index [--rebuild]` and
  `mm3 search status` do the same from the terminal.
- **Embeddings in the LLM backends**: `embed()` and `list_embedding_models()` for Ollama (`/api/embed`), AWS
  Bedrock (Titan Text Embeddings V2, Cohere Embed), OpenRouter (verified live: `/embeddings` with
  `openai/text-embedding-3-small`) and OpenAI-compatible servers, plus deterministic fake embeddings for tests;
  embedding models are never offered for writing notes. `mm3 llm test` says whether the search embedding model is
  available.
- **Cloud embedding needs its own permission**: a cloud backend embeds for search only with *Allow search
  indexing with this backend's embeddings* (`llm.backends.<name>.cloud_embedding_consent`, off by default), because
  indexing sends every meeting's full text and each search its query; otherwise nothing is sent (S6).
  *Revoke consent* clears it too.
- **Re-link moved meetings** (Meetings page, `mm3 notes relink`, ADR-0047): after a vault folder is moved or `vault.path`
  changes, entries whose note is missing or outside the vault can be found again by their `mm3-id`: **Find them in the
  vault**, then **Re-link** per entry or **Re-link N found** for all clear matches (one live note, or one that kept its
  file name); ambiguous entries offer a choice. Only the list entry changes, keeping its job, audio link and history.
- **Cloud model picker** (New meeting, Settings, the review page's Regenerate and Switch template): a drop-down of
  only the models that can write notes (text in and out, callable on demand or through an inference profile, workable
  context window, not measured as unsuitable), with **Show all models (N hidden)** and the reason for each hidden
  one; a typed id still works. Cloud models show the context size, price per 1M tokens (live from OpenRouter, a
  dated table for Bedrock with a staleness note after 180 days) and an estimated cost for the meeting, and
  **Best value** (Claude Haiku 5.5) and **Best quality** (Claude Sonnet 5.5) are marked from Phase 15g's
  measurements. Bedrock lists one entry per model using the id that can be called. Settings and New meeting
  now show the same set (Phase 15h, ADR-0042).
- **AWS keys for Bedrock in Settings** (Settings → Language models): write-only fields for the access key ID and
  secret access key of an IAM user, saved as a pair, removed from logs; the `MM3_SECRETS__AWS_*` variables still
  win and the page says when they are set (Phase 15g, ADR-0041).
- **Step-by-step setup guides** for AWS Bedrock (region, model access and the Anthropic use-case form, a
  least-privilege IAM user with the policy JSON, access key, where to put it, testing, rotating and revoking, the
  profile/SSO alternative) and OpenRouter (credit, key with a credit limit) in `docs/user-guide/llm-backends.md`,
  linked from Settings, the Docker guide and `.env.example`. `docker/compose.yaml` documents passing cloud keys in
  `.env` and an optional read-only `~/.aws` mount.
- **Bedrock context windows by model family** (`llm/bedrock_models.yaml`, ADR-0044): Claude, Nova, Llama, Mistral
  and others are planned with their real window instead of 8,192 tokens, inference-profile IDs (`us.…`,
  `global.…`) included; **Test** says when a model's window is unknown.
- Eval: `--cloud` (consent for a cloud backend), token counts per note, `--price-in/--price-out` for cost per note,
  `--long-tokens`. Live checks for cloud backends: `MM3_LIVE_BEDROCK=1` / `MM3_LIVE_OPENROUTER=1 uv run pytest -m
  network tests/integration/test_live_cloud.py`.
- **Ollama settings for small GPUs** in the hardware guide: flash attention (`OLLAMA_FLASH_ATTENTION=1`) and an 8-bit
  context cache (`OLLAMA_KV_CACHE_TYPE=q8_0`) keep more of an 8B model on an 8 GB GPU, which roughly halved note
  times on the reference laptop. How to set them for a systemd service, by hand and in Docker, and how to check the
  CPU/GPU split with `ollama ps`. The app never changes them. The optional bundled Ollama in `docker/compose.yaml`
  now sets both (Phase 15f, ADR-0043).
- **Title & date…** on the review page, and `mm3 meetings rename`, change a meeting's title, date and time after
  it was written (Phase 15d, R28, ADR-0040). One previewed operation renames the note, its companion and
  readable transcripts, its archives and the vault copy of its recording (moving them to the new year's folder
  when the note is in the old date's folder), updates their properties, heading and header lines, rewrites the
  links to them in every other vault note (wikilinks and Markdown links, keeping aliases, headings and blocks;
  each note backed up first), and updates the Meetings list, the job and its `written.json`. The meeting id,
  the sections, the transcript, the speakers and your own text never change. Each rename is journalled with
  backups in `<data>/rename-backups/`. An interrupted rename is completed or undone at the next start, and the
  Meetings page says which.
- **Default Notes** (`default-notes`), the 23rd built-in template and the new default (Phase 15e, R29,
  ADR-0039): a briefing for someone who missed the meeting. A one-line Summary Succinct, Summary Detailed,
  Meeting Context, **Discussion by Topic** (numbered topics with bold-labelled, timestamped paragraphs that
  keep the figures, names, dates and who said what), Questions & Answers when much of the meeting was
  questions, a Conclusion, Action Items by owner and AI Recommendations. It keeps every MeetingMaster3
  convention (frontmatter, header, file names, markers, task format) and the interview guardrails.
- The template you start a meeting with on **New meeting** becomes the pre-selected one next time (saved as
  `generation.default_template`, so Settings shows the same choice). API and CLI jobs do not change it.
- Template parameter `params.detail: standard | high`: long meetings (map-reduce) keep up to 30 points per
  part, with their specifics and a topic label, and the questions that were answered (who asked, who
  answered), for templates that write dense, topic-by-topic notes.
- Template parameter `params.task_candidates: all | relevant`: with `relevant`, task sections are only
  shown the candidate sentences that name follow-up work (send, schedule, review…), so conversational
  "I'll …" remarks in an informal call no longer become tasks.
- Eval: a synthetic introductory-call meeting for Default Notes and two new checks, `expected.numbered`
  (numbered headings in a section) and `expected.limits` (sentences and words in a section).
- Pre-operational tuning, round 3 (Phase 15c, R27, ADR-0038):
  - **Switch template** and **Regenerate** run in the background with a moving progress bar, the current step,
    elapsed time and time left (estimate from your hardware profile, then the run's measured rate), a motion cue
    (off with reduced motion), **Cancel**, and **Hide and keep running**; a reloaded page reattaches.
    New endpoints under `/ui/review/{id}/task`; `POST …/switch/preview` and `POST …/regenerate` return a task.
  - The review page shows the **size and format of the stored recording** and offers it for **download**
    (`GET /api/jobs/{id}/audio?download=1`), also in the header Download menu.
  - The Preview/Edit control is one button named after its action ("Edit note" / "Show preview").
  - **Meetings** (was Recent) is the one place for jobs, notes and **Browse the vault**; each section pages
    (10, 10, 25 rows) with bookmarkable `jobs_page`, `notes_page`, `browse_page` links. `/open` redirects to it.
  - `MM3_FAKE_LLM_SECONDS` slows the fake model for browser tests.
- Pre-operational tuning, round 2 (Phase 15b, R26, ADR-0036):
  - The review screen opens the note in **Preview** (rendered on the server); **Edit** is one click away, and
    the last mode is remembered.
  - **Keep forever** / **Allow deletion** for a meeting's recording, with a line beside the player showing
    how many days are left before it is deleted (the same rule the pruner uses), or that it is kept forever.
    `GET /api/jobs/{id}` and the pin/unpin responses include `audio.retention`.
  - The logo and hero picture are released under **CC0 1.0** (`brand/LICENSE.md`); forks may keep them.
- Pre-operational tuning, round 1 (Phase 15a, R25):
  - **Readable transcript** in the vault, `<note> (Transcript).md`, next to the note: the time, each speaker's
    name highlighted in their own colour (the review screen's palette), then the text; long turns are split into
    paragraphs. It is linked from the note's new `- **Transcript:**` header line, refreshed when speakers are
    renamed or a transcript is linked, included in the meeting zip, and ignored by every vault scanner. Setting
    `generation.readable_transcript` (default on).
  - **Summary Succinct + Summary Detailed** in all 22 built-in templates: the old Summary is renamed, and a new
    section of typically three paragraphs (never fewer than two, checked with one retry) follows it. Unedited
    vault copies of the built-ins are upgraded when the app starts; edited ones are kept and the library says a
    newer version exists.
  - **Update older notes** card on Recent and `mm3 notes upgrade [--dry-run] [--note] [--backend] [--model]
    [--allow-cloud]`: adds Summary Detailed, renames a default "Summary" heading and writes missing readable
    transcripts, after a dry run and an optional one-note preview; archives each note first, never overwrites an
    edit made meanwhile, and can be cancelled.
  - Dates in file names without a year (`09-22`, `9-22`, `09_22`, `Sep 22`, `Sept 22nd`, `22 Sep`) and US dates
    (`09-22-2026`, `9-22-26`); the current year is assumed, or last year when the date would be in the future. The
    form shows "From the file name" under the date.
  - The job page says quietly whether leaving it is safe (and what stops a job), and the tab title shows the
    progress (`42% · Transcribing`, `✓ Notes ready`).
  - A logo in the header of the navigation pages (not on job, speaker, review or preview pages), built by
    `scripts/make_logo.py`. The logo is © Nick Antonizick, all rights reserved, and not under Apache-2.0
    (`NOTICE`).
- The New meeting page shows the logo picture large above its heading: the whole scene as a 320 px wide
  rectangle with slightly rounded corners, centred, full width on a phone (ADR-0033). The small header logo is unchanged.
- Model choice that cannot fail late: for Ollama the app reads each model's capabilities and context length.
  The new-meeting picker leaves out embedding models and models whose context window is too small, pre-selects
  a tested model when no default is set, and explains a bad typed-in model before starting. The upload API and
  `mm3 process` refuse such a model before transcription (`E_LLM_MODEL_UNSUITABLE`, `E_LLM_CONTEXT`). When
  writing the notes fails, the job page offers **Try another model**: pick any usable local or cloud model, keep
  the transcript and speaker names, write only the notes again, and optionally save the choice as the
  backend's default. `/api/llm/backends/{name}/models` reports `can_generate`, `usable` and `suggested`.
- Recent: "Notes in your vault" entries can be removed from the list one at a time, and entries whose note is
  missing or outside the configured vault are marked (*File not found*, *Not in your vault*, with no dead links)
  and can be removed together. Only the list entry is removed, never the file.
- Hardening and QA (Phase 15): `docs/THREAT_MODEL.md` (assets, trust boundaries, STRIDE, every mitigation
  mapped to code and a test, residual risks); a control → test table and scan summary in `SECURITY.md`;
  `docs/PERFORMANCE.md` with measured numbers on the 8 GB reference GPU (60 minutes transcribed with speakers
  in about 4-5 minutes; a whole job with a local 8B model in about 8-9 minutes). Hypothesis fuzzing of every
  vault-file parser and the Markdown renderer (`tests/unit/test_fuzz.py`); end-to-end checks of S1/S5/S6
  (`tests/unit/test_security_controls.py`); a GPU socket audit; Playwright tests of re-open, the consent
  dialog, the out-of-memory retry, error pages and keyboard use, plus an axe-core WCAG 2.1 AA scan of 16
  pages, run in a new CI job. Eval results as JSON and `tests/eval/baseline.py` to flag quality regressions.
  CI also audits the `ml` extra (`scripts/pip_audit_ml.sh`). `scripts/gen_third_party.py` covers every
  extra and checks the licence policy.
- The time shown before a job starts includes writing the notes when the default backend is local
  (measured rate for 8 GB).
- Docker deployment (Phase 14): multi-stage `docker/Dockerfile` (`runtime-gpu`, `runtime-cpu`), compose
  files (GPU default, CPU override, host-network override for an Ollama on 127.0.0.1, optional `ollama`
  profile), a Makefile (`up`, `down`, `logs`, `doctor`, `models-download`, `prune`), a `docker` CI workflow
  (CPU image build and smoke test, GPU image build, compose validation), `.dockerignore`, and the guides
  `install-docker.md` and `install-native.md` (renamed from `installation.md`). Non-root, read-only root
  filesystem, port published on 127.0.0.1 only, no models in the image. Measured sizes in ADR-0026.
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
  retained recording again) and read-only mode for notes without markers. Phase 12's rating widget on the note and on every section.
  Guide: `docs/user-guide/reviewing-and-editing.md`. ADR-0024, ADR-0025, spec R23.
- Database migration 4: `recent_meetings.job_id`.
- Expanded template library (Phase 13): the remaining 17 built-in templates, so 22 ship in total:
  General Discussion Summary, Strategic Meeting Summary, Detailed Meeting Minutes, Job Interview Notes
  (job-relevant evidence only, advisory recommendation), Project Team Sync, Brainstorming & Ideation,
  Sales & Client Call, Agile Stand-up, One-on-One & Coaching, Board & Governance Minutes (motions and
  votes exactly as stated; no AI Recommendations), Workshop & Training Recap, Retrospective & Lessons
  Learned, Q&A Extraction, Speaker-Attributed Notes, Chronological Timeline, Risks, Issues &
  Mitigations, and Key Takeaways & Next Steps. Each has a golden prompt snapshot; invariant tests cover
  every template and the guardrails of the sensitive ones.
- `docs/user-guide/template-catalogue.md`, generated from the template files by
  `scripts/gen_template_catalogue.py` (checked in CI and by a unit test).
- Five synthetic eval meetings for the type-specific templates (interview, stand-up, retrospective,
  board meeting, sales call); the eval checker can require keywords in a section and forbid words
  anywhere in a note.
- Web UI, core flow (Phase 10): first-run vault setup with live validation and a preview of the output
  path, upload with drag and drop and progress, hardware confirmation with an ETA and advanced
  overrides, template and model pickers with a local/cloud badge and a cloud consent dialog, live job
  progress over SSE (cancel, retry, "retry with smaller model", language question, cloud-consent
  question), the Name Speakers screen (audio samples, suggestions, "same person as", "remember this
  voice"), a completion page with an `obsidian://` link, a sanitised read-only note preview, and the
  Recent list (resume, delete). Vendored HTMX 2.0.11 and the CSP build of Alpine.js 3.17.4; no CDN and
  no build step. Playwright browser smoke test (`e2e` marker).
- Settings, template library and feedback (Phase 12): a tabbed Settings screen (vault, transcription with a
  Hugging Face token test and background model downloads, notes and jobs, language-model backends with
  add/edit/remove, write-only API keys, connection tests, model lists, revocable cloud consent and the
  recommendations panel, privacy with a retention preview and voiceprint management including the two-step
  wipe, diagnostics with copy-path and export of all app data) that validates as a whole and writes
  `config.yaml`; a template library screen (favourite stored in the template's frontmatter, preview, in-app
  editor with line-numbered validation, duplicate, create, delete with archive, reset built-in with archive,
  tag and text filter); local feedback ratings on notes and sections (migration 3, JSON/CSV export, no
  telemetry); a Download menu per meeting (note, transcript, plain text, zip with the audio) and
  `GET /api/export/all`; the optional copy of the retained audio into the vault (`privacy.copy_audio_to_vault`,
  `vault.attachments_subfolder`, `mm3-audio` link). Playwright smoke test for settings and templates.
- `markdown-it-py` is now a direct dependency (note preview); `playwright` is a dev dependency.

### Security
- Phase 15 review fixes: a cloud-consent answer given while switching to a local model could later
  approve a cloud backend (S6, now single-use and cleared on resume; reprocessing no longer inherits
  consent); "Export all app data" could include a waiting job's voice embeddings (S7, now excluded and
  deleted by retention and by "delete all voiceprints"); a YAML alias bomb in a vault note or template
  hung the parser and impossible dates caused HTTP 500 (capped alias expansion); backend header values
  and passwords in base URLs were not masked or redacted (S5); the optional audio copy into the vault
  could overwrite a file (S4); reprocessed recordings escaped audio retention (R8); ffmpeg inputs are
  limited to local files and playlist/list formats are refused.
- Docker images: Debian 13 base (fewer open OS CVEs, newer ffmpeg), no curl or system pip (ADR-0027).
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

### Fixed
- **New meeting shows a "Synchronizing models…" banner** above the Model field while the model list, prices and
  recommendations load, instead of a bare text box for a few seconds. It fades in only if loading takes a moment, and
  respects reduced-motion settings.
- **The web app no longer freezes when its terminal stops accepting output** (ADR-0046): logging, uvicorn's included,
  goes through a bounded queue to a writer thread, so Ctrl+S (or a paused terminal) can only drop log lines, which
  are reported afterwards, instead of hanging every request. Log lines now use one timestamp format.
- **Claude 5.x models on Bedrock can write notes** (Phase 15g, ADR-0045): they reject `temperature`, which the app
  sent on every call, so every note failed. The Bedrock backend now repeats a rejected call as the model's error
  advises (no temperature; thinking switched off the way that model accepts) and remembers it per model.
- Bedrock honours **Let reasoning models think** (off by default) for Claude models; Haiku 5.5 had spent whole
  sections on hidden reasoning.
- A cloud model that returns **no text** because it hit its length limit (often on hidden reasoning) or a content
  filter now fails with a clear `E_LLM_BAD_RESPONSE` instead of writing an empty section (Bedrock and
  OpenAI-compatible, streaming too).
- Bedrock setup mistakes give clear errors (`E_LLM_CONFIG`): a model that needs its inference-profile ID, a
  Provisioned-only model, an unknown model ID. Bedrock lists every inference profile (the list is paged).
- **OpenRouter** (Phase 15g, ADR-0045 addendum): **Let reasoning models think** now reaches OpenRouter as its
  `reasoning` switch; Claude 5.x reasoned by default there and emptied sections. Models that cannot stop reasoning
  (Sonnet 5.5, Opus 5.5) fall back to low effort automatically. Claude models on OpenRouter are planned at a 200k
  window as on Bedrock, so long meetings are not billed at the long-context price.
- A cloud or OpenAI-compatible server's 4xx error now shows the provider's own short reason instead of only
  "returned HTTP 400".
- Settings → Language models → **Edit** a backend no longer collapses: the model list replaced the whole form.
- Eval checker: a bold owner heading above a group of tasks is not a malformed task line.
- Tasks written as `**Owner:** task (due: …)` without a list marker (Haiku 5.5 in Default Notes) become `- [ ]`
  checkboxes, so they show up as Obsidian tasks; the eval checker flags any task line that is not a checkbox.
- Long meetings asked a local Ollama for more context than any call used (the output reserve was counted twice):
  Default Notes now asks for 13 312 tokens instead of 15 360 on the default 16 384 window. Each note's context is
  the size of its largest real call plus a measured 10 % margin, still one value per note (Phase 15f, ADR-0043).
- A retry (a map step's JSON repair, or Summary Detailed asked for more paragraphs) and a section regeneration with a
  long previous version could be larger than the context Ollama was given, which silently cuts the start of the
  prompt. They are now counted, and a retry repeats only what fits. Map chunks count each turn's timestamp, and the
  merged notes of very long meetings are counted at their real token density.
- Static files are sent with `Cache-Control: no-cache`, so a browser that cached an older `review.js` no longer breaks the review page (for example an Edit note button that did nothing) after an upgrade.
- With no default model set for Ollama, the new-meeting page filled in the first installed model, which could be
  an embedding model such as `nomic-embed-text` (2,048-token window). The job then failed at *Generating notes*
  with a context error, after the whole transcription, and the error's advice (raise `generation.max_context`)
  could not help. Context errors now say whether the model or the setting is the limit, and point at the
  matching fix.
- Workspace section-marker labels had too little contrast (axe-core, WCAG AA).
- The board-governance template's vote line contradicted its own instruction to copy the chair's
  words ("carried unanimously").
- Frontmatter values PyYAML cannot build (an impossible date) gave HTTP 500 instead of a readable error.

### Changed
- **Model lists (Phase 15h).** New meeting lists a cloud backend's models as soon as it is selected (this sends only your
  API key to that provider, as Settings' Load models does, never the transcript); before, you had to type the id.
  Settings and New meeting now agree on which models are usable (Settings applied only the embedding-model check).
  `cloud_recommendations.yaml` is format version 2 (`picks`, `unsuitable`); its generic `cloud` list is unchanged.
- The default template for a new install is **Default Notes** instead of Executive Summary (R29). A
  `default_template` already saved in `config.yaml` is kept.
- The plain-text transcript export (`.txt`) uses the readable layout: time and name on one line, the text
  below, a blank line between turns.
- The guessed title drops a date found in the file name, and a free-standing `_` (a `:` or `|` replaced by the
  recorder or browser) becomes ` - `.
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
- Documentation skeleton: `docs/MM3_ARCHITECTURE.md`, `docs/PRIVACY.md`, user and developer guide indexes.
- Planning artifacts from Phase 00: specification v1.1, ADR log, implementation plan and phase prompts.
