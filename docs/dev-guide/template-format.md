# Template Format (normative)

> **Status:** normative since Phase 09 (template schema version 1). The loader
> (`src/meetingmaster3/templates/`) and every shipped or user template must follow this page; if
> the code and this page disagree, that is a bug in one of them. Spec: §6, §8, §15.1 A3, §15.2 R6
> and R10. Decisions: ADR-0016 (map-reduce), ADR-0017 (default temperatures and prompt layout).

A template tells MeetingMaster3 which sections a note has and how to write each one. It is a
plain Markdown file, so it can be read and edited in Obsidian like any other note.

## 1. Where templates live
| Source | Location | Notes |
|---|---|---|
| Built-in | `src/meetingmaster3/starter_templates/*.md` | Shipped with the app; read-only. |
| Vault | `<vault>/<vault.templates_subfolder>` (default `MeetingMaster3/templates/`) | The user's copies and their own templates. |

* A vault template **overrides** a built-in template with the same `id`. Two vault files with the
  same `id` are both reported as invalid (`duplicate_template_id`) and neither is used; the
  built-in stays available.
* The vault folder is confined to the vault (S4); symlinks that leave it are ignored.
* Only `*.md` files directly inside the folder are templates (no recursion). Files whose names
  start with `.` or `_` are ignored, so a `_README.md` can live there.
* **Install (copy into the vault)** happens on first use (app start-up, `mm3 process`, the setup
  screen) and on demand (`mm3 templates install`). A built-in is copied only when the vault has no
  file with its name. An existing file is replaced only if it is byte-identical to the version MM3
  installed earlier (recorded as a SHA-256 in `<data>/templates.installed.json`), which means the
  user never edited it; otherwise it is kept and reported as `kept (modified)`. User edits are
  never overwritten.

## 2. File layout
```markdown
---
mm3-template: 1
id: executive-summary
name: Executive Summary
description: Short, high-level brief on outcomes, key decisions and implications.
tags: [general, leadership]
favorite: false
sections:
  - {id: summary, title: Summary, kind: narrative}
  - {id: decisions, title: Decisions Made, kind: extraction}
  - {id: action-items, title: Action Items, kind: extraction, format: tasks}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
<!-- mm3:prompt:_system -->
You are writing for a busy executive ...

<!-- mm3:prompt:summary -->
Write 3-5 sentences ...

<!-- mm3:prompt:decisions -->
...
```
* YAML frontmatter between `---` lines, then the **prompt blocks**.
* A prompt block starts at a line that is exactly `<!-- mm3:prompt:<id> -->` (surrounding spaces
  allowed) and runs to the next prompt marker or the end of the file. Its text is trimmed.
* Text before the first prompt marker is a free comment for humans and is ignored.

## 3. Frontmatter schema
| Key | Type | Required | Meaning |
|---|---|---|---|
| `mm3-template` | integer | yes | Schema version. Must be `1`. |
| `id` | text | yes | `[a-z0-9][a-z0-9-]*`, at most 64 characters. Stored in the note as `mm3-template`. |
| `name` | text | yes | Display name. |
| `description` | text | no | One or two sentences: when to use this template. |
| `tags` | list of text | no | Library categories (not note tags). |
| `favorite` | boolean | no | Shown first in pickers (Phase 12 toggles it in the file). |
| `sections` | list (≥ 1) | yes | See §3.1. Order = order in the note. |
| `params` | mapping | no | See §3.2. |

Unknown top-level keys are kept but ignored (a warning is reported), so a newer template still
loads in an older app.

### 3.1 Sections
| Key | Type | Default | Meaning |
|---|---|---|---|
| `id` | text | required | Section id, `[a-z0-9][a-z0-9-]*`, ≤ 64. Becomes the marker id `<!-- mm3:section:<id> -->`. Unique in the template. `_system` is reserved. |
| `title` | text | required | The `## ` heading in the note. |
| `kind` | `narrative` \| `extraction` | required | Drives the default temperature (§4). |
| `format` | `markdown` \| `tasks` \| `bullets` | `markdown` | Post-processing (§5). |
| `temperature` | number 0–2 | none | Overrides the default for this section. |
| `max_tokens` | integer ≥ 64 | `params.max_tokens_per_section` | Output limit for this section. |

Common section ids (reuse them so regeneration and future tooling stay consistent): `summary`,
`key-points`, `decisions`, `action-items`, `open-questions`, `next-steps`, `ai-recommendations`.

