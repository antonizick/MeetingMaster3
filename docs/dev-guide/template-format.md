# Template Format (normative)

> **Status:** normative since Phase 09 (template schema version 1). The loader
> (`src/meetingmaster3/templates/`) and every shipped or user template must follow this page; if
> the code and this page disagree, that is a bug in one of them. Spec: §6, §8, §15.1 A3, §15.2 R6
> and R10, R22. Decisions: ADR-0016 (map-reduce), ADR-0017 (prompt layout, temperatures and the
> deterministic aids), ADR-0018 (stages).

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
  never overwritten. Since Phase 15a the app also refreshes those unedited copies at start-up when
  a newer built-in ships (`ensure_installed`; a built-in the user deleted is not brought back), and
  the library flags an edited copy whose built-in changed (`newer_builtins`). `planning_library`
  gives the library as it will be after that refresh without writing (dry runs of
  `mm3 notes upgrade`).

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
  - {id: summary, title: Summary Succinct, kind: narrative}
  - {id: summary-detailed, title: Summary Detailed, kind: narrative, max_tokens: 1000}
  - {id: decisions, title: Decisions Made, kind: extraction}
  - {id: action-items, title: Action Items, kind: extraction, format: tasks}
  - {id: ai-recommendations, title: AI Recommendations, kind: narrative}
params: {temperature: null, max_tokens_per_section: 800}
---
<!-- mm3:prompt:_system -->
You are writing for a busy executive ...

<!-- mm3:prompt:summary -->
Write 2-4 sentences ...

<!-- mm3:prompt:summary-detailed -->
Write a detailed summary ... typically three paragraphs and never fewer than two ...

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
`summary-detailed`, `key-points`, `decisions`, `action-items`, `open-questions`, `next-steps`,
`ai-recommendations`.

**Two summaries (Phase 15a, R25, ADR-0031).** `summary` is the short one (titled "Summary
Succinct" in the built-ins; the id stays `summary` so older notes, regeneration and ratings keep
working). `summary-detailed` follows it: prose, typically three paragraphs (context and purpose; the
threads of discussion with who said what; outcomes, decisions and open questions), about 1 000 output
tokens. The generator enforces a floor for this id: fewer than two paragraphs
(`templates/postprocess.count_paragraphs`) triggers one retry with a firmer instruction, then the
better answer is kept and the job gets a warning; nothing is padded.

### 3.2 Params
| Key | Type | Default | Meaning |
|---|---|---|---|
| `temperature` | number 0–2 or `null` | `null` | Overrides the per-kind default for every section without its own `temperature`. |
| `max_tokens_per_section` | integer ≥ 64 | `800` | Default output limit. |
| `ai_recommendations` | boolean | `true` | When `true`, the template **must** have an `ai-recommendations` section and it **must be last** (spec §8, Appendix A). When `false` (e.g. formal board minutes), it must not have one. |
| `detail` | `standard` \| `high` | `standard` | How much of a long meeting the map-reduce notes keep (§9, ADR-0039). `high` is for templates that write dense, topic-by-topic notes (`default-notes`): each part keeps up to 30 points with their specifics and a topic label, and the questions that were answered, at the cost of a longer map step. |
| `task_candidates` | `all` \| `relevant` | `all` | Which candidate sentences task sections see (§7, ADR-0039). `all`: every candidate, and every commitment in the list must appear as a task. `relevant`: only the candidates that name follow-up work (send, schedule, review, prepare, sync…; `templates.cues.follow_up_cues`), as hints, in the map step too; for templates whose meetings are informal conversations (`default-notes`), where most "I'll …" sentences are not tasks. The owner guard still checks every candidate. |

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
  * `format: tasks`: every top-level list item becomes an Obsidian checkbox
    `- [ ] **<Owner>:** <task> (due: <deadline as said, or "not stated">)`; items the model
    already ticked (`- [x]`) stay ticked. Deadlines said as "today", "tomorrow", a weekday,
    "next <weekday>" or "<weekday> next week" get their date appended from the meeting date
    (`(due: Friday, 2026-10-09)`): the model is told *not* to compute dates (ADR-0017). Then the
    **owner guard** runs: a named owner who only suggested ("we should…") or declined the task, and
    never committed to it or was asked to do it, is replaced by `Unassigned`.
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
| `unreadable` | Not readable as UTF-8 text. |

