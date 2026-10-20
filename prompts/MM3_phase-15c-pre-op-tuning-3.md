# Phase 15c: Pre-operational tuning, round 3

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 15b · **Branch:** `phase-15c-pre-op-tuning` · **Worktree:** `../MeetingMaster3-phase-15c`

This is the third **interim tuning round** (ADR-0030; planned with `/phase-add`, ADR-0034). After 15b, Nick
used the review screen and the Recent page every day and asked for a set of changes before publication. Two other
requests from the same round have their own phases: **15d** (renaming a meeting, which runs after this phase because
it touches the same review files) and **15e** (a new topic-based template, which can run in parallel with this
phase). See ADR-0037. Phase 16 depends on all three.

## Read first
- `CLAUDE.md`, `prompts/MM3_shared-instructions.md`, `docs/MM3_SPECIFICATION.md` §15 (R8 retention, R23 review
  workspace, R26, and the S1–S8 controls in §15.3, especially S2 CSRF/Origin, S3 sanitised rendering and S4 vault
  path confinement).
- Phase Log entries for Phases 10 (job progress, SSE), 11 (review workspace), 15b, the pre-release fix
  "removing Recent 'Notes in your vault' entries", and the 15c/15d/15e planning entry (2026-10-14).
- ADR-0019 (HTMX partials, SSE as a trigger, Alpine CSP build), ADR-0024, ADR-0025, ADR-0036, **ADR-0037**.
- `docs/user-guide/reviewing-and-editing.md`, `docs/user-guide/getting-started.md`.

## Nick's request (verbatim intent, 2026-10-14)
1. "While utilizing the switch template function, can we provide the user with some better feedback during
   processing? Ideally, there would be a moving, updating progress bar aligned with the amount of time that has
   progressed and the estimated time to completion. Also, ideally there would be a visual cue with some amount of
   motion so that it's clear that no process has locked up."
2. "When the user is on the review and edit page, there should be a button or option somewhere to download a copy
   of the audio file."
3. "When the user is on the Review and Edit page, near the top of the left pane with the audio material there
   should be somewhere that very subtly states the size of the stored audio file (even if it's only a mouse-over
   pop-up). That way the user is making an informed decision when they decide whether or not to retain the audio
   file forever or abide by the default retention period."
4. "On the review and edit page, the text of the preview button should change (appropriately) depending on whether
   the right pane is in edit or preview mode."
5. "The menu screens 'Recent' and 'Open a Note' are somewhat redundant. Rename 'Recent' to 'Meetings' (menu link and
   its page title/heading). Also update the 'Notes in your vault' part of the page: keep the content exactly the way
   it is, but put it in a light grey block with the same layout as 'Recent notes' on the 'Open a note' page.
   Forklift-move the 'Browse the vault' section from the 'Open a note' page and put it at the bottom of the
   'Meetings' page. And lastly, on the 'Meetings' page, ensure each section has intuitive pagination so that, as
   the content accumulates over time, the page length does not grow vertically in an uncontrolled manner."

## Decisions already made
- The request is split across 15c (this phase), 15d (rename a meeting) and 15e (topic-based template)
  (ADR-0037). Do not start 15d or 15e work here.
