# Phase 15b: Pre-operational tuning, round 2

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 15a · **Branch:** `phase-15b-pre-op-tuning` · **Worktree:** `../MeetingMaster3-phase-15b`

This is the second **interim tuning round** (ADR-0030; planned with `/phase-add`, ADR-0034). After 15a, Nick
used the review screen day to day and asked for three changes before publication. Phase 16 depends on this
round.

## Read first
- `CLAUDE.md`, `prompts/MM3_shared-instructions.md`, `docs/MM3_SPECIFICATION.md` §15 (R8 retention, R19, R25 and
  the S1–S8 controls in §15.3, especially S2 CSRF/Origin and S3 sanitised rendering).
- Phase Log entries for Phases 04 (retention, pin API), 11 (review workspace), 12 (Settings → Privacy),
  15a and the 15b planning entry (2026-10-14).
- ADR-0006 (audio retention and per-meeting pin), ADR-0013, ADR-0025 (review workspace writes),
  ADR-0032, ADR-0033 and **ADR-0035** (logo licence, decided).
- `docs/user-guide/reviewing-and-editing.md`, `docs/user-guide/configuration.md` (privacy settings).

## Nick's request (verbatim intent, 2026-10-14)
1. When the user opens the review and edit screen, the meeting notes on the right side should default to a
   **preview** state, not an edit state.
2. There is a default setting for how long the audio is retained. On the review and edit screen, the user
   should have a way to **mark an audio file for permanent retention**. Up by the player controls there
   should also be an indication of **how many days are left before the audio is deleted** because its
   retention window closes, or, if the audio is marked for permanent retention, that instead.
3. Change the licensing on the image (logo). Users should not be forced to replace it. It is an image Nick
   generated; he does not mind people keeping and using it: free use.

## Decisions already made
- **Logo licence: CC0 1.0 Universal** (ADR-0035, Q6 updated). Covers `web/static/brand/logo*` and `hero*`.
  The notice says CC0 covers copyright only: no trademark rights, and no right to use the likeness of a
  person shown (for example to suggest endorsement). The original `wiz.jpg` is still never committed.
- "Permanent retention" is the existing **pin** (`jobs.audio_pinned`). Do not add a second flag. The UI
  should say "Keep forever" or similar, not "pin", and it can be undone.

## Goal
The review screen opens on a readable note. It shows plainly how long the meeting's recording will be kept
and lets the user keep it forever, or undo that, in one click. The logo can be reused freely.

## What exists (verified 2026-10-14; re-check before relying on it)
- **Review page:** `web/templates/review.html` + `web/static/js/review.js` (plain JS, no Alpine). The note
  pane has `#editor` (textareas per part) and `#preview` (hidden), and a toggle `#btn-preview`
  (`aria-pressed`). The preview HTML comes from `POST /ui/review/{mm3_id}/render`
  (`web/review.py`), which takes the *current edits* and is sanitised server-side (raw HTML off, links
  filtered). Read-only notes (`ws.readonly`) hide the toolbar, `#btn-preview` included. The draft banner
  (`#draft-restore`) restores unsaved edits into the editor. Section actions (regenerate, append,
  archive) sit in the editor.
- **Audio on the review page:** `review/workspace.py:audio_state` → `ok | expired | missing | none` with a
  message. `web/review.py` builds `audio_url` only when `ok`. The player lives in `#player`
  (`.player-controls`: back, play, forward, seek, `#pl-time`, speed), with `#no-audio` otherwise.
  `ws.job_id` is the job that produced the meeting (`find_job`), or `None` for notes processed elsewhere.
- **Retention:** `config/settings.py` `privacy.audio_retention: "forever" | "days" | "delete_after_write"`
  (default `days`), `privacy.audio_retention_days` (default 90). `jobs/retention.py`:
  `compute_expiry(written_at, privacy)` for written jobs and `_stale_expiry` (from `updated_at`) for
  unfinished ones. **The pruner recomputes the expiry from the current setting**, so the stored
  `audio_expires_at` can be stale after a settings change. It skips `audio_pinned` jobs and runs every
  `jobs.prune_interval_hours` (24) and at start-up.
