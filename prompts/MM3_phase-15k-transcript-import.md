# Phase 15k: Import a transcript or an AI conversation (no audio)

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 15j · **Branch:** `phase-15k-transcript-import` · **Worktree:** `../MeetingMaster3-phase-15k`

Inserted with `/phase-add` after 15j (ADR-0034, ADR-0052). Today every MeetingMaster3 workflow starts from an audio
or video file. Nick also has text he wants turned into notes: transcripts made elsewhere (Plaud, Otter, Teams/Zoom
captions, MM3's own `.txt` export) and, above all, **exports of conversations with AI assistants** (Grok voice mode
in particular). This phase adds a second job type that starts from a text file, turns it into the same `Transcript`
the audio pipeline produces, lets Nick confirm who said what, and then runs the existing generate and write stages, so
the result is an ordinary MM3 meeting: note, companion transcript, Meetings entry, review, regenerate, template
switch, rename, Search and Ask-AI all work unchanged. Phase **15l** adds Grok share links on top of this phase's
parser interface, and **15m** adds the *Create Project Plan* template; both build on this phase and can run in
parallel with each other.

## Read first
- `CLAUDE.md`, `prompts/MM3_shared-instructions.md`, `docs/MM3_SPECIFICATION.md` §15 (R7 upload, R13 naming, R18 note
  format, R19 jobs, R25 readable transcript, R28 rename, R30/R31 search and Ask; S1-S6).
