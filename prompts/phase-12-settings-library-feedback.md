# Phase 12: Settings, Template Library Management & Feedback

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 10 (can run in parallel with 11 and 13) · **Branch:** `phase-12-settings-library-feedback`

## Read first
`CLAUDE.md`, `prompts/_shared-instructions.md`, and `docs/SPECIFICATION.md` §3 (template library, feedback), §6, §8, §11 (config file reveal), §15.2 (R3, R8) and §15.3 (S1, S5, S6, S7). `docs/user-guide/configuration.md`.

## Goal
Everything the user configures and curates lives in the UI and round-trips cleanly to `config.yaml` and to template files in the vault. Feedback ratings are stored locally for a future improvement loop.

## Tasks
1. **Settings UI** (`/settings`, tabbed):
   - *Vault:* path, output subfolder pattern, templates folder, "copy audio to vault attachments" option (R8) and attachments path.
   - *Transcription:* hardware profile (auto or override), default whisper model, compute type, batch size, diarization default, HF token (masked; Test button that checks token validity and model access via the HF API, plus the terms-acceptance URL), and Download models button (calls the Phase 06 downloader with progress).
   - *LLM backends:* list, add, edit and remove backends (kind-specific forms), API keys (masked; write-only fields; "replace key" flow), Test connection, model dropdown from `list_models`, default backend and model, remembered cloud consents (revocable; stored as `llm.backends.<name>.consent_remembered`; use `BackendRegistry.invalidate()` after saving config; typed config is `config.settings.BackendConfig`), and the recommendations panel (Phase 08).
   - *Privacy:* audio retention (forever / N days, default 90 / delete after write; per-meeting pins are shown and managed on each meeting; the opt-in "copy audio to vault" setting shows a warning about vault size and sync uploads), voiceprints enable toggle plus link to manage or wipe voiceprints (Phase 07 API, with an explicit confirmation dialog), and a bind-host warning if not loopback (read-only display; changing it requires editing config, deliberately).
   - *About / Diagnostics:* the `mm3 doctor` output rendered, version, the paths of the config, data and model dirs, with copy-path buttons ("Open config file" means reveal the path, spec §11; also offer `xdg-open` when running natively, not in Docker).
2. **Config round-trip:** saving writes through the Phase 02 `save()` (atomic, 0600). Preserve comments and unknown keys if Phase 02 chose ruamel.yaml; otherwise document that UI saves normalise the file. Validation errors show inline. Secrets: an empty field means unchanged; there is an explicit Clear button.
3. **Template library** (`/templates`): grid or list with name, description, tags, a favourite star (persisted in the template frontmatter `favorite`, so it stays in the vault), built-in vs custom badges, and validation status. Actions: **Preview** (renders section list and prompts), **Edit in app** (CodeMirror from Phase 11, with validation on save showing line-numbered errors), **Duplicate** (new id, `name (copy)`), **Create new** (from a skeleton), **Delete** (custom only; built-ins can be reset to default), **Open in Obsidian** link, and **Reset built-in** (restore the shipped version, archiving the user's). Filtering by tag and search.
4. **Feedback** (spec §3, step 9): a SQLite migration for `feedback` (id, mm3_id, template_id, backend, model, section_id nullable, rating_kind thumbs|stars, value, comment, created_at). UI: thumbs or 1–5 stars plus an optional comment on the note and on each section (the slots from Phase 11). `GET /api/feedback/export` returns JSON or CSV for the user's own analysis. Stored locally only. No telemetry, ever (state this in the UI).
5. **Export and data ownership** (design notes MVP item 7): a "Download" menu on a meeting offering the note `.md`, the transcript `.md`, a zip of both plus the audio if retained, and plain `.txt` transcript; and a global "Export all app data" (zip of the SQLite dump as JSON plus job artifacts, excluding secrets).

## Tests
Settings forms (validation, secret masking, empty-means-unchanged, clear); config round-trip; template CRUD in a temp vault (duplicate, favourite persisted in frontmatter, reset built-in archives the user copy, invalid template shows errors); feedback storage and export; export zip contents exclude secrets. A Playwright smoke test for settings save and template duplicate.

## Acceptance criteria
- Every setting from `docs/user-guide/configuration.md` can be viewed and, where intended, edited in the UI, and survives a restart.
- Template edits made in Obsidian show up in the app on refresh, and vice versa.
- No secret value is ever present in any HTML response (asserted by a test that greps rendered pages).

## Phase-specific docs
`docs/user-guide/settings.md`, `docs/user-guide/templates.md` (library management), configuration doc (sync it), PRIVACY (feedback and export), README feature list. Then the standard close-out checklist.