### 3.2 Params
| Key | Type | Default | Meaning |
|---|---|---|---|
| `temperature` | number 0–2 or `null` | `null` | Overrides the per-kind default for every section without its own `temperature`. |
| `max_tokens_per_section` | integer ≥ 64 | `800` | Default output limit. |
| `ai_recommendations` | boolean | `true` | When `true`, the template **must** have an `ai-recommendations` section and it **must be last** (spec §8, Appendix A). When `false` (e.g. formal board minutes), it must not have one. |

## 4. Temperatures (R6)
`section.temperature` → `params.temperature` → the kind default: **0.2** for `extraction`
(decisions, action items, open questions, facts) and **0.4** for `narrative` (summaries,
AI Recommendations).

## 5. Prompt blocks
* `_system` (required): the template's persona and house rules. It is added to MeetingMaster3's
  global rules (which already forbid invented owners and dates, demand attribution and ban
  filler), so it only needs what is specific to the template.
* One block per section id (required): what the section must contain and an **example of its
  structure**. Examples should use placeholders such as `<Name>`, not realistic content the model
  could copy into a note.
* The model returns **only the section body**: no heading, no markers. MM3 post-processes every
  answer: strips a reasoning block (`<think>…</think>`), a wrapping code fence, a leading heading,
  and any `mm3` marker-like lines; demotes `#`/`##` headings to `###`; trims blank lines.
  * `format: tasks`: every list item becomes an Obsidian checkbox
    `- [ ] **<Owner>:** <task> (due: <date or "not stated">)`. Items the model already ticked
    (`- [x]`) stay ticked.
  * `format: bullets`: `*` and `+` bullets become `-`.
* The Appendix B header (title, date, participants, tags, location; R10) is rendered by code from
  the meeting metadata. Templates do not ask for it.

## 6. Validation
A template is loaded only if it passes every check below. Each problem is reported with a code,
a message and a **1-based line number** in the file (`0` when it concerns the whole file), and an
invalid template is listed with its errors instead of crashing the app.

| Code | Problem |
|---|---|
| `no_frontmatter` / `frontmatter_unclosed` | No `---` block at the top, or no closing `---`. |
| `yaml_error` | The frontmatter is not valid YAML (line of the YAML error). |
| `schema_error` | A key is missing or has the wrong type or value (line of the key). |
| `unsupported_version` | `mm3-template` is not `1`. |
| `duplicate_section_id` | Two sections share an id. |
| `reserved_section_id` | A section is called `_system`. |
| `ai_recommendations_missing` / `ai_recommendations_not_last` / `ai_recommendations_disabled` | See `params.ai_recommendations`. |
| `missing_prompt` | A section, or `_system`, has no prompt block (line of the section). |
| `unknown_prompt` | A prompt block names no section (line of the marker). |
| `duplicate_prompt` | Two blocks for one id (line of the second). |
| `empty_prompt` | A block has no text. |
| `malformed_prompt_marker` | A line that looks like a prompt marker but is not one. |
| `duplicate_template_id` | Two vault templates share an `id`. |
| `file_too_large` | Larger than 256 KiB. |

Warnings (the template still loads): `unknown_key`.

`mm3 templates validate [PATH...]` prints the same report.

## 7. How the prompt is assembled
For each section, one chat request (see `templates/assembler.py`):
* **System message:** MM3's global rules; the template's `_system` block; the meeting facts
  (title, date, participants and the speaker list, location); and today's date, so relative
  deadlines ("by Friday") can be resolved against the meeting date.
* **User message:** the transcript (or, for long meetings, the merged map-reduce notes) **first**,
  formatted as `[mm:ss] Name: text` per speaker turn (`[h:mm:ss]` past one hour); then the section
  title and its prompt block; optional user instructions; on regeneration the previous section
  content and the user's feedback; and the output rules.

Because the system message and the transcript are identical for every section of a note, a local
Ollama reuses its prompt cache and only processes the short section-specific tail (ADR-0017).

## 8. Long meetings (map-reduce, R6, ADR-0016)
If the system message, the transcript, the longest section prompt and the output reserve exceed
70 % of the model's context window, MM3 switches to map-reduce:
1. **Map:** the transcript is cut into chunks on speaker-turn boundaries
   (`llm.budget.chunk_transcript`), and each chunk is turned into a JSON extraction: a summary plus
   points, decisions, actions and questions, each with a `[mm:ss]` timestamp and a speaker. Bad
   JSON is repaired (code fences, surrounding prose, trailing commas) and, if still invalid,
   requested once more with the parser error; a chunk that still fails is skipped with a warning.
2. **Merge:** the extractions are concatenated in time order and near-duplicates (the same
   decision, action or question restated in two chunks, e.g. in the overlap turn) are removed.
3. **Reduce:** every section is generated from the merged notes instead of the raw transcript.
