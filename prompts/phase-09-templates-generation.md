# Phase 09: Template Engine & Note Generation (End-to-End Backend)

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 03, 07, 08 · **Branch:** `phase-09-templates-generation`

## Read first
`CLAUDE.md`, `prompts/_shared-instructions.md`, and `docs/SPECIFICATION.md` §2, §3, §5, §6, §8, §9, §15.1 (A3), §15.2 (R6, R9–R11), §15.3 (S6), and Appendices A and B. Phase Log entries for 03, 07 and 08. Open question Q2 (companion transcript optional?). `docs/dev-guide/note-format.md` (normative format).

**Phase 03 interfaces for the WriteStage:** `vault.paths.resolve_vault_root` and `output_folder(root, settings.vault.output_subfolder, date)`; `vault.naming.allocate_note_paths(folder, date, title)` (gives `.note`, `.transcript`, `.note_link`, `.transcript_link`); `markdown.note_writer.build_note(meta, sections, ...)` + `render_note(note)` (H1, Appendix B header and AI Recommendations ordering are handled there, so templates do not render the header); `markdown.transcript_format.build_companion(...)` + `render_transcript(doc)`; `vault.io.atomic_write_text(path, text, vault_root=root)` (never overwrites without `overwrite=True`). Set `MeetingMeta.transcript_ref = paths.transcript_link`, `generated_at` truncated to seconds. `Section(id, title, body_markdown)` rejects bodies containing `<!-- mm3:section` lines, so strip marker-like lines from LLM output before building sections. For regeneration, compare old and new bodies with `markdown.diff.unified_diff` / `side_by_side`.

**Phase 04 interfaces** (`docs/dev-guide/jobs-and-stages.md`): register `GenerateStage` and `WriteStage` with `jobs.pipeline.register_stage("generate"|"write", factory)`. The speaker answer is `ctx.artifacts["await_speaker_confirmation"]` (JSON `{"speakers": {...}}`), the transcript `ctx.artifacts["diarize"]`. Mark `GenerateStage.uses_gpu = True` when the backend is a local Ollama on the same GPU, so the runner's GPU semaphore serialises it with other jobs' transcription. Every stage artifact must be a file in the job folder: `WriteStage` writes the vault files, then returns a JSON artifact (e.g. `written.json`) listing the vault paths. Retention is applied by the runner when the job reaches `written` (Opus re-encode, expiry); `WriteStage` does not touch audio. Add the note to `storage.repositories.RecentMeetingsRepository(db).touch(note_path, transcript_path=..., mm3_id=..., title=..., date=...)` (the app database is `ctx.db`). `mm3 process` can drive a `JobRunner` directly in an event loop.

## Goal
The heart of the product. A transcript, a speaker map and a chosen template produce a **secretary-grade** Markdown note, written into the vault together with the companion transcript. The whole flow works headlessly (API + CLI) before any UI exists.

## Tasks
1. **Template file format** (`docs/dev-guide/template-format.md` is normative; write it first):
   ```markdown
   ---
   mm3-template: 1                 # schema version
   id: executive-summary
   name: Executive Summary
   description: Short, high-level brief…
   tags: [general, leadership]
   favorite: false
   sections:
     - {id: summary, title: Summary, kind: narrative}
     - {id: decisions, title: Decisions Made, kind: extraction}
     - {id: action-items, title: Action Items, kind: extraction, format: tasks}
     - {id: open-questions, title: Open Questions, kind: extraction}
     - {id: next-steps, title: Next Steps, kind: extraction}
     - {id: ai-recommendations, title: AI Recommendations, kind: narrative}   # always last
   params: {temperature: null, max_tokens_per_section: 800}
   ---
   <!-- mm3:prompt:_system -->  global persona/rules for this template
   <!-- mm3:prompt:summary -->  instructions + example structure for the section
   …
   ```
   `kind` drives the default temperature (R6). `format: tasks` means Obsidian checkboxes `- [ ] **Owner:** task (due: …)`. Validation gives line-numbered errors, and `ai-recommendations` is enforced last (spec §8).