- **Pin:** `POST /api/jobs/{id}/pin` and `/unpin` (`web/api/jobs.py`, CSRF-protected) →
  `JobRunner.set_pinned`, which refuses to pin already-pruned audio (`E_AUDIO_EXPIRED`). `DELETE` of a job with
  pinned audio needs `force=true`. **No page offers pin today**, yet `settings/privacy.html` says "Pin or
  unpin a meeting's audio on the meeting's own page", and the `E_AUDIO_EXPIRED` hint says "Pin a meeting to
  keep its audio".
- **Logo notices:** `NOTICE` (lines ~10-13), `THIRD_PARTY_NOTICES.md` "Project logo (Phase 15a)",
  `README.md` licence section ("forks must replace it"), ADR-0032/0033, `prompts/MM3_phase-16-release.md`
  line ~8, and possibly `scripts/make_logo.py`'s docstring and `docs/` pages. `grep -rn -i "all rights
  reserved\|must replace" .` lists every place.

## Tasks

### 1. Review screen opens in Preview
1. On load, show the rendered note and hide the editor. Render the first view on the **server** in the
   page response (same renderer and sanitiser as `/render`, from the saved note), so there is no
   flash of textareas and no extra request. Keep `/render` for previews of unsaved edits.
2. The toggle becomes a clear two-state control: **Preview** (selected) / **Edit**, with `aria-pressed`
   or a tab pattern, keyboard reachable, and a visible label for the current mode.
3. Switch to Edit automatically whenever an editing action needs it: restoring a draft, a section's
   regenerate/append/archive action, accepting a regeneration diff, Switch template and Rename speakers
   previews, and any validation error that points into a textarea. After Save, stay in the current mode and
   refresh the preview if it is showing.
4. Clicking a `[mm:ss]` reference in the preview should still seek the player if it does in the editor; check
   both modes.
5. Read-only notes show the preview only (no editor toggle). The unsaved-changes warning must still work.
6. Optional, if cheap: remember the last mode per browser (`localStorage`, try/catch). The default for a
   first visit is Preview. Record the choice in the ADR.

### 2. Keep the recording forever, and show how long it is kept
1. **Server:** add a pure function in `jobs/retention.py`, for example `audio_retention_status(job, privacy,
   now) -> RetentionStatus` (`kept_forever_pinned | kept_forever_setting | expires(at, days_left) |
   due(now) | pruned | none`). It uses **the same expiry rule as `prune`** (refactor so both share one
   function; no second copy of the maths). Days left = whole days, rounded up, local date. Expose it to the
   review page (`review/workspace.py` / `web/review.py`) and include `audio_pinned` and the status in the job
   dict that `/api/jobs/{id}` returns.
2. **Indicator** in `#player`, beside the controls (one muted line, not an alert), with exact wording to
   refine:
   - pinned: "Recording kept forever" + **Allow deletion** (undo);
   - `days`: "Recording deleted in 23 days (13 Jan 2027) under your retention setting" + **Keep forever**;
     "today" or "at the next check" when due; singular "1 day";
   - retention `forever`: "Recording kept: retention is set to keep forever" with no button, but pinning is
     still allowed so the meeting survives a later settings change. Decide whether to show the button,
     and record why;
   - `delete_after_write`: audio is normally already gone, so the existing `#no-audio` message applies; if
     it is still there (written moments ago, before the pruner ran), show "deleted at the next check" +
     **Keep forever**;
   - expired or pruned or no job: keep the existing `#no-audio` message, with no button.
   Link "retention setting" to Settings → Privacy.
3. **Action:** the button calls the existing pin/unpin API (CSRF header as in `review.js:call`), updates the
   line in place without a reload, and announces it politely (`aria-live`). Errors such as
   `E_AUDIO_EXPIRED` appear as the usual toast. No confirmation is needed to keep; un-keeping should say
   what it means ("will be deleted in N days" or "at the next check", if it is already past its time). Use
   a confirm dialog with the app's `<dialog>` pattern, never `window.confirm`.