- Defaults chosen at planning time (follow them, or record a justified change in this phase's ADR):
  - **Open a note** leaves the main navigation once Browse the vault has moved. `GET /open` redirects (303) to
    `/meetings`. `/open/note`, `/ui/open/browse` and every existing link keep working. The "Recent notes" list on
    the Open page is dropped because "Notes in your vault" on Meetings already shows the same rows.
  - **Preview/Edit:** one toggle button named after the **action it performs**: "Edit note" while the preview shows,
    "Show preview" while the editor shows. A small muted mode label next to it ("Viewing" / "Editing") keeps the
    current state visible. `aria-pressed` is not used on an action-labelled button.
  - **Pagination:** 10 rows per page for Jobs and for Notes in your vault, 25 entries per page in Browse the vault,
    each section paged on its own (`?jobs_page=`, `?notes_page=`, HTMX swaps of that section only, links that also
    work without JS).

## Goal
A template switch shows real progress, the time elapsed and an honest estimate of the time remaining, with
continuous motion so a long switch never looks frozen. From the review page, the user can see how big the
stored recording is and can download it. The Preview/Edit control says what it will do. **Meetings** is the
single place to find meetings and notes, and its length stays bounded however many meetings pile up.

## What exists (verified 2026-10-14; re-check before relying on it)
- **Switch template:** `review.js` (`#form-switch` submit) calls `busy(button, () => call("/switch/preview", …))`.
  It is **one blocking POST** to `POST /ui/review/{mm3_id}/switch/preview` (`web/review.py:switch_preview`), which
  awaits `review/switch.py:switch_template` (a whole-note `NoteGenerator.generate`) and returns
  `{html, token}`. While it waits, the only feedback is the disabled button with `aria-busy`. Apply is
  `POST …/switch/apply` (archive + `write_checked`). `NoteGenerator` already takes a
  `progress: ProgressFn = Callable[[float, str], None]` (fraction 0-1 and a message), including the map-reduce
  share (`MAP_SHARE`), and a `check_cancelled` hook. The switch path does not pass either. Section regeneration
  (`/regen/preview`, `#form-regen`) is the same blocking pattern.
- **Estimates:** `hardware/recommend.py` `LLMRecommendation.estimate(duration_s)` uses `notes_rtf` from
  `hardware/recommendations.yaml` (`[12, 18]` measured for `qwen3:8b` on 8 GB). That figure is for a *whole
  job*. A switch generates the same note, so it is a fair first guess, replaced by the measured rate once
  sections finish.
- **Job progress UI (reference pattern):** `web/templates/partials/job_panel.html`, `jobs/progress.py`
  `ProgressBus`, and SSE `GET /api/jobs/{id}/events`. The review page uses plain JS (`review.js`), not Alpine.
- **Review audio:** `web/review.py:workspace_page` sets
  `audio_url = /api/jobs/{job_id}/audio` only when `ws.audio == "ok"`. `GET /api/jobs/{job_id}/audio`
  (`web/api/jobs.py:job_audio`) serves `JobRunner.audio_file()` (`jobs/retention.py:playable_audio`: Opus, then
  WAV, then the upload) with Range support and `Cache-Control: no-store`, but with **no download disposition or
  file name**. `review.html` `#player` / `.player-controls` and the retention line (`partials/retention.html`,
  `review/retention_view.py`, `retention.js`). The header **Download** menu (`details.download-menu`) already
  offers the note and transcript through `/api/export/meeting?note=…&kind=…` (`web/api/export.py`). Nothing on
  the page shows the file size.
- **Preview/Edit:** `review.html` lines ~28-31: `.mode-switch` group with `#btn-preview` (aria-pressed) and
  `#btn-edit`. `review.js` `showMode`/`showEdit`/`showPreview` and `MODE_KEY` in `localStorage` (15b, ADR-0036).
  Read-only notes hide the toolbar.
- **Navigation:** `web/pages.py` `NAV`: `("recent", "/meetings", "Recent")` and `("open", "/open", "Open a note")`.
  The route is **already `/meetings`**. Only the label and the page say "Recent". `recent.html` has the title
  "Recent meetings", an `<h1>Recent meetings</h1>`, a **Jobs** table (`list_jobs(None, limit=200)`, no paging), the
  Update-older-notes card (`hx-get="/ui/notes/upgrade"`), and **Notes in your vault** (`RecentMeetingsRepository.recent(30)`,
  orphan badges, Remove from list, prune). `open.html` (`web/review.py:open_page`) has `.card` sections
  "Recent notes" and "Browse the vault" (`#picker`, `partials/picker.html`, `/ui/open/browse?dir=`, a
  `listing.truncated` warning). Tests and e2e refer to "Recent" in places (`grep -rn "Recent" tests/ src/`).
  `/meetings/{mm3_id}` is the review workspace (R23), so make sure the new paging query parameters never clash with it.

## Tasks

### 1. Switch template: live progress, ETA and motion
1. **Server.** Make the switch preview a background task: `POST …/switch/preview` starts it and returns at once
   with a `task` id, and the result (diff HTML + token) is fetched when it is done. Pass `NoteGenerator` a
   `progress` callback and a `check_cancelled` hook. Keep the task state small and in memory, per workspace (one
   switch at a time per note; a second start while one runs is refused with a clear error). Expose progress by
   **SSE** (`GET …/switch/events?task=`; reuse the `_sse` helper and the heartbeat pattern from
   `web/api/jobs.py`) or by short polling. Pick one, say why in the ADR, and make sure it survives a reload of
   the page (reattach to a running task, or say clearly that it was lost). Add **Cancel** (`POST …/switch/cancel`,
   CSRF). The existing apply flow, token, archive and `E_NOTE_CHANGED` checks stay as they are.
2. **Progress model.** Fraction = the generator's own fraction: sections done / total, with the map step's share
   in map-reduce mode. ETA: before the first section finishes, use `LLMRecommendation.estimate(duration)` for the
   meeting's duration on the current hardware profile (or "estimating…" when there is no figure, e.g. a cloud
   backend). After that, use the measured rate (elapsed / fraction), smoothed so it does not jump about. Never show
   a negative or 0:00 ETA while work remains; past the estimate, show "taking longer than expected" and keep the
   elapsed timer running.