Warnings (the template still loads): `unknown_key`.

`mm3 templates validate [PATH...]` prints the same report.

## 7. How the prompt is assembled
For each section, one chat request (see `templates/assembler.py`):
* **System message:** MM3's global rules; the template's `_system` block; the meeting facts
  (title, date, participants and the speaker list, location); and today's date, so relative
  deadlines ("by Friday") can be resolved against the meeting date.
* **User message:** the transcript (or, for long meetings, the merged map-reduce notes) **first**,
  formatted as `[mm:ss] Name: text` per speaker turn (`[h:mm:ss]` past one hour); then the section
  title and its prompt block; for `format: tasks` sections, the **task candidates**: transcript
  sentences that sound like a commitment, a request, a suggestion or a refusal, tagged by kind
  (`templates/cues.py`), with the rule that every commitment must appear (with
  `params.task_candidates: relevant`, only the candidates that name follow-up work, as hints); optional user instructions; on regeneration the previous section content
  and the user's feedback; and the output rules.
* One request per section, with the section's temperature and `max_tokens`, one `num_ctx` for the
  whole note, and `think: false` for reasoning models unless `generation.think` is set.
* **`num_ctx`** (ADR-0043) is the estimated size of the note's **largest real call** plus a 10 %
  margin (Ollama silently drops the start of a prompt that does not fit), rounded up to 1 024 and
  capped by the window. A section call counts its prompt and `max_tokens` (Summary Detailed also
  its paragraph retry; a regeneration its previous body and feedback); in map-reduce the map calls
  are built first and count their prompt, output room and a repair turn, and the reduce notes are
  then cut to fit, counted at 1.15 real tokens per estimated token (`NOTES_DENSITY`). Estimates use
  4 characters per token; on qwen3, transcript-sized calls measured 0.97-1.01 real tokens per
  estimated token, and the denser merged notes up to 1.115.

Because the system message and the transcript are identical for every section of a note, a local
Ollama reuses its prompt cache and only processes the short section-specific tail (ADR-0017).

## 8. Writing good template prompts
Lessons from the Phase 09 eval (`tests/eval/`, small local models):
* Show the structure with **placeholders** (`<Owner>`, `<task>`), never with realistic values: models
  copy example dates and names into notes.
