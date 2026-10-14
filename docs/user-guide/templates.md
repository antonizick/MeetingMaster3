# Templates and note generation

A **template** decides which sections a meeting note has and how each one is written.
MeetingMaster3 ships **23 built-in templates** and you can change them or write your own in
Obsidian. The file format is specified in
[`../dev-guide/template-format.md`](../dev-guide/template-format.md).

## The built-in templates
The full list, with when to use each one and its sections, is the generated
[template catalogue](template-catalogue.md). A quick guide to choosing:

| If the meeting is... | Try |
|---|---|
| Anything, and you want a full briefing by topic (the default) | **Default Notes** (`default-notes`): a one-line summary, a detailed summary, numbered topics dense with figures, names and dates, questions and answers when there were many, a conclusion and action items. It takes longer to write than the others. For hiring interviews prefer **Job Interview Notes**: with a small local model, Default Notes may keep a personal remark a candidate volunteers (ADR-0039). |
| Anything, and you want a short brief | **Executive Summary** (`executive-summary`) |
| Anything, and you want a neutral overview | **General Discussion Summary**, **Just the Facts**, or **Key Takeaways & Next Steps** for the shortest version |
| A full record, to be consulted later | **Detailed Meeting Minutes**, **Chronological Timeline**, or **Speaker-Attributed Notes** |
| About who does what | **Action-Focused**, **Project Team Sync**, or **Agile Stand-up** |
| About choices | **Decision Log** or **Strategic Meeting Summary** |
| Technical | **Technical Deep-Dive** or **Risks, Issues & Mitigations** |
| A formal board or governance meeting | **Board & Governance Minutes** (motions and votes recorded exactly as stated; no AI Recommendations section) |
| A hiring interview | **Job Interview Notes** (job-relevant evidence only; the recommendation is advisory) |
| A one-on-one or coaching session | **One-on-One & Coaching** (respectful, non-judgmental tone) |
| A sales or client call | **Sales & Client Call** |
| A brainstorm, workshop, training or review | **Brainstorming & Ideation**, **Workshop & Training Recap**, **Retrospective & Lessons Learned** |
| Mostly questions and answers | **Q&A Extraction** |

Every note starts with the title and a header (date and time, participants, tags, location) built
from the meeting details, not by the AI. **AI Recommendations** is the last section of every template except Board & Governance Minutes,
and it only draws on what was said.

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
* **Web UI:** the template picker on the upload page and the template library in Settings.

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
  updated, only templates you never touched are refreshed (at the next start). When a built-in you edited
  has a newer version, the library says so; **Reset to default** gets it (your copy goes to the Archive
  folder), or copy the changes by hand.
* **Make your own:** copy a file, change its `id` and `name`, and edit the sections and the prompt
  blocks under `<!-- mm3:prompt:… -->`. A template in the folder **overrides** a built-in one with
  the same `id`.
* **Restore the built-ins** you deleted: `uv run mm3 templates install` (or `POST /api/templates/install`).
* **Check your changes:** `uv run mm3 templates validate` lists every problem with its line number, and
  `uv run mm3 templates list` shows what the app sees (`INVALID` templates are listed with their errors
  and are not offered).
* Files starting with `_` or `.` in the folder are ignored, so you can keep a `_README.md` there.

### Adding Summary Succinct and Summary Detailed to your own templates
Since Phase 15a every built-in template starts with two summaries (Board & Governance Minutes puts them after
Attendance & Quorum). Your own templates are not changed automatically. To add them, put these two lines first
under `sections:` (keep the `summary` id: notes, regeneration and ratings use it):
```yaml
  - {id: summary, title: Summary Succinct, kind: narrative}
  - {id: summary-detailed, title: Summary Detailed, kind: narrative, max_tokens: 1000}
```
and a prompt block for each, for example (adapt the first sentences to your template's voice):
```markdown
<!-- mm3:prompt:summary-detailed -->
Write a detailed summary. First paragraph: why the meeting was held and its context. Second paragraph:
the main threads of discussion, naming who said what. Third paragraph: what was decided, what happens next
and what is still open.

Write prose only: typically three paragraphs and never fewer than two, separated by blank lines, about
200-450 words in all. No bullet points, numbered lists, headings or tables. Use only what was said in the transcript and the names in the
speaker list; never invent facts, names or numbers. Do not repeat the short summary word for word: go deeper.
```
A section with the id `summary-detailed` always gets the two-paragraph check: an answer with one paragraph is
asked for again once, and kept with a warning if it is still short. Then **Update older notes** on the Recent
page can add the new section to notes made with that template.

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
| `generation.default_template` | `default-notes` | Template when a job does not choose one, and the one the New meeting page pre-selects. The template you start a meeting with there becomes the new default (R29). |
| `generation.write_companion` | `true` | The companion transcript. Without it a note cannot be re-opened for regeneration. |
| `generation.readable_transcript` | `true` | The readable `… (Transcript).md` next to each note (needs the companion). |
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