- **ADR-0052** (this feature's decisions), ADR-0010 (companion data block), ADR-0012 (round-trip), ADR-0013 (jobs),
  ADR-0018 (generate/write stages), ADR-0019 (HTMX UI), ADR-0031 (readable transcript).
- `docs/dev-guide/jobs-and-stages.md`, `docs/dev-guide/note-format.md`, `docs/dev-guide/storage.md`.
- Phase Log entries for 04, 07, 09, 10, 11, 15a, 15d, 15i.

## Nick's request (verbatim intent, 2026-10-24 11:20 CDT)
"I want to add a feature that will allow me to start the workflow by importing a transcript or a export from an AI
conversation (Rather than starting the workflow only from an audio sound file) I'm attaching an Example markdown file
of an AI conversation as a typical example of what I would like to initiate the workflow by when leveraging this new
option."

During intake: the example is `/home/nick/Documents/01 Inbox/privacy project brainstorming.md`, also shared as
`https://x.com/i/grok/share/…`. "It would be greatly preferred if you and MeetingMaster3 workflow can use the URL from
x.com as that makes my workflow much much easier, but uploading an MD file With transcripts or notes should also be an
option for the user." (The URL is Phase 15l.) Formats chosen for this phase: **AI chat Markdown** and **timestamped
transcripts**. An imported conversation shows up **the same as a meeting**.

## Decisions already made (ADR-0052)
- **Same as a meeting.** An import is a job of a new type (`import`) whose output is a normal MM3 note, companion
  transcript and readable transcript in the meetings folder, with a Meetings entry. It is marked as imported in the
  note's frontmatter (default `mm3-source: import` plus `mm3-source-format: <parser id>`) and on the review page. No
  separate "Conversations" kind.
- **Formats in this phase:** (a) AI chat Markdown: role-labelled exports (`## User` / `## Assistant`, `**You:**`,
  `User:` / `Grok:` / `ChatGPT:` / `Claude:` lines and the like) **and** unlabelled exports such as Nick's Grok
  voice-mode example; (b) timestamped transcripts: `[hh:mm:ss] Name: text` lines (MM3's `.txt` export, Plaud and
  similar), MM3 companion `.transcript.md` files, WebVTT `.vtt` and SubRip `.srt`. Official JSON data exports and a
  paste box are out of scope.
- **The example conversation is private.** Use `privacy project brainstorming.md` only locally (copy it to
  `~/.local/share/meetingmaster3/private-eval-15k/`, deleted at close-out). Never commit it, quote it in committed
  files, or put it in fixtures, golden files or the Phase Log. Committed fixtures are **synthetic** conversations
  written in the same shape (see Tests).

## Goal
On the New meeting page Nick chooses **Import a transcript or AI conversation**, uploads his Grok Markdown export (or
a timestamped transcript), sees a preview of the turns with who said each one, fixes any wrong speaker with one click,
names the speakers (default "Nick" and the assistant's name), picks a template, and gets an ordinary MM3 note in the
vault, with no audio and no transcription step.

## What exists (verified 2026-10-24 11:39 CDT; re-check before relying on it)
- **Job types:** `jobs.job_type` exists in the schema (`storage/migrations.py`, default `'meeting'`) and in
  `storage/repositories.py:JobRecord`; `jobs/runner.py:JobRunner.create_job(..., job_type="meeting")` and
  `pipeline_for(job_type)` already take it. `jobs/pipeline.py:build_pipeline` raises `E_JOB_TYPE` for anything but
  `meeting`; `MEETING_STAGES` is `ingest, transcribe, align, diarize, speaker_suggest, await_speaker_confirmation,
  generate, write`. `audio_path` is nullable; retention (`jobs/retention.py`), pin and `/audio` treat `None` as "no
  audio".
- **Upload:** `web/api/jobs.py:create_job` streams a multipart `file` part to `<job>/original.<ext>`
  (`_receive_upload`, `safe_extension`), parses JSON `options` (`_parse_options`, which also guesses title and date
  from the file name via `domain/filenames.py:parse_filename`), runs `preflight` (model check, ADR-0029), then calls
  `audio.ingest.probe` (ffprobe), which rejects non-audio. `audio.max_upload_mb` = 2048 (R7). The New meeting form
  is `web/templates/new.html` (file input `accept="audio/*,video/*,…"`, title, date, time, location, participants,
  tags, template picker, backend/model with cloud consent, diarize and speaker counts).
- **Transcript model:** `domain/transcript.py`: `Segment(id, start>=0, end>=0, speaker_label, speaker_name, text,
  words)`, `Transcript(segments, language, duration, model, diarized)`, `SpeakerMap`. `start`/`end` are required
  floats, so an untimed import needs a rule (Task 3).
- **Stages after transcription read artifacts:** `templates/stages.py:load_final_transcript` reads
  `ctx.artifacts["diarize"]` (`E_TRANSCRIPT_MISSING` otherwise); `load_named_transcript` prefers
  `transcript.named.json`. `speakers/stages.py:SpeakerSuggestStage` and `SpeakerConfirmationStage` (the "Name
  speakers" pause, `web/templates/speakers.html`, `web/api/speakers.py`) work on that transcript.
- **Prompt layout already tolerates missing times:** `templates/assembler.py:format_turns` and `task_cues` print a
  `[mm:ss]` stamp only when `Turn.start is not None`; `MeetingFacts.duration` prints "Length". Rule 5 of the system
  prompt says "Use only timestamps that appear in the transcript".
- **Writers:** `markdown/transcript_format.py` (companion: readable turns with `**[hh:mm:ss] Name:**` plus the hidden
  JSON-lines data block, ADR-0010; frontmatter `duration`, `mm3-transcription-model`, `mm3-diarized`),
  `markdown/readable_transcript.py` (R25), `templates/stages.py:WriteStage`. The review page
  (`review/workspace.py`) already hides the player when there is no audio (`audio_state`); transcript lines link to
  `#t=<seconds>`.
- **Nick's example (private):** a Grok voice-mode conversation exported as Markdown, 240 lines, about 33 KB,
  **no speaker labels, no times**: paragraphs separated by blank lines. User turns are speech-to-text with fillers
  ("um", "uh") and **repeated growing prefixes** (the same utterance appears 2-5 times, each a longer prefix of the
  last); assistant turns are polished prose, often **several paragraphs in a row**, sometimes preceded by a short tool-status
  line (the assistant saying it is checking or looking something up); there is a UI artefact line
  `2 / 2` (a regenerated reply counter). So strict alternation does not work: about 63 user and 44 assistant messages
  in the source, many consecutive.
- **Eval harness:** `tests/eval/run_eval.py`, `checker.py`, synthetic meetings in `tests/eval/meetings/*.yaml`.

## Tasks
1. **Parser interface** (`src/meetingmaster3/importing/`, new package; pure, no I/O beyond the bytes given):
   `ImportedConversation(turns: list[ImportedTurn], title: str | None, started_at: datetime | None, source_format:
   str, warnings: list[str])` and `ImportedTurn(speaker: str, role: Literal["user","assistant","other"] | None,
   text: str, start: float | None, confidence: float)`. `detect_and_parse(data: bytes, filename: str) ->
   ImportedConversation` picks a parser by content (not only the extension); each parser has an id. Phase 15l adds a
   Grok-share parser behind the same interface, so keep it small and documented in a new
   `docs/dev-guide/importing.md`. Decode as UTF-8 (BOM stripped), reject binary and over-size input with an `MM3Error`
   (`E_IMPORT_UNREADABLE`, `E_IMPORT_TOO_LARGE`; default limit `importing.max_mb` = 10).
2. **Parsers.**
   - *Timestamped:* `[h:mm:ss] Name: text` / `[mm:ss] Name:` / `**[hh:mm:ss] Name:**` (companion body; if the hidden
     data block is present, use it exactly), WebVTT (`<v Name>` voice tags or `Name:` prefixes) and SRT (speaker from a
     `Name:` prefix, else none). Times are kept; consecutive cues of the same speaker merge into one turn.
   - *Labelled AI chat:* headings or bold/plain prefixes naming a role (`User`, `You`, `Me`, `Human`, `Assistant`,
     `AI`, `Grok`, `ChatGPT`, `Claude`, `Gemini`, `Copilot`, and a custom name followed by a colon at line start when
     it repeats). Keep Markdown inside a turn (code fences, lists), strip export chrome (title line, "Share", "Copy",
     `N / N` counters).
   - *Unlabelled chat* (Nick's case): split on blank lines; drop UI artefacts (`^\d+ / \d+$`); **collapse growing
     prefixes** (a paragraph that is a prefix of the next, ignoring trailing punctuation and whitespace, is dropped);
     then assign roles with a scored heuristic (speech disfluencies and first-person questions → user; polished prose,
     long paragraphs, em dashes, Markdown, tool-status phrases → assistant), with **runs allowed** (an assistant
     answer may span paragraphs; a tool-status line joins the next assistant paragraph). Each turn gets a
     confidence. Measure it on the private example (Task 8) and on the synthetic fixtures; target at least 95 % of
     paragraphs correct before the user's fixes. If the heuristic cannot reach that, say so in the ADR and keep the
     preview fix-up as the safety net; an LLM-assisted role pass is a follow-up, not this phase.
3. **Untimed transcripts.** Decide and record in ADR-0052 "Phase 15k implementation" how a transcript with no times is
   represented. Default: `Transcript` gains `timed: bool = True` (the data block's header records it; old files parse
   as timed); untimed segments get `start = end = 0.0`; the assembler, task cues, companion and readable transcript,
   review page and Search omit clocks and `#t=` links when `timed` is false; `duration` is unknown (no "Length" line).
   The model is told there are no timestamps, so notes carry none. Update `note-format.md` and the round-trip tests
   (ADR-0012: existing files stay byte-identical).
4. **Import pipeline.** In `jobs/pipeline.py` add `IMPORT_STAGES`: `import_parse` ("Reading the file"), the existing
   `await_speaker_confirmation` (here: confirm who said what and name the speakers), `generate`, `write`.
   `import_parse` writes the parsed turns as a `Transcript` artifact (`diarized` = true when roles or names exist) that
   the later stages read; make `load_final_transcript` find it (for example by artifact name, not only `"diarize"`).
   No GPU, no ffmpeg, no audio; retention and pin do nothing for these jobs. Resume, cancel and SSE progress work as
   for meetings. `build_pipeline("import", …)` and the fake pipeline both work.
5. **API.** `POST /api/jobs` with `options.job_type: "import"` (or a separate `POST /api/imports`; pick one and record
   it) accepts a text file instead of audio: skip `probe`, keep the streamed save, size limit, CSRF, Host/Origin checks
   and `preflight`. Title: the file's first heading or the export's title if present, else the file-name guess; date:
   from the export or the file name, else today. Add a CLI: `mm3 import <file> [--template --backend --model --title
   --date --speaker user=Nick --speaker assistant=Grok --yes]` (`--yes` skips the confirmation pause).
6. **UI.** On New meeting, a clear choice between **Record or upload audio** (today's form) and **Import a transcript
   or AI conversation** (file input accepting `.md,.txt,.vtt,.srt`, plus title, date, participants, tags, template,
   backend/model and the same cloud consent; no diarization or speaker-count fields). The confirmation step shows the
   turns (first ~200, then "show all") with the speaker as a toggle per turn (keyboard-accessible), the low-confidence
   ones highlighted, and the speaker names to set (defaults: the user role → `participants[0]` or a new setting
   `importing.user_name`, default "Me"; the assistant role → the name detected in the export, else "AI"). Changes are
   validated server-side. The job page skips audio wording ("can I leave this page?" still applies). The review page
   shows "Imported from <format>" and no player. CSP-clean, HTMX, no new JS library.
7. **Output.** The note's frontmatter gets `mm3-source: import` and `mm3-source-format`; the companion omits
   `mm3-transcription-model` and records the parser; the readable transcript is written as usual. Everything else (file
   names R13, folder, markers, `mm3-id`, Meetings entry, Search indexing, Ask-AI) is unchanged. Rename (R28),
   template switch, section regeneration and **Update older notes** must work on an imported meeting (add tests).
8. **Private check.** Import Nick's example through the real app with local `qwen3:8b` and Default Notes; report the
   role accuracy before fixes, the number of fixes needed, and show Nick the note. Keep everything in
   `private-eval-15k/` and delete it at close-out (memory: private eval location).

## Out of scope
- Grok (or any) share links: Phase 15l. The *Create Project Plan* template: Phase 15m.
- Official JSON data exports (ChatGPT `conversations.json`, Claude data export), a paste box, `.docx`/PDF, audio plus
  text together, LLM-assisted role detection (record as follow-ups if useful).

## Tests
- Unit: each parser on synthetic fixtures in `tests/fixtures/imports/` (CC0, written for this phase, described in
  `tests/fixtures/README.md`): a labelled ChatGPT-style and a Claude-style Markdown export, an **unlabelled voice-mode
  export built to mimic the example's quirks** (growing prefixes, multi-paragraph answers, tool-status lines, `2 / 2`),
  `[hh:mm:ss] Name:` text, an MM3 companion, VTT with voice tags, SRT; detection picks the right parser; prefix
  collapsing; role heuristic accuracy on the unlabelled fixture (≥ 95 %); size/binary/encoding errors; Hypothesis: no
  parser raises anything but `MM3Error` on arbitrary text.
- Untimed round-trip: companion and readable transcript render/parse, old timed files byte-identical, assembler output
  without stamps (golden prompt for one template on an untimed transcript).
- Jobs: the import pipeline end to end with the fake LLM (parse → confirm → generate → write), resume after a kill at
  each stage, cancel, retention/pin no-ops, `E_JOB_TYPE` gone for `import`, CSRF on the new route, the speaker toggle
  validation.
- Web: New meeting choice, confirmation page, review page badge and no player; e2e (Chromium): import the unlabelled
  fixture, flip one turn, write, open the review page.
- `uv run pytest`, `ruff check`, `ruff format --check`, `mypy src`.

## Acceptance criteria
- In the real app, Nick imports `privacy project brainstorming.md`, fixes at most a handful of turns in the preview,
  names the speakers, picks Default Notes, and gets a note and transcripts in the vault with his name and the
  assistant's on the right turns and no invented timestamps.
- A `[hh:mm:ss] Name:` transcript (for example MM3's own `.txt` export of an existing meeting) imports with its times;
  clicking a line on the review page jumps to that time in the transcript (no player).
- The imported meeting appears on the Meetings page, is found by Search and Ask-AI, and can be renamed, switched to
  another template and regenerated.
- Uploading audio works exactly as before.

## Phase-specific docs
- ADR-0052: append "Phase 15k implementation" (parser ids and detection, the role heuristic and its measured accuracy,
  the untimed rule, the API shape). Spec §15: add **R32** (import of transcripts and AI conversations) and amend R18
  (the `timed` flag, `mm3-source*` properties) and R19 (the `import` job type).
- New `docs/user-guide/importing.md` (supported formats with examples, how to export a Grok/ChatGPT/Claude chat to
  Markdown, the preview and speaker fix-up, what is and is not kept), `docs/dev-guide/importing.md` (parser interface
  for 15l), `note-format.md`, `jobs-and-stages.md`, `configuration.md` (`importing.*`), `docs/MM3_ARCHITECTURE.md`,
  `docs/THREAT_MODEL.md` (untrusted text files: parser robustness, size limits, prompt injection from imported text is
  the same as from a transcript), README feature list, `CHANGELOG.md`.
- `prompts/MM3_phase-15l-grok-share-import.md` and `prompts/MM3_phase-15m-create-project-plan-template.md`: correct any
  names this phase changed (package, interface, settings, job-type field).

Then the standard close-out checklist.
