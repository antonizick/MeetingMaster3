# Phase 15d: Rename and re-date a meeting

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 15c · **Branch:** `phase-15d-rename-meeting` · **Worktree:** `../MeetingMaster3-phase-15d`

Part of the third tuning round (ADR-0030, ADR-0034; planned with `/phase-add`, split in ADR-0037). Nick
imported a meeting with the wrong date and title, and MeetingMaster3 has no way to fix that after import. A
meeting's title and date are spread across several vault files, their names and links, other notes' links, and
the app database. Fixing them by hand breaks links. This phase adds one safe, previewed operation that changes
them all and loses nothing. It runs after 15c because both change the review toolbar and the Meetings page.

## Read first
- `CLAUDE.md`, `prompts/_shared-instructions.md`, `docs/SPECIFICATION.md` §5 (naming), §15 (R11 damaged
  sections, R12 archive, R13 file names, R18 note format, R23, R25(a) readable transcript, and S3/S4/S8 in
  §15.3: sanitised rendering, **vault path confinement**, **atomic writes**).
- `docs/dev-guide/note-format.md` (normative note, companion and readable-transcript format).
- Phase Log entries for Phases 03, 04, 11, 15a, 15c and the 15c/15d/15e planning entry (2026-10-14).
- ADR-0010, ADR-0011, ADR-0012 (round-trip rules), ADR-0022 (audio copy into the vault), ADR-0025 (save model),
  ADR-0031 (readable transcript, upgrade path), **ADR-0037** (backlink policy).
- `review/upgrade.py` and `review/rename.py` (rename *speakers*) as the closest patterns: plan → preview → apply,
  archive first, SHA re-check, idempotent.

## Nick's request (verbatim intent, 2026-10-14)
"We need to add the ability to rename / re-title a meeting that has already been imported. For example, the
meeting '09-22 Interview Nick Antoncic - SOC Manager Cyber Defense Candidate' actually took place on August 18th,
and it was inaccurately named and titled during the import. We need a mechanism that will allow the user to rename
or re-title a previously imported meeting, whereby all the documentation, Obsidian notes, linking, etc. will be
'corrected' so that after it is renamed everything will be linked and work correctly and everything will be
titled accordingly. We need to ensure that no metadata or information is lost during this process."

## Decisions already made
- **Links in other vault notes are updated, after a backup** (ADR-0037). The preview lists every other note that
  links to the meeting's files. Apply rewrites those links (keeping `|alias`, `#heading` and `^block` parts),
  copies each changed note to a backup first, and writes atomically. This matches what renaming inside Obsidian does.
- Defaults (follow them, or justify a change in this phase's ADR):
  - **What can change:** the title, the date, and optionally the time. Changing only one of them is fine. The
    `mm3-id` never changes, and neither does the meeting's content (sections, transcript text, speakers, extra
    properties, the user's own text).
  - **Prose is not rewritten.** Section text that mentions the old title or date stays as it is. The preview
    points out such mentions ("3 mentions of '09-22' inside sections: edit or regenerate them if needed").
  - **Folder:** if the note sits in the folder that `vault.output_subfolder` gives for the *old* date (for example
    `MM3.Meetings/2026/`) and the new date gives a different one, the meeting's files move to the new folder. If
    the user moved the note somewhere else, the files stay in that folder.
  - **Archives** (`<folder>/Archive/<stem>.<stamp>.md`, section archives) are renamed to the new stem with the same
    stamps, and their MM3 link properties are updated. Their bodies stay historical.
  - **Collisions:** if a target name exists, refuse with a clear message (no silent ` (2)`). A case-only rename
    works (rename through a temporary name).
  - **Backups** of other users' notes go to app data (`<data_dir>/rename-backups/<timestamp>-<mm3-id>/<vault-relative
    path>`) with a `manifest.json` (old/new names of every file, every link changed, the DB rows before and after).
    They do not go into the vault. Enough is recorded to undo by hand. An **Undo last rename** is a stretch goal
    (log it if skipped).
  - **Unsaved edits:** renaming needs a clean editor (`requireClean`). After a rename, the workspace reloads at the
    new path and the stored base snapshot and draft are re-keyed.

## Goal
From the review page (and `mm3 meetings rename`), the user changes a meeting's title and/or date, sees exactly
what will change, applies it, and ends up with every MM3 file renamed, every link inside and outside MM3's files
still resolving in Obsidian, the database agreeing, and nothing lost. An interrupted rename can always be completed
or rolled back.

## What exists (verified 2026-10-14; re-check before relying on it)
- **Names** (`vault/naming.py`): stem `YYYY-MM-DD - <sanitize_title(title)>`. Note `<stem>.md`, companion
  `<stem>.transcript.md`, readable transcript `<stem> (Transcript).md` (`readable_names`, which can also be
  ` (Transcript 2).md`…; find it with `vault/readable.py:find_readable`, which checks `mm3-id`). `allocate_note_paths`
  gives the first free stem for a new note.
- **Where the title and date live in a meeting** (real example `MM3.Meetings/2026/2026-08-13 - Interview Nick for
  SOC Management Role*`):
  - note frontmatter: `title`, `date` (ISO; midnight when the time is unknown), `mm3-transcript: "[[<stem>.transcript]]"`;
  - note body: `# <title>` H1; header lines `- **Date & Time:** …` and `- **Transcript:** [[<stem> (Transcript)|Read
    the transcript]]` (`markdown/note_writer.py`: `render_header`, `TRANSCRIPT_LINE_PREFIX`,
    `with_transcript_link`); possibly an audio link if `privacy.copy_audio_to_vault` is on (`jobs/vault_audio.py`,
    ADR-0022, which names the copy after the note stem);
  - companion frontmatter: `mm3-note: "[[<stem>]]"`, and the H1 `# Transcript: <title>`
    (`markdown/transcript_format.py`);
  - readable transcript frontmatter: `mm3-note`, `mm3-transcript`. It is generated from the companion by
    `vault/readable.py:refresh_readable`, so regenerate it rather than editing it;
  - archives in `<folder>/Archive/` (`vault/archive.py`: `note_archive_path`, `section_archive_path`, stamp
    `YYYYMMDD-HHMM`); for example `2026-08-13 - Interview Nick for SOC Management Role.20261014-0921.md`.
