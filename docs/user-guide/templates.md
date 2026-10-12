# Templates and note generation

A **template** decides which sections a meeting note has and how each one is written. MeetingMaster3
ships five templates now (17 more arrive with Phase 13) and you can change them or write your own in
Obsidian. The file format is specified in
[`../dev-guide/template-format.md`](../dev-guide/template-format.md).

## The built-in templates
| Template (`id`) | Use it for | Sections |
|---|---|---|
| **Executive Summary** (`executive-summary`, the default) | A one-minute brief for people who were not there | Summary, Decisions Made, Action Items, Open Questions, Next Steps, AI Recommendations |
| **Technical Deep-Dive** (`technical-deep-dive`) | Design reviews, architecture discussions, incident reviews | Summary, Problem & Context, Technical Details, Options Considered, Decisions Made, Risks & Concerns, Action Items, Open Questions, AI Recommendations |
| **Decision Log** (`decision-log`) | Meetings whose output is choices: what, why, alternatives, who | Summary, Decisions, Deferred Decisions, Action Items, AI Recommendations |
| **Action-Focused** (`action-focused`) | Who does what by when, grouped by owner | Summary, Action Items, Blockers & Dependencies, Decisions Made, Next Steps, AI Recommendations |
| **Just the Facts** (`just-the-facts`) | Neutral minutes to share widely, no interpretation | Key Points, Decisions Made, Action Items, AI Recommendations |

Every note starts with the title and a header (date and time, participants, tags, location) built
from the meeting details, not by the AI. **AI Recommendations** is always the last section and only
draws on what was said.

## The template library
**Templates** in the top bar lists every template with its description, tags, whether it is built in or your own, and whether it is valid. You can:

* **Star** a template to make it a favourite (favourites come first). The star is stored in the template file itself (`favorite: true`), so it travels with your vault.
* **Preview** it: the sections and the instructions the model receives for each.
* **Edit** it in the app. Saving checks the file first and shows errors with line numbers; nothing is written until it is valid. (Editing a built-in
  template copies it into your vault, where it takes precedence.)
* **Duplicate** it (a new id and the name "… (copy)"), or **Create** a new one from a small skeleton.
* **Delete** one of your own templates (a copy is kept in `<templates folder>/Archive/`). Built-in templates cannot be deleted; **Reset to default**
  restores the shipped version and keeps your current copy in the Archive folder.
* **Open in Obsidian**, and filter by tag or search by name and description.

The library reads the vault each time, so a template you edit in Obsidian shows up here when you reload, and the other way round. Files that are not valid
templates are listed with their errors instead of being hidden. The format is in [`../dev-guide/template-format.md`](../dev-guide/template-format.md).

## What a note looks like
```markdown
# Atlas Launch Sync
- **Date & Time:** 2026-10-06 10:00
- **Participants:** Priya Natarajan, Marcus Webb, Elena Sokolova, Tom Fischer
- **Tags:** #meeting

<!-- mm3:section:action-items -->
## Action Items

- [ ] **Marcus Webb:** Finish the billing migration script and run the remaining accounts (due: Friday, 2026-10-09) [01:20]
- [ ] **Unassigned:** Update the status page template before launch (due: not stated) [04:06]
<!-- /mm3:section:action-items -->
```
* Action items are Obsidian checkboxes. The **owner** is the person who said they would do it or who
  was asked and agreed. A task that someone only suggested ("we should…") is **Unassigned**:
  MeetingMaster3 checks owners against what was actually said and never guesses one.
* Deadlines appear as they were said. For "today", "tomorrow" and weekdays the calendar date is added,
  calculated from the meeting date.
* `[mm:ss]` points to the moment in the recording (the companion transcript has the same times).
* The `<!-- mm3:section:… -->` lines are invisible in Obsidian's reading view. They mark the parts
  MeetingMaster3 may regenerate; everything outside them is yours and is never changed.

