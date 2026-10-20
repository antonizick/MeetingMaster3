# Phase 15a: Pre-operational tuning, round 1

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 15 · **Branch:** `phase-15a-pre-op-tuning` · **Worktree:** `../MeetingMaster3-phase-15a`

This is the first **interim tuning round** between Phase 15 and Phase 16 (ADR-0030): Nick ran real meetings
through the app and asked for five changes before publication. Rounds are numbered 15a, 15b, 15c… and each
one has its own prompt, row, Phase Log entry and branch. Phase 16 depends on every round.

## Read first
- `CLAUDE.md`, `prompts/MM3_shared-instructions.md`, `docs/MM3_SPECIFICATION.md` §15 (especially R9, R13, R24
  and the S1–S8 controls in §15.3).
- Phase Log entries for Phases 03, 09, 10, 11, 13 and 15, and both "Pre-release fix" entries
  (2026-10-12).
- `docs/dev-guide/template-format.md`, `docs/user-guide/getting-started.md`, ADR-0009 (companion
  transcript data block), ADR-0025 (review workspace writes), ADR-0029 (model check).
- Owner question **Q6** (logo publication) in `MM3_IMPLEMENTATION_PLAN.md`. Ask Nick at the start of
  the session if it is still open. Task 6 depends on the answer; the other tasks do not.

## Nick's feedback (verbatim intent, 2026-10-12)
1. Keep the companion transcript as it is, but also write a **human-readable transcript** Markdown file into
   the vault, laid out like the review screen's transcript, with speaker names **colour-coded with Obsidian
   highlighting**.
2. Selecting `09-22 Interview_ Nick Antoncic - SOC Manager _ Cyber Defense Candidate.mp3` left the date at
   *today*. A file name with only a month and a day must fill in the date, **assuming the current year**.
3. Summaries are good but too short. The existing summary stays and is renamed **Summary Succinct**. Every
   default template gains a **Summary Detailed** below it: typically three paragraphs, **never fewer than two**.
   Meetings that were already processed must be updated with the new section too.
4. On the progress page it is unclear whether leaving the page interrupts processing. Add a subtle note that
   says what happens.
5. Use `/home/nick/Pictures/wiz.jpg` as the basis for a logo: cropped and reframed (for example a rounded
   rectangle), small to medium size, in the upper-left corner of the navigation pages, and **hidden on meeting
   pages** (job progress, Name Speakers, review), where screen space matters most.

## Goal
Make the app's output and first impressions match what Nick wants from daily use: readable transcripts in the
vault, correct dates from file names, richer summaries (backfilled into existing notes), clear expectations
while a job runs, and a product logo. Do all of it without weakening any Phase 15 security control.

## What exists (verified 2026-10-12; re-check before relying on it)
- **Companion transcript:** `markdown/transcript_format.py` writes `YYYY-MM-DD - Title.transcript.md`. It
  holds readable `**[hh:mm:ss] Name:** text` turns plus a hidden `<!-- mm3:transcript-data v1 … -->` JSON
  block, which is the source of truth (ADR-0009). In Nick's 31-minute meeting the data block is about
  400 of 540 lines and 230 KB. Obsidian's Live Preview shows it, and turns run for minutes as one line,
  so the file reads poorly. **Do not change this format.**
- **Review screen transcript** (the layout Nick likes): `review/workspace.py:transcript_view` groups segments
  into turns (`domain/transcript.py:group_turns`), with colour index `i % SPEAKER_COLOURS` per label in
  first-appearance order. `web/templates/review.html` renders the timestamp (`clock`: `m:ss`, or `h:mm:ss`
  from one hour) and the name on one line, then the text below. Colours are in `web/static/app.css`
  (`.spk-0` … `.spk-7`, light and dark variants).
- **Text export:** `exporting.py:transcript_to_text` (one `[h:mm:ss] Name: text` line per turn); the meeting
  zip contains the note, the companion and that `.txt`.
- **Speaker renames** rewrite the companion (`markdown/transcript_format.py:rename_speakers`,
  `review/rename.py`). The companion is also written by the job's write-to-vault stage, by
  `link-transcript` and by reprocessing.
- **File-name parsing:** `domain/filenames.py:parse_filename` only knows year-first dates
  (`2026-10-11`, `20261011_143000`). `/ui/parse-filename` (`web/pages.py`) feeds `app.js:prefill`, which never
  overrides a date the user edited. `web/api/jobs.py:create_job` falls back to the same guess server-side.