* Give every section an explicit "nothing here" sentence ("If no decision was made, write exactly:
  No decisions were made."), so the model does not invent content to fill it.
* For task sections, keep the `**Unassigned:**` example line in the structure and the owner rule in
  the prompt; the candidates and the owner guard rely on them.
* Say what does **not** belong in a section (e.g. task assignments are not decisions).
* Check a change with `uv run python -m tests.eval.run_eval --model <model> --templates <id>`.

## 9. Long meetings (map-reduce, R6, ADR-0016)
If the system message, the transcript, the longest section prompt and the output reserve exceed
70 % of the model's context window, MM3 switches to map-reduce:
1. **Map:** the transcript is cut into chunks on speaker-turn boundaries
   (`llm.budget.chunk_transcript`, counting each turn's `[mm:ss]` stamp), and each chunk is turned into a JSON extraction: a summary plus
   decisions, actions, questions and (last, at most 10) key points, each with a `[mm:ss]`
   timestamp and a speaker. With `params.detail: high` each chunk keeps up to 30 points of up to
   40 words, with their figures and names and a `topic` label, plus up to 10 answered questions
   (`exchanges`: who asked, the question, who answered, the answer), and the map call gets 3 500
   output tokens instead of 1 500, so the chunks are smaller. If the window is too small for that,
   the template falls back to standard notes. The reduce step then sees the points as
   `- [mm:ss] (topic) Name: text` and a "Questions and answers" list. Bad JSON is repaired (code fences, surrounding prose, trailing commas,
   an answer cut off by the output limit) and, if still invalid, requested once more with the
   parser error (or shorter); a chunk that still fails is skipped with a warning.
2. **Merge:** the extractions are concatenated in time order and near-duplicates (the same
   decision, action or question restated in two chunks, e.g. in the overlap turn) are removed.
3. **Reduce:** every section is generated from the merged notes instead of the raw transcript.

## 10. The built-in library (Phase 13)
24 templates ship in `starter_templates/` (spec §15.1 A3, Appendix A; the 23rd, `default-notes`,
is R29 and the default template; the 24th, `create-project-plan`, is R33). Conventions they follow, which
new built-ins should too:
* The file name is the `id` (`test_builtin_templates_are_valid` checks it), kebab-case.
* Reuse the common section ids (§3.1) where the section means the same thing; type-specific ids
  (`candidate-strengths`, `motions-and-votes`, `went-well`, `risks`) are fine beside them.
* A section called `action-items` has `format: tasks` and its prompt keeps the `**Unassigned:**`
  structure line and the owner rule (§8).
* `summary` (title "Summary Succinct") is followed directly by `summary-detailed` (title "Summary
  Detailed"), first in the note except in `board-governance-minutes` (after Attendance & Quorum)
  (`tests/unit/templates/test_summaries.py`).
* `ai-recommendations` is last. The only built-in with `params.ai_recommendations: false` is
  `board-governance-minutes`: a formal record must not carry generated commentary
  (`AI_RECOMMENDATIONS_EXCEPTIONS` in `tests/unit/templates/test_schema.py`).
* Sensitive types carry their rules in `_system` and are guarded by
  `test_sensitive_templates_keep_their_guardrails`: `job-interview-notes` (job-relevant evidence
  only, no protected characteristics, advisory recommendation), `one-on-one-coaching` (respectful,
  non-judgmental tone), `board-governance-minutes` (formal style, motions and votes exactly as
  stated, never an inferred outcome), `default-notes` (used for interviews too: the
  job-relevant-only and protected-characteristics rules, no hiring decision; with `qwen3:8b` it can
  still keep a family remark a candidate volunteers, a known limitation recorded in the eval
  baseline, ADR-0039), and `create-project-plan` (the owner decides and the AI assistant only
  proposes: an assistant suggestion is never presented as decided unless the owner accepted it;
  external claims go to Facts to Verify as unverified; nothing is invented; R33).
* Golden prompt snapshots are in `tests/fixtures/assembler/<id>.txt`
  (`MM3_UPDATE_GOLDEN=1 uv run pytest tests/unit/templates/test_assembler.py`).
* `docs/user-guide/template-catalogue.md` is generated: after changing a template run
  `uv run python scripts/gen_template_catalogue.py` (CI runs it with `--check`, and
  `tests/unit/templates/test_catalogue.py` fails when it is stale).
* Type-specific eval meetings declare `templates: [id]` in their YAML and may list
  `expected.sections` (keywords that must appear in a section) and `expected.forbidden` (words that
  must not appear anywhere in the note). Since Phase 15e they may also list `expected.numbered`
  (`{section, min, max}`: the number of `### N. <Title>` headings in a section) and
  `expected.limits` (`{section, max_sentences, max_words}`). Since Phase 15m, `expected.numbered`
  takes `style: list` to count top-level `N.` list items instead of headings, `expected.absent`
  (`{section, any}`) lists words that must not appear in one section (a rejected option in
  Decisions), and a meeting with `timed: false` is an untimed conversation whose turns are
  `[label, text]` (R32). Run one with
  `uv run python -m tests.eval.run_eval --model qwen3:8b --meetings <name> --templates <id>`.