2. **Loader (`templates/loader.py`):** loads the built-in templates from `src/meetingmaster3/starter_templates/`, and on first run (or on demand) **copies them into the vault templates folder** (default `MeetingMaster3/templates/`) without overwriting user-modified files. User templates in the vault take precedence by `id`. Invalid templates are listed with their errors rather than crashing.
3. **The 5 stage-1 templates** (A3): Executive Summary, Technical Deep-Dive, Decision Log, Action-Focused and Just the Facts. Write the prompts carefully. They should produce the tone of a skilled chief of staff: concise, specific, attributed, no filler, no hallucinated owners or dates ("Owner: unassigned", "Due: not stated"), grounded in the transcript with optional `[mm:ss]` references. Each template includes the Appendix B header (R10), which is rendered by code from metadata, not by the LLM.
4. **Prompt assembler (`templates/assembler.py`):** builds `system` (a global MM3 rules block, the template `_system` prompt, the speaker list, the meeting metadata, and "today's date" for relative deadlines) and per-section `user` messages (section instructions, the named transcript formatted as `[mm:ss] Name: text`, optional user instructions, and on regeneration the *prior section content* plus the user's feedback). Output rules: return only the section body Markdown, without the heading or markers.
5. **Generator (`templates/generator.py`):**
   - If the transcript fits the budget (Phase 08's `llm.budget.fits(backend, model, prompt)`; `chunk_transcript(turns, max_tokens)` takes `llm.budget.Turn(speaker, text, start)` items, so convert the transcript segments into `Turn`s, and call `llm.consent.enforce_consent(backend, cloud_consent=..., remembered=cfg.consent_remembered)` before any generation call), generate each section from the full transcript.
   - Otherwise use **map-reduce** (R6): per-chunk structured extraction (JSON: points, decisions, actions, questions, with timestamps and speakers), validated with pydantic and repaired or retried once on bad JSON; merge and deduplicate; then generate sections from the merged extraction plus chunk summaries.
   - Sections are generated sequentially with progress events per section. Each section output is post-processed: strip stray headings and markers, normalise checkboxes, and trim.
   - `regenerate_section(note, section_id, instructions?)` returns the new body only; the Phase 03 diff utilities compare it, and the caller decides whether to apply and archive.
6. **Stages:** `GenerateStage` (enforces cloud consent S6; writes `notes.draft.md`, a full rendered note) and `WriteStage` (Phase 03 vault writer: main note plus companion transcript, links both ways, adds to `recent_meetings`, applies retention). Q2 (decided): always write the companion by default, with a setting to disable it that warns that regeneration will be lost.
7. **Headless entry points:** `mm3 process <audio> --title --date --template --backend --model --speakers "SPEAKER_00=Alice,…"` (non-interactive, for testing and scripting; if `--speakers` is omitted, it prompts on the TTY), and `mm3 templates list|validate|install`. API: `GET /api/templates`, `POST /api/jobs/{id}/generate` (template and backend options) and `POST /api/notes/regenerate-section`.
8. **Quality evaluation:** create `tests/eval/` with 2–3 synthetic transcripts (realistic meetings written as fixtures, with known decisions, actions and owners) and a lightweight checker that scores the generated notes: required sections present, every expected action item captured, no invented owners, AI Recommendations last, valid Markdown and markers. Run it with the local Ollama model (`network`/`slow`-marked) and record the scores in the Phase Log. Iterate on the prompts until the checks pass on an 8 GB-class model.

## Tests
Template validation (good and bad fixtures, with line numbers); the user-template override; the non-overwrite copy; assembler snapshots (golden files); map-reduce with FakeLLMBackend (deterministic, covers JSON repair); the consent refusal; end-to-end with FakeTranscriber + FakeLLM: audio → note and transcript in a temp vault, which the Phase 03 parser parses back with all markers valid.

## Acceptance criteria
- On the reference machine, `uv run mm3 process tests/fixtures/audio/<clip> --template executive-summary --backend ollama` writes a valid note and companion transcript into a test vault, fully offline.
- The eval checks pass with a recommended 8 GB local model, and the scores are recorded.
- A long synthetic transcript (≥ 3× the context window) completes through map-reduce.

## Phase-specific docs
`docs/dev-guide/template-format.md` (normative); `docs/user-guide/templates.md` (using and customising templates); README (Quickstart now has a real headless flow); ARCHITECTURE (generation flow diagram); ADRs for the map-reduce design and the default temperatures. Then the standard close-out checklist.