4. **Elsewhere, consistently:**
   - Recent: a small "kept forever" marker on meetings whose audio is pinned, if it fits the row design;
   - Settings → Privacy: change the hint to name the real place ("Keep a recording forever from its review
     page");
   - the `E_AUDIO_EXPIRED` hint wording;
   - the job page after writing, optional; log the choice.
5. Nothing here changes the retention defaults or the pruner's behaviour. Add a test proving the indicator and
   the pruner agree, including after the retention setting changes.

### 3. Logo licence → CC0 1.0
1. Update `NOTICE`, `THIRD_PARTY_NOTICES.md` ("Project logo"), `README.md` (licence section: remove "forks
   must replace it"), `scripts/make_logo.py` docstring if it mentions the licence, and any user or developer
   doc that repeats it. Use ADR-0035's text, including the likeness/trademark sentence. Link the CC0 legal
   code (`https://creativecommons.org/publicdomain/zero/1.0/`).
2. Do **not** add the CC0 legal text as a new top-level `LICENSE` (the code stays Apache-2.0). Putting a
   short `src/meetingmaster3/web/static/brand/LICENSE.md` (CC0 statement) next to the images is
   recommended, so a fork that copies the folder carries it.
3. Update `prompts/MM3_phase-16-release.md`: replace "all rights reserved … forks must replace it" with CC0, and
   keep "the original `wiz.jpg` is never added".

## Out of scope
- Changing retention defaults, the pruner schedule, or adding per-meeting custom retention periods (record
  them as ideas if they come up).
- Copying audio into the vault (`privacy.copy_audio_to_vault` stays as it is).
- Editor features beyond the mode switch.
- A new logo or new crops.

## Tests
- Unit: `audio_retention_status` for every setting × pinned × written/unfinished × pruned, the days-left
  rounding (freeze "now"; the boundary at 0 and 1 days; a time-zone edge), and agreement with `prune(dry_run=True)`.
- Web:
  - the review page renders preview HTML server-side, with the editor hidden, for writable and read-only notes;
  - the indicator text and button for each status;
  - pin/unpin from the page (CSRF required, `E_AUDIO_EXPIRED` on pruned audio);
  - the `/api/jobs/{id}` dict includes the new fields;
  - the Privacy hint text.
- e2e (fake pipeline, Chromium):
  - open a written meeting → Preview is showing → Edit → type → Preview shows the edit → Save;
  - Keep forever → the line changes → reload shows it → Allow deletion → the days are back;
  - axe stays clean on the review page in both modes.
- No regressions in the existing review e2e tests (`tests/e2e/`).

## Acceptance criteria
- Opening any note on the review screen shows the rendered note first; editing is one click away and every
  editing action still works.
- Beside the player, Nick sees how many days remain before his recording is deleted. He can keep it forever
  and undo that. The days shown always match what the pruner will do, even after he changes the retention
  setting.
- `NOTICE`, `THIRD_PARTY_NOTICES.md`, README and the Phase 16 prompt state CC0 1.0 for the logo and hero
  picture, and nothing says forks must replace them.
- Verified in the real app on a spare port against Nick's config: a written meeting shows the days-left
  line; keep/undo works; screenshots in light and dark, and at phone width. Revert any pin state you
  changed on Nick's real meetings unless he asks to keep it.
- `uv run pytest`, `ruff check`, `ruff format --check` and `uv run mypy src` pass, the e2e suite passes,
  and the `mypy src tests` error count is no higher than on `main`.

## Phase-specific docs
- `docs/MM3_SPECIFICATION.md` §15: amendment **R26** (review opens in preview; per-meeting keep-forever with a
  visible countdown; the logo licence, amending R25(f)'s "all rights reserved").
- ADR (next free number): the preview-first default and mode-switch rules, the retention-status function
  shared with the pruner, and the wording choices.
- User guide: `reviewing-and-editing.md` (Preview/Edit, Keep forever, the countdown) and `configuration.md`
  (how the countdown relates to `privacy.audio_retention`).
- `docs/MM3_ARCHITECTURE.md` if modules change; `CHANGELOG.md`; `NOTICE`, `THIRD_PARTY_NOTICES.md`, `README.md`.
- `prompts/MM3_phase-16-release.md`: screenshots show the review screen in Preview with the retention line; the
  logo is CC0.

Then the standard close-out checklist.