## Choosing a template and a model
* **Command line:** `uv run mm3 process recording.m4a --template decision-log --backend ollama --model qwen3:8b`
  (see "Process a recording headlessly" in the [README](../../README.md#quickstart)).
* **API:** the upload's `options` take `template`, `backend` and `model`; `POST /api/jobs/{id}/generate`
  changes them before the notes are generated, or re-generates the notes of a failed job.
* **Web UI:** a template picker arrives with Phase 10.

Without a model, the backend's `default_model` is used (set it in `config.yaml`, see
[`configuration.md`](configuration.md)). On an 8 GB GPU, a 7-9B model such as `qwen3:8b` is a good
choice (see [`hardware.md`](hardware.md)). Notes take about 15-60 seconds on the reference laptop,
depending on the template.

**Cloud models.** If the backend is a cloud service, the job pauses and asks before sending the
transcript (`cloud_consent`), unless you agreed at upload (`cloud_consent: true`, or
`mm3 process --cloud-consent`) or remembered consent for that backend. Declining stops the job
without sending anything. See [`../PRIVACY.md`](../PRIVACY.md).

**Long meetings.** When a meeting does not fit the model's context window (with a local model on 8 GB,
roughly anything over an hour), MeetingMaster3 first extracts notes from each part of the meeting and
then writes the sections from those notes. It takes longer but nothing is skipped; if one part cannot
be read, the job shows a warning naming the time range.

## Where templates live and how to change them
The first time MeetingMaster3 uses your vault, it copies the built-in templates into
`MeetingMaster3/templates/` (setting `vault.templates_subfolder`). From then on:
* **Edit a template** directly in Obsidian. Your edits are never overwritten: when MeetingMaster3 is
  updated, only templates you never touched are refreshed.
* **Make your own:** copy a file, change its `id` and `name`, and edit the sections and the prompt
  blocks under `<!-- mm3:prompt:… -->`. A template in the folder **overrides** a built-in one with
  the same `id`.
* **Restore the built-ins** you deleted: `uv run mm3 templates install` (or `POST /api/templates/install`).
* **Check your changes:** `uv run mm3 templates validate` lists every problem with its line number, and
  `uv run mm3 templates list` shows what the app sees (`INVALID` templates are listed with their errors
  and are not offered).
* Files starting with `_` or `.` in the folder are ignored, so you can keep a `_README.md` there.

Tips for prompts (from testing with small local models):
* Show the structure with placeholders such as `<Owner>` and `<task>`, not with realistic examples:
  models copy example names and dates into notes.
* Tell the model what to write when there is nothing ("If no decision was made, write exactly: No
  decisions were made.").
* Keep sections focused: one call writes one section, with its own temperature (0.2 for
  `extraction` sections, 0.4 for `narrative` ones, unless the template sets `temperature`).

## Regenerating a section
`POST /api/notes/regenerate-section` with `{"note": "<path inside the vault>", "section_id":
"summary", "instructions": "Shorter, and focus on the budget"}` returns the current and the new text of
that section with a diff. Nothing is written; the review screen (Phase 11) lets you accept it, archive
the old version, or discard it. It needs the note's companion transcript.

## Settings
| Setting | Default | |
|---|---|---|
| `generation.default_template` | `executive-summary` | Template when a job does not choose one. |
| `generation.write_companion` | `true` | The companion transcript. Without it a note cannot be re-opened for regeneration. |
| `generation.max_context` | `16384` | Context planned for local models; raise it on bigger GPUs. |
| `generation.think` | `false` | Let reasoning models think first (slower). |
| `generation.install_templates` | `true` | Copy the built-ins into the vault on first use. |

## Troubleshooting
| Message | What to do |
|---|---|
| `No model is chosen for the backend 'ollama'` | Pass `--model`, or set `llm.backends.ollama.default_model`. `ollama list` shows installed models. |
| `There is no template with the id '…'` | Check the id with `mm3 templates list`. |
| `The template '…' is invalid` | Run `mm3 templates validate` and fix the reported line. |
| `The "…" section reached its length limit` | Raise that section's `max_tokens` in the template. |
| A cloud job is "waiting for input" | It is asking for cloud consent; answer it, or switch the job to a local backend. |