3. **UI** (in `#dlg-switch`, plain JS like the rest of `review.js`): a determinate bar (`<progress>` or an ARIA
   `progressbar` with `aria-valuenow`), the current step ("Section 3 of 9: Summary Detailed"), **elapsed** and
   **about N min left**, plus a **motion cue** that moves even while the fraction stands still (an animated
   stripe or shimmer on the bar and a ticking elapsed clock). With `prefers-reduced-motion`, drop the animation
   but keep the ticking clock. Announce milestones politely (`aria-live`, not every tick). The dialog says the user
   can keep reading the note. Closing the dialog asks whether to cancel or keep the switch running in the
   background.
4. **Reuse.** Put the progress widget in a small shared module (for example `static/js/progress.js` + a partial)
   and use it for **section regeneration** too (`/regen/preview`), so both long actions behave the same. If
   that grows too large, ship it for switch only and log regeneration as a follow-up.

### 2. Recording size and download on the review page
1. In `web/review.py:workspace_page`, when `ws.audio == "ok"`, add the playable file's size (bytes) and format
   (Opus/WAV/original) to the context. Format it with one helper (`12.4 MB`, decimal units, one decimal place).
2. Show it **subtly** near the top of the left pane: a muted, small line or an ⓘ with a `title` tooltip **and**
   visible-on-focus text (a tooltip alone is not accessible), for example "Recording: 41.2 MB (Opus)". Put it
   next to the 15b retention line so the user sees the size while deciding about Keep forever.
3. **Download:** add `?download=1` to `GET /api/jobs/{id}/audio` (or a sibling route), which sets
   `Content-Disposition: attachment` with a safe file name built from the **note stem** (`<note stem>.opus`,
   RFC 6266/5987 encoding for non-ASCII, `vault.naming.sanitize_title` rules). Offer it in two places: a
   "The recording (.opus, 41 MB)" item in the header **Download** menu, and a small download icon or link in the
   player area. Neither appears when there is no audio (expired, missing, none). An expired recording still gives
   the existing `E_AUDIO_EXPIRED` error.
4. Security: same Host/Origin rules as the player; the job id is validated (`check_job_id`); no path from the
   client reaches the filesystem.

### 3. Preview/Edit label follows the mode
Replace the `.mode-switch` pair with the single action-labelled toggle described in the decisions ("Edit note" ⇄
"Show preview" plus the muted mode label), keeping every 15b behaviour: auto-switch to Edit for draft restore and
accepted regenerations, the remembered mode, `/render` for unsaved edits, the read-only case (no toggle), and the
keyboard and focus behaviour. Update `review.js` and every test or e2e that clicks `#btn-preview` / `#btn-edit`.

### 4. Meetings page (was Recent) with pagination
1. **Rename:** nav label "Meetings"; `<title>Meetings · MeetingMaster3</title>`; `<h1>Meetings</h1>`; check the
   docs, the user guide, toasts, hints, error hints and empty-state texts that say "Recent" (`grep -rn
   "Recent" src/ docs/`). Keep `/meetings`. The nav key may stay `recent` internally.
2. **Notes in your vault:** keep the content and behaviour exactly as they are (links, orphan badges, Remove from
   list, prune), and wrap the section in the same light-grey `.card` block and list layout as "Recent notes" on the
   Open page.
3. **Browse the vault:** move it as it is (heading, hint, `#picker`, the `/ui/open/browse` HTMX behaviour) to the
   bottom of Meetings, in a `.card`. Apply the Open-page decision from above (nav entry removed, `/open` → 303 to
   `/meetings`). Keep `open_page`'s `?dir=` deep link working by redirecting it to `/meetings?dir=…` with the
   picker opened there.