- **Templates:** 22 built-ins in `src/meetingmaster3/starter_templates/`. 19 have
  `{id: summary, title: Summary, kind: narrative}` first, with a 1–2 sentence prompt. **board-governance-minutes,
  just-the-facts and key-takeaways-next-steps have no summary section.** `templates/loader.py:install_builtins`
  copies the built-ins into the vault's templates folder and never replaces a copy the user changed.
- **Section editing building blocks:** section markers `<!-- mm3:section:<id> -->` (`markdown/sections.py`),
  `templates/regenerate.py` (generate one section from the companion), `markdown/editing.py`, the review
  routes `append-section` / `regenerate` / `archive-section` (`web/review.py`), `vault/archive`, and the
  SHA-256 + `mm3-id` checks of ADR-0025.
- **Jobs:** run in the server process. Closing the browser does not stop them (Phase 15 verified).
  Stopping the server marks running jobs `interrupted` (`jobs/runner.py:recover`), and they can be resumed.
  A job waits at *Confirm speakers* for the user. The page is `web/templates/job.html` +
  `partials/job_panel.html`.
- **Layout:** `web/templates/base.html` has `<a class="brand" href="/">MeetingMaster3</a>` in `.site-header`.
  ImageMagick (`/usr/bin/magick`) is on the host, and Pillow is in `uv.lock` as a transitive dependency.

## Tasks