- **Database** (`storage/migrations.py`): `jobs.title`, `jobs.meeting_date`; `recent_meetings` (PK `note_path`,
  `transcript_path`, `mm3_id`, `title`, `date`, `job_id` since migration 3); the job folder's `written.json`
  (`WRITTEN_FILE`, has `mm3_id` and `note_path`; `review/workspace.py:find_job`). Feedback rows, drafts and base
  snapshots (`review/store.py`) and voiceprints are keyed by `mm3_id` or job id, so they need no change. Check that
  the store's base snapshot is still valid after the files change.
- **Writes:** `vault/io.py` (`write_checked` with an expected SHA, atomic temp + rename), `vault/paths.py`
  (confinement, symlink checks). Never write outside the vault root, and never follow a symlink out of it.
- **Scanning the vault** for MM3 notes: the picker and `review/upgrade.py` (they skip archives and transcripts by
  `mm3-kind` / suffix). There is **no** backlink scanner yet.
- **The example meeting** in Nick's vault: `MM3.Meetings/2026/2026-09-22 - 09-22 Interview Nick Antoncic - SOC
  Manager Cyber Defense Candidate.md` (`mm3-id 4cbf8a4b-…`), with `.transcript.md`, `(Transcript).md` and an archive
  `…20261012-1240.md`. Nick says it took place on **2026-08-18**. The title still begins with the import-time
  "09-22 " prefix. Also note: a separate, non-MM3 file `09-22 Interview Nick Antonizick - SOC Manager Cyber Defense
  Candidate.md` (a Plaud export) sits in the same folder and is **not** part of the meeting. Do not touch it.
  **Update from Phase 15e (2026-10-14):** the vault now also has a separate MM3 meeting
  `2026-08-18 - Cybersecurity Technical Interview and Role Alignment Follow On Discussion.md` (processed that day),
  and Nick confirmed that it, not the 09-22 meeting, matches the 18 August Plaud sample, while the 09-22 meeting
  matches the sample dated 2026-09-22. **Ask Nick whether the 09-22 meeting needs re-dating at all** before using
  it as the example; if not, rename only its title (drop the "09-22 " prefix) or use a copy in a scratch vault.

## Tasks
1. **Plan** (`review/retitle.py`, pure, no writes): `plan_retitle(vault_root, note_path, new_title, new_date,
   new_time=None, settings) -> RetitlePlan`. It lists every file rename/move (note, companion, readable, archives,
   vault audio copy), every in-file change as a before/after (frontmatter keys, H1, header lines, MM3 link
   properties), every **backlink** in other vault notes, the DB updates, and warnings (old title or date mentioned
   in prose, a target name that exists, a note moved by the user, damaged sections per R11, a missing companion).
   Re-read and SHA-check every input. Unknown frontmatter keys, comments and line endings must keep their bytes
   (ADR-0011, ADR-0012); reuse the frontmatter editor that keeps raw chunks.
2. **Backlink scanner** (`vault/links.py`): find links to any of the meeting's stems across the vault's `.md` files
   (skip `.obsidian/`, `.trash/`, MM3 archives and the meeting's own files, which the plan handles). Handle
   `[[stem]]`, `[[stem|alias]]`, `[[stem#heading]]`, `[[stem#^block]]`, `![[stem]]` embeds, path-qualified
   `[[folder/stem]]`, and Markdown links `[text](<folder/stem.md>)` / `[text](folder/stem%20x.md)`. Skip links inside
   code fences and inline code. Match the way Obsidian resolves a link (by name across the vault; path-qualified
   when names are ambiguous). A link that would become ambiguous after the rename must stay unambiguous (use a
   path-qualified link). Rewrite only the link target and keep everything else byte for byte. Bound the scan's cost
   (file count/size limits with a warning) and keep it off the event loop.
3. **Apply with a journal** (`apply_retitle`): before the first change, write a journal to app data (the plan + the
   backup manifest), then back up the changed external notes, then do the steps in a fixed order (write new
   contents to the new names atomically → re-point the DB → remove the old names). Each step is idempotent. On
   start-up (and before any new rename), an unfinished journal is either completed or rolled back, and the user is
   told which. Re-check every SHA right before writing, and stop with `E_NOTE_CHANGED` if Obsidian or the user changed
   a file since the preview. Regenerate the readable transcript with `refresh_readable`.
4. **Database:** update `jobs.title`/`meeting_date` (when the job exists), the `recent_meetings` row (PK change:
   insert new + delete old in one transaction), the job's `written.json` `note_path`, and anything else that stores
   a path (`grep -rn "note_path\|transcript_path" src/`).
5. **UI** (review page): a **"Title & date…"** button in the toolbar (clearly different from "Rename speakers…"). It
   opens a `<dialog>` with the title (prefilled), date and optional time, and a preview that shows the file renames,
   the in-file changes as a diff, the "N links in M other notes will be updated" list (expandable) and the
   warnings. Apply needs CSRF. Show the result as a toast with the backup location, then reload at the new path. Read-only
   and note-only workspaces explain what is possible (for example, the companion is missing, so the companion is
   left alone and that is listed). On **Meetings**, a row action or link to the same dialog is optional; record the
   choice.
6. **CLI:** `mm3 meetings rename <mm3-id|path> [--title …] [--date YYYY-MM-DD] [--time HH:MM] [--dry-run]
   [--yes]`, printing the same plan. It uses the same functions as the UI.
7. **Security:** every path is resolved and confined to the vault (S4), symlinks are refused, titles are sanitised
   (R13), the rendered preview is escaped (S3), the routes are CSRF-protected (S2), and backups are written with
   the same care as other app data (no world-readable permissions beyond the defaults used elsewhere).

## Out of scope
- Rewriting prose inside sections or regenerating the note (the preview only points at mentions).
- Renaming meetings in bulk.
- Changing `mm3-id`, speakers or template.
- Syncing with Obsidian's own rename (Obsidian may be open: the SHA checks cover concurrent edits).

## Tests
- Unit (`tmp_path` vault): plan contents for title-only, date-only, date across a year (folder move), a case-only
  change, a user-moved note (no folder move), no companion, a readable transcript at ` (Transcript 2).md`, archives
  present, a vault audio copy present, a collision refused. Byte preservation: unknown keys, comments, CRLF, BOM and
  user text unchanged (Hypothesis over generated notes, if cheap). Link scanner and rewriter: every link form above,
  aliases, headings, blocks, embeds, Markdown links with `%20` and `<…>`, links in code fences ignored, an ambiguous
  name made path-qualified, links to the companion and readable stems. Journal: kill after each step (simulated
  exception) → recovery completes or rolls back to a consistent state, and a second run is a no-op.
- Web: preview/apply routes (CSRF, `E_NOTE_CHANGED` after a concurrent edit, collision, read-only), the workspace
  redirect to the new path, the DB rows after the rename, the base snapshot and draft after the rename.
- CLI: `--dry-run` output and the apply path.
- e2e (fake pipeline, Chromium): write a meeting, add a second vault note linking to it, rename and re-date it
  across a year, then the note opens at the new path, the second note's link points at the new name, the readable
  transcript and companion links work, Meetings shows the new title and date, and axe is clean on the dialog.

## Acceptance criteria
- With Nick's explicit OK in the session (after showing him the dry run), his example meeting is renamed to date
  **2026-08-18** with the title he chooses (ask him; for example drop the "09-22 " prefix). Afterwards, in
  Obsidian (Nick checks), the note, the readable transcript link, the companion link and any backlinks all
  resolve, nothing is missing (compare frontmatter keys, section contents and transcript bytes before and after),
  and the backup folder and manifest exist. If he declines, demonstrate on a copy of the meeting in a scratch vault.
- The review page and Meetings show the new title and date, the recording still plays, and Keep forever still
  works.
- An interrupted rename (simulated) is recovered on the next start.
- `uv run pytest`, `ruff check`, `ruff format --check` and `uv run mypy src` pass, the e2e suite passes, and the
  `mypy src tests` error count is no higher than on `main`.

## Phase-specific docs
- `docs/SPECIFICATION.md` §15: amendment **R28** (renaming and re-dating a meeting: what changes, what never
  changes, backlinks, the journal). Take the next free number if R28 is already used on `main`.
- ADR (next free number): the plan/journal design, the backlink matching rules, the folder-move rule, and the
  backup location.
- `docs/dev-guide/note-format.md` (what a rename touches), `docs/user-guide/reviewing-and-editing.md` (Title &
  date), the CLI reference, `docs/THREAT_MODEL.md` (a new write path across the whole vault), `docs/ARCHITECTURE.md`,
  `CHANGELOG.md`.
- `prompts/phase-16-release.md` if screenshots or the feature list should mention it.

Then the standard close-out checklist.