4. **Pagination:** Jobs, Notes in your vault and Browse the vault each page independently. The server does the
   paging (`LIMIT/OFFSET` or a keyset in `JobsRepository.list_jobs` and `RecentMeetingsRepository.recent`, plus a
   count). Controls: "‹ Newer · Page 2 of 5 · Older ›" (or numbered pages when there are few), disabled at the ends,
   `aria-label`ed `<nav>`, and focus returned to the section heading after an HTMX swap. URLs are bookmarkable and
   work without JS. Removing or deleting the last row on a page shows the previous page, never an empty one. The
   orphan banner counts across **all** entries, not just the visible page. Browse the vault pages its folder
   listing (25 per page) and keeps the truncated warning.
5. Make sure the Update-older-notes card and the Jobs Resume/Delete buttons still work on any page.

## Out of scope
- Renaming or re-dating a meeting (Phase 15d). Do not add its button here.
- New templates (Phase 15e).
- Changing retention rules, audio formats or the export zip.
- A progress UI for other actions beyond switch and section regeneration (record ideas).

## Tests
- Unit: progress/ETA maths (estimate before the first section, measured after, smoothing, overrun wording, no
  estimate for cloud); the size formatter; the download file name (non-ASCII, forbidden characters, long titles);
  the paging helpers (counts, bounds, last page after a delete).
- Web: the switch task lifecycle (start, progress events or polls, result, cancel, a second start refused, an
  unknown task gives 404, CSRF required, reload/reattach); the audio size shown only when audio is `ok`; the
  download disposition header and that expired audio gives `E_AUDIO_EXPIRED`; the toggle label in both modes and
  read-only; the Meetings title, heading and nav; `/open` redirects; each section's pagination (page 2 and beyond,
  out-of-range pages, HTMX partials); the orphan count across pages.
- e2e (fake pipeline, Chromium): switch with a slowed fake generator → the bar moves, elapsed ticks, the ETA shows,
  Cancel works, then a full switch applies. Download the recording (the browser download event has the expected
  file name). Toggle Edit/Preview labels. Meetings with more than 10 jobs and notes → paging works, and Browse the
  vault opens a folder. axe stays clean on review (both modes, switch dialog open) and on Meetings.
- No regressions in the existing review, recent and open e2e tests (update their selectors and labels).

## Acceptance criteria
- In the real app, a template switch on one of Nick's real meetings shows a moving bar, the elapsed time and a
  time-left estimate that ends up within reasonable error of the real time (record estimate vs actual in the Phase
  Log). With reduced motion on, the clock still ticks. Cancel the switch, or apply it only with Nick's OK; the
  previous note is archived either way per R12.
- The review page shows the recording's size subtly, and the recording downloads with a sensible file name.
- The Preview/Edit control's text always says what clicking it will do.
- The nav says **Meetings**. The page has Jobs, Update older notes, Notes in your vault (grey block), and Browse
  the vault at the bottom. Each section pages at 10 (25 for browse). "Open a note" is gone from the nav, and old
  `/open` links still land somewhere useful.
- Screenshots (light, dark, 390 px) of the switch progress dialog, the review header with size and download, and
  Meetings with pagination.
- `uv run pytest`, `ruff check`, `ruff format --check` and `uv run mypy src` pass, the e2e suite passes, and the
  `mypy src tests` error count is no higher than on `main`.

## Phase-specific docs
- `docs/MM3_SPECIFICATION.md` §15: amendment **R27** (switch/regenerate progress with ETA; recording size and
  download on the review page; the action-labelled Preview/Edit toggle; Meetings page, Open-a-note merged, and
  pagination). If 15e has already used R27 on `main`, take the next free number.
- ADR (next free number on `main` at close-out; 15e may run in parallel, so re-check after rebasing): background
  switch task and its transport, the ETA model, the download route, and the pagination and Open-page choices.
- User guide: `reviewing-and-editing.md` (progress, size, download, toggle) and `getting-started.md` (Meetings
  replaces Recent and Open a note). README feature list if it names Recent. `docs/ARCHITECTURE.md` if modules
  change. `CHANGELOG.md`.
- `prompts/MM3_phase-15d-rename-meeting.md`: check that its "What exists" still matches (review toolbar, Meetings
  page) and correct it if this phase changed something it relies on.
- `prompts/MM3_phase-16-release.md`: screenshots show Meetings (not Recent) and the review header with size/download.

Then the standard close-out checklist.