### 1. Human-readable transcript in the vault
1. Add a pure renderer (for example `markdown/readable_transcript.py`) that builds the readable file from a
   `CompanionTranscript` (or `Transcript` + `SpeakerMap`). It must never parse the readable file back.
   Layout per turn, matching Nick's screenshot of the review pane:
   ```
   <span style="color: var(--text-muted)">04:14</span> <mark style="background: rgba(134,239,172,.35)">**Nick**</mark>
   Yes, in the… Yeah, so there's a… Stand by. Yeah, so in the … project…

   <span …>04:39</span> <mark style="background: rgba(253,186,116,.35)">**Michelle**</mark>
   Oh, that came through as plain text.
   ```
   - Keep the timestamp, name, line break, text and blank-line rhythm. The exact markup is yours to
     choose, but it must render well in Obsidian **Reading view and Live Preview, in both light and dark
     themes**. Coloured `<mark style="background: …">` is the usual way to get a coloured Obsidian
     highlight; `==…==` is single-colour only.
   - Each speaker keeps one colour, using the same palette order as the review screen, so the colours match
     the app. Unnamed labels (`SPEAKER_03`) get a neutral style.
   - Clock format matches `review/workspace.py:clock` (`m:ss`, or `h:mm:ss` from one hour).
   - Turns longer than about 90 seconds are split into paragraphs at segment boundaries, without repeating
     the speaker heading, so a 3-minute monologue is not one wall of text. Record the threshold in the ADR.
   - Escape or neutralise transcript text so spoken words can never become HTML, wikilinks, embeds, tags
     or section markers (S3; reuse the companion writer's escaping).
2. **File and links.** Recommended name: `YYYY-MM-DD - Title (Transcript).md`, next to the note. The
   name must not end with `.transcript.md`, so no scanner mistakes it for the companion. Choose the name
   through `vault/naming.py` and record it in the ADR. Frontmatter: `mm3-id`, `mm3-kind:
   readable-transcript`, a wikilink to the note and to the companion, `duration`, `language` and the
   speakers. The first body line is a short muted notice: generated by MeetingMaster3, edits here are
   replaced, and the full-fidelity copy is in the companion. Link the readable transcript from the note,
   preferably the link a person clicks; keep the companion link in frontmatter. Every vault scanner
   (Recent, Open note, re-open, prune orphans, template library, export all, rename) must ignore or
   correctly classify the new file; add a test for each.
3. **Lifecycle.** Rewrite the readable file whenever the companion is written: job write-to-vault, speaker
   rename (review), link-transcript, reprocess. Use `vault/io.atomic_write_text` and confinement. Phase 15
   rule: never silently replace a file MM3 did not write. If a file with that name exists without this
   meeting's `mm3-id`, pick a free name (or report a conflict); never overwrite it. Add a setting
   `notes.readable_transcript` (default `true`) in the pydantic model, Settings → Notes and
   `docs/user-guide/configuration.md`.
4. **Exports.** Add the readable file to the meeting zip. Align `transcript_to_text` with the same layout
   (timestamp and name on one line, text below, blank line between turns), because Nick says the `.txt`
   "closely aligns" and should match. Keep plain text: no markup in the `.txt`.

### 2. Dates from file names without a year
1. Extend `domain/filenames.py:parse_filename` to recognise a month and day without a year, and, while
   you are there, common US forms that do carry a year:
   - `09-22`, `9-22`, `09_22`, `09.22`
   - `Sep 22`, `Sept 22nd`, `September 22`, `22 Sep`
   - `09-22-2026`, `9-22-26`
   Year-first dates keep priority. Month-first is the default order (Nick is in the US). Read the date
   day-first only when the first number is above 12 and the second is not. Reject impossible dates
   (`02-30`) and anything glued to other digits. Do not mistake times (`14-30`), version numbers (`v2-10`),
   `1-on-1` or counts for dates; each of these needs a test.
2. **Year inference:** use the current year in the server's local time zone. If that puts the date more
   than one day in the future, use the previous year, because a recording cannot come from the future.
   For example, `12-30` uploaded on 2027-01-02 means 2026-12-30. Nick asked for "assume current year";
   this is the only exception. Record it in the ADR and tell Nick about it in the final message.
3. Remove the matched date from the guessed title. `09-22 Interview_ Nick Antoncic - SOC Manager _ Cyber
   Defense Candidate.mp3` must give the title `Interview Nick Antoncic - SOC Manager - Cyber Defense
   Candidate` (or similarly clean; no stray `_` or doubled separators) and the date `<current year>-09-22`.
4. UI: when the date comes from the file name, show a small muted hint under the Date field ("From the file
   name"). Hide it as soon as the user edits the date. It works for audio and video files alike. The
   existing rule that a user's edit always wins stays. Keep the server-side fallback in `create_job` in sync.
5. Table-driven unit tests for every form above, the year rollover (freeze "today") and the reported file
   name. Add an e2e check that picking that file name fills the date.

### 3. Summary Succinct + Summary Detailed in every default template
1. In all 22 built-in templates:
   - Keep section id `summary`, so existing notes, regeneration and ratings keep working. Change its
     title to **Summary Succinct** and leave its prompt alone.
   - Add `{id: summary-detailed, title: Summary Detailed, kind: narrative, max_tokens: <enough for ~3
     paragraphs, about 1200>}` directly below it.
   - The three templates without a summary (board-governance-minutes, just-the-facts,
     key-takeaways-next-steps) get both sections. Put them at the top, unless that reads badly for formal
     minutes; for board minutes, after Attendance & Quorum is acceptable. Log the choice.
   - Bump whatever version or hash the loader uses, so that unchanged vault copies of the built-ins are
     upgraded by `install_builtins`. Copies the user changed are left alone, and the template library
     shows that a newer built-in exists. Add a test for both cases.
2. Write the `summary-detailed` prompt for each template, in the voice of that template's `_system` block
   (interview notes are an assessment narrative, board minutes are formal and neutral, a stand-up is
   brisk). Shared requirements:
   - Prose only, no bullets or headings.
   - **Typically three paragraphs and never fewer than two.** Roughly: context and purpose; the main
     threads of discussion with who said what; outcomes, decisions and open questions.
   - Grounded only in the transcript, with names as mapped, and no invented facts.
   - `[mm:ss]` references follow the template's existing convention.
   - Must stay useful on long meetings that go through map-reduce: check that the reduce input carries
     enough material for a multi-paragraph narrative, and adjust `templates/mapreduce.py` if it does not.
3. Enforce the floor in code. Add a post-processing check (`templates/postprocess.py` or the generator)
   that counts paragraphs in `summary-detailed`. Fewer than two triggers one retry with a firmer
   instruction. If the retry is still short, keep the output and add a job warning; never pad or
   fabricate. Unit-test the check with the fake backend.
4. **Eval:**
   - Add checks to `tests/eval/`: 2–4 paragraphs, no list markers, roughly 150–500 words, and the
     succinct summary stays at 1–2 sentences.
   - Run `MM3_EVAL_MODEL=qwen3:8b uv run pytest tests/eval -s` across all 22 templates and update
     `tests/eval/baseline.json` (the baseline is currently 71/71; report the new numbers).
   - Measure how much generation time the extra section adds on a 60-minute meeting (Nick's recordings via
     `MM3_PRIVATE_TEST_AUDIO`, already approved for timing only) and update `docs/PERFORMANCE.md` and the
     pre-job estimate if it moves noticeably.
5. Spec: add amendment **R25** to SPECIFICATION §15 (readable transcript, two summaries, date inference),
   and update the template catalogue and `docs/dev-guide/template-format.md`. Explain in the user guide how
   to add the two sections to a user's own templates (their custom templates are not changed
   automatically).

### 4. Bring existing notes up to date (backfill)
Nick asked for meetings he has already processed to gain the new section. Build a reusable upgrade path,
not a one-off script:
1. A core module (for example `notes/upgrade.py` or inside `review/`) that scans the vault for MM3 notes
   (`mm3-id` frontmatter) and plans, per note:
   - add `summary-detailed` when the note's template now has it and the note does not;
   - rename the `summary` heading to "Summary Succinct", **only if it is still the default "Summary"** (a
     user's own heading wins);
   - write the readable transcript if it is missing.
   Notes without a companion transcript are skipped with a reason. The plan is computed without writing
   anything.
2. Applying a note:
   - Generate the section from the companion transcript and the note's speaker names, using the
     regeneration path (`templates/regenerate.py`) and the default backend and model. The ADR-0029
     preflight applies, and so do the cloud-consent rules (S6): a cloud default must ask, and a local model
     is the recommended choice.
   - Insert the new section right after `summary`.
   - Archive the previous note version (`vault/archive`).
   - Re-check `mm3-id` and the file's SHA-256 just before an atomic write, so an edit in Obsidian during the
     run is never overwritten (skip that note and report it).
   - Make it idempotent: running it twice changes nothing the second time.
3. UI: put an **Update older notes** card in a sensible place (Recent or Settings → Notes):
   - Show how many notes need which change, the model that will be used, and a time estimate.
   - The user runs it in the background with progress, can cancel, and gets a per-note result list with
     links to each note.
   - Offer a preview of one note's new section before running all of them.
4. CLI: `mm3 notes upgrade [--dry-run] [--note PATH] [--model …]` for headless use and for Docker.
5. **Live run on Nick's vault**, which currently holds two meetings in `~/Documents/MM3.Meetings/2026/`.
   First run a dry run and show Nick the plan and a preview of one generated section; apply only after he
   says yes in the session. Confirm that the archive copies exist afterwards. Never commit the notes or their
   content.

### 5. "Can I leave this page?" note on the progress page
1. In `partials/job_panel.html`, add a single subtle line (muted text with a small info icon; not an
   alert, not a toast) at the top or bottom of the panel. Its wording depends on the state:
   - **queued or running:** you can leave this page or close the browser; processing continues on this
     computer, and you can come back any time from **Recent**. It stops only if the MeetingMaster3 server
     stops or the computer sleeps or shuts down; the job can then be resumed from where it stopped.
   - **waiting at Confirm speakers:** the job is paused until you name the speakers here; you can come
     back later from Recent.
   - **interrupted, failed, cancelled or done:** no note, or one matching the state (the existing banners
     already cover these).
   Verify every claim against the code before writing it, including what happens on suspend/resume
   during GPU work (test it if it is safe to; otherwise word it carefully).
2. Keep the browser tab title up to date with the stage and progress (for example `42% · Transcribing ·
   MeetingMaster3`, and `✓ Notes ready` when done), so a tab Nick left in the background tells him the
   state. Use one polite live update only, with no extra announcements.
3. Add the same expectation, in one sentence, to the getting-started guide.

### 6. Logo from `wiz.jpg` (Q6 must be answered first)
1. The source (934×672 JPEG with GIMP EXIF data) is a photo-composite showing Nick as a wizard with a
   crystal ball at a boardroom table, with other people in the background. Crop it to the wizard's head and
   crystal ball (roughly square), with no recognisable background faces.
2. Produce a rounded-rectangle logo with ImageMagick or Pillow:
   - Optimised WebP plus a PNG fallback at 1× and 2× for a display height of about 36–44 px.
   - All metadata stripped (`-strip`).
   - Add a script (`scripts/make_logo.py` or a documented one-line command) that rebuilds the logo from a
     source path passed as an argument.
   - **Never commit the original image.** What is committed, and where, depends on Q6:
     - committed → `web/static/brand/`;
     - local-only → a git-ignored `branding.logo_path` setting, with a neutral default logo in the repo.
3. In `base.html`, show the logo to the left of the "MeetingMaster3" brand text on the navigation pages:
   home/new, Recent, Open, Templates (and the editor), Settings, setup and error pages.
   - Hide it on meeting pages (`job.html`, `speakers.html`, `review.html`/`/meetings/{id}`). Use a block or
     context flag (for example `show_logo`), not CSS that still downloads the image.
   - Use `alt=""` (the link already has text) and set the size in CSS so nothing shifts while it loads.
   - It must look right in light and dark themes and at phone width.
   - Do not change the CSP: the logo is served from `/static`.
4. Optionally offer Nick a favicon version, but keep `favicon.svg` unless he says yes.
5. `THIRD_PARTY_NOTICES.md` / `NOTICE`: record where the logo came from and its licence, as Nick answered
   in Q6 (logos are often excluded from the code licence). Phase 16 screenshots will include it.

### 7. Verification on the real app
- Restart a server from the worktree on a spare port, against Nick's real config.
- Process one short private clip end to end with qwen3:8b and check four things: the readable
  transcript in Obsidian (Nick opens it: ask him to look at Reading view and Live Preview in light and
  dark), both summaries, the date taken from a month-day file name, and the leave-page note. Logo
  visibility per page (screenshots or browser automation) is also part of this check.
- Then run the backfill (Task 4.5).
- Stop the server, and delete any scratch audio or vault files you created.

## Out of scope
- Changing the companion transcript format or its data block.
- Changing user-made templates automatically (document how instead).
- Browser notifications or sounds when a job finishes, which would need a permission prompt; record them as an idea.
- New templates, new backends, publication (Phase 16).

## Tests
- Unit:
  - readable renderer (layout, colours stable per speaker, paragraph splitting, escaping of hostile text
    such as `<script>`, `[[link]]`, `![[embed]]`, `#tag`, `<!-- mm3:section:x -->`, unnamed speakers,
    hour-long clocks);
  - file-name dates (Task 2.5);
  - template schema (every built-in has `summary` then `summary-detailed`, titles exact);
  - the paragraph-floor retry;
  - the upgrade planner and applier (idempotence, user-renamed heading kept, concurrent edit skipped,
    missing companion skipped, archive written, consent required for cloud);
  - scanners ignoring the readable file;
  - `install_builtins` upgrade rules.
- Web: tests for the upgrade card and routes, the job-panel note in each state, `show_logo` on every page
  type, and the parse-filename hint.
- e2e (fake pipeline): upload with a month-day file name → date filled; the job page shows the note and
  updates the tab title; the review page has no logo and the home page does; axe still clean on every page
  Phase 15 covered.
- Eval: Task 3.4.

## Acceptance criteria
- Every new meeting writes a readable transcript that Nick has looked at in Obsidian and approved. A speaker
  rename updates it, and every vault scanner ignores it.
- `09-22 Interview_ … .mp3` pre-fills `<current year>-09-22` and a clean title, and the year rollover rule
  is tested.
- All 22 built-in templates produce Summary Succinct and Summary Detailed. The eval shows the detailed
  summary at 2 or more paragraphs on every template with qwen3:8b, and the baseline is updated with no
  regressions in other checks.
- Nick's existing notes have Summary Detailed and readable transcripts, after his approval of the dry run,
  with archives kept.
- The progress page states clearly and quietly whether leaving is safe, in every job state.
- The logo appears on the navigation pages only, per Q6, with no original image in git.
- `uv run pytest`, `ruff check`, `ruff format --check` and `uv run mypy src` pass, the e2e suite passes,
  and the `mypy src tests` error count is no higher than on `main`.

## Phase-specific docs
- `docs/MM3_SPECIFICATION.md` §15: R25.
- ADR-0031: readable transcript name and format, date inference rules, the two summaries and the upgrade
  path. Add an ADR for the logo too if Q6 changes what is committed.
- User guide: getting-started (readable transcript, leaving the page, the date hint, Update older notes),
  configuration (`notes.readable_transcript`, `branding.logo_path` if added), template-format (two
  summaries).
- `docs/MM3_ARCHITECTURE.md`: new modules.
- `docs/PERFORMANCE.md`: extra generation time.
- `CHANGELOG.md`, `THIRD_PARTY_NOTICES.md` / `NOTICE` (logo).
- Phase 16 prompt: screenshots now show the logo, the two summaries and the readable transcript; and
  whatever Q6 decided about publishing the logo.

Then the standard close-out checklist.
