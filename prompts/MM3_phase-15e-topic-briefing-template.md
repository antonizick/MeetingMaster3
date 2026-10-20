# Phase 15e: Topic Briefing template (the "Plaud Clone" request)

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 15b · **Branch:** `phase-15e-topic-briefing-template` · **Worktree:** `../MeetingMaster3-phase-15e`

Part of the third tuning round (ADR-0030, ADR-0034; planned with `/phase-add`, split in ADR-0037). Nick compared
MeetingMaster3's notes with the notes a commercial AI recorder (Plaud) produced from **the same meetings** and wants a
built-in template that writes notes like those: organised by topic, dense with specifics, followed by a conclusion
and owned action items. Everything MM3 already does for metadata and naming stays. This phase only touches the
template library and its tests and docs, so **it can run in parallel with 15c and 15d**.

## Read first
- `CLAUDE.md`, `prompts/MM3_shared-instructions.md`, `docs/MM3_SPECIFICATION.md` §15 (A3 template count, R22 templates
  and generation, R25(c) the two summaries).
- `docs/dev-guide/template-format.md` (whole file; §10 lists the conventions every built-in follows).
- Phase Log entries for Phases 09, 13, 15 (eval baseline), 15a (two summaries, eval word targets) and the
  15c/15d/15e planning entry (2026-10-14).
- ADR-0003, ADR-0016 (map-reduce), ADR-0017 (prompt layout, small-model aids), ADR-0023 (stage-2 library, shared
  section ids), ADR-0031, **ADR-0037** (name and shape decided).
- The closest existing templates: `starter_templates/general-discussion-summary.md`, `detailed-meeting-minutes.md`,
  `key-takeaways-next-steps.md`, `job-interview-notes.md`, `action-focused.md`.

## Nick's request (verbatim intent, 2026-10-14)
"I would like another template created called 'Plaud Clone'. Examples of the required template results are here:
`/home/nick/Downloads/temp`. The new template should keep all of our existing naming standards and metadata habits.
I don't want to lose any of that. Also, I want to have an extremely concise summary first, with a more detailed
meeting summary below that. However, the sample meeting notes I referenced above should provide guidance on the
sections for the new template, the type of content and quantity of content we would want the new template to
produce. Those samples were derived exactly from three of the meetings within our MeetingMaster3 program, so you
have an exact example of the source material transcripts, and what the sample data shows you is what the output of
the template should produce from meetings like those."

## Decisions already made (ADR-0037)
- **Name:** the built-in template has a **neutral public name**, not "Plaud Clone". "Plaud" is another company's
  product name, and built-ins are published in Phase 16. Default: **Topic Briefing**, id `topic-briefing`. Its
  description describes the style in plain words, with no brand. If Nick agrees during the session, also make a
  personal **vault copy** named "Plaud Clone" (id `plaud-clone`) through the library's copy function. It lives only in
  his vault and is never committed.
- **Shape: topic-based**, one structure for every kind of meeting. Do not use the interview-specific layout of the
  09-22 sample (candidate synopsis, strengths, concerns) as the template's structure. Its *density* and its Q&A
  section are still guidance.
- **The samples and the real transcripts are personal data.** Never commit them, quote them in committed files,
  or put them in fixtures, golden files, the eval baseline or the Phase Log. Use them only locally to compare.

## Goal
A 23rd built-in template whose notes, on Nick's real meetings and the recommended local model (`qwen3:8b`, 8 GB),
come close to the Plaud samples in sections, kind of content and quantity of content, while keeping MM3's
frontmatter, header, file names, section markers, timestamps and task format.

## What exists (verified 2026-10-14; re-check before relying on it)
- **Samples** (`/home/nick/Downloads/temp/`; copies also sit as non-MM3 files in Nick's vault
  `MM3.Meetings/2026/`). They show three layouts:
  - `13 Aug Tenent Caleb Nick Introductory Call.md` (~1,290 words): an *Interview Information* block (date & time,
    location, interviewer, interviewee); **Viewpoints** made of 9 numbered `### N. <Topic>` headings, each with 2-3
    `- <Bold label>:` points followed by a dense 2-5 sentence paragraph (numbers, product names, org changes);
    a one-paragraph **Conclusion**; **Next Arrangements** as checkboxes.
  - `18 Aug 2026 Tenent Caleb Nick Follow on introductory call.md` (~1,180 words): a one-paragraph overview, then
    5 `##` topic sections of 2-3 prose paragraphs each, separated by `---`, and **Action Items** grouped by person
    (`**@Speaker 3 (Caleb)**`, then checkboxes with `[TBD]` deadlines).
  - `09-22 Interview Nick Antonizick - SOC Manager Cyber Defense Candidate.md` (~2,870 words): an interview
    assessment layout (synopsis with numbered history, job expectations, strengths said-by-interviewer /
    self-reported, concerns, exploration per experience, a long **Q&A** split into interviewer's and interviewee's
    questions with `> A:` answers, to-dos).
- **The matching MM3 meetings** (companion transcripts in Nick's vault): `MM3.Meetings/2026/2026-08-13 - Interview
  Nick for SOC Management Role.transcript.md` (59:19, Nick and Caleb) ↔ the 13 Aug sample, and `2026-09-22 - 09-22
  Interview Nick Antoncic - SOC Manager Cyber Defense Candidate.transcript.md` (Caleb, Nick, Fritz, Harry) ↔ the
  09-22 sample. **No MM3 meeting obviously matches the 18 Aug sample.** The only other MM3 meeting is
  `2026-10-10 - 10-10 Michelle Meeting …`, and Nick says the "09-22" meeting really happened on 18 August. Confirm the
  mapping with Nick at the start. If the 18 Aug source is not in MM3, use that sample for style only. (Phase 15d may
  have renamed the 09-22 meeting by the time this runs. Look it up by `mm3-id 4cbf8a4b-…`.)
- **What MM3 adds around any template** (keep it; it comes from the writer, not the template):
  frontmatter (`title`, `date`, `participants`, `tags`, `location`, `mm3-*`), the H1, header lines (Date & Time,
  Participants, Tags, Location / Context, Transcript link), file names `YYYY-MM-DD - Title.md`, section markers,
  `[mm:ss]` references, and archives. The template cannot and must not change these.
- **Template conventions** (`template-format.md` §10, enforced by tests): file name = id; `summary` ("Summary
  Succinct") directly followed by `summary-detailed` ("Summary Detailed") first; `action-items` uses `format: tasks`
  with the `**Unassigned:**` line and owner rule; `ai-recommendations` last; reuse common section ids; golden
  prompt snapshots in `tests/fixtures/assembler/<id>.txt`; the catalogue `docs/user-guide/template-catalogue.md` is
  generated (`scripts/gen_template_catalogue.py`, CI `--check`).
- **Eval:** `tests/eval/` (`run_eval.py`, `checker.py`, `baseline.json`, synthetic meetings in `tests/eval/meetings/*.yaml`),
  run with `MM3_EVAL_MODEL=qwen3:8b uv run pytest tests/eval -s`. Checks include `detailed_paragraphs`,
  `detailed_prose`, `detailed_length`, `succinct_short`.
- **Counts that say 22:** spec §15.1 A3, README (lines ~14, 20, 111), `docs/MM3_ARCHITECTURE.md` (~198),
  `docs/dev-guide/template-format.md` §10, `docs/user-guide/template-catalogue.md`, `docs/user-guide/README.md`,
  `tests/unit/templates/test_cli.py` (`count(" ok ") == 22`), the plan's MVP definition of done ("22 templates").
  `grep -rn "22" --include=*.md --include=*.py` to find the rest.

## Tasks
1. **Study the samples against the transcripts** (locally): for each pair, list the sample's sections, word counts
   per section, the number of topics, the kinds of details kept (figures, product names, org changes, dates,
   opinions attributed to people) and what was left out. Write a short **anonymised** summary of the findings (no
   names, no employer details) for the ADR. Use it to set the targets below and adjust them if the evidence
   disagrees.
2. **Write `starter_templates/topic-briefing.md`**. Default sections (adjust with evidence and justify):
   - `summary`, **Summary Succinct**: *extremely* concise, 1-2 sentences and at most about 50 words (stricter
     than the other templates; Nick asked for it);
   - `summary-detailed`, **Summary Detailed**: as R25(c) (prose, 2-4 paragraphs, about 200-450 words);
   - `meeting-context`, **Meeting Context**: purpose, who took part and in what role (interviewer, candidate,
     client…) as stated, and the setting if said. Short bullets. Do not repeat the header's date and participant
     list verbatim;
   - `topics`, **Discussion by Topic**: the core. 4-9 numbered `### N. <Topic title>` headings in the order
     discussed, each with 2-4 `- **<Label>:**` points followed by a dense paragraph of 2-5 sentences that keeps
     specifics (numbers, names of tools and organisations, dates, who said what), with `[mm:ss]` on each point. The
     quantity should follow the sample (about 900-1,500 words for a 60-minute meeting, scaling with length). Large
     `max_tokens`. Test map-reduce on long meetings (the reduce step must still produce numbered topics);
   - `questions-answers`, **Questions & Answers**: only when a large part of the meeting was questions and
     answers (interviews, Q&A sessions). Each question as asked (shortened) with a `> A:` answer of 1-4 sentences,
     grouped by who asked. Otherwise write exactly: "No question-and-answer exchange to record.";
   - `conclusion`, **Conclusion**: one paragraph, 3-6 sentences, on outcome, fit or alignment and open points;
   - `action-items`, **Action Items**: `format: tasks`, grouped by owner in MM3's standard structure (`- [ ]
     **<Owner>:** … (due: …) [mm:ss]`, `**Unassigned:**` last). This replaces the sample's `@Speaker` grouping
     and keeps the MM3 convention;
   - `ai-recommendations` last (standard).
   `_system`: a meticulous executive assistant writing a briefing for someone who missed the meeting. Specific
   beats generic. Attribute views to the people who held them. Never invent. Keep job-relevant-only and
   no-protected-characteristics rules when the meeting is an interview (borrow the wording from
   `job-interview-notes`; consider adding it to `test_sensitive_templates_keep_their_guardrails`).
3. **Generator support, only if needed:** if `succinct_short` or the two-summary checks assume more than 2
   sentences, add a per-template override (for example a `params` key) rather than a special case. Any change to
   the template schema needs an update to `template-format.md` and validation tests. Prefer pure prompt work.
4. **Tests and fixtures:** golden prompt snapshot (`MM3_UPDATE_GOLDEN=1`), schema validity, the count updates
   (22 → 23), the regenerated catalogue, and one new **synthetic** eval meeting whose shape is like the samples
   (a 40-60 minute interview-style or intro call with figures, org changes and Q&A) under `tests/eval/meetings/`,
   with checks for numbered topics, the topic count range, specifics retained, the Q&A behaviour and the succinct
   length.
5. **Private comparison** (not committed): a script or an env-driven pytest (`MM3_PRIVATE_EVAL_DIR` pointing at a
   folder Nick names, skipped when unset) that generates Topic Briefing notes for the matched real meetings and
   prints, per section, the word count beside the sample's, the topic headings side by side, and the coverage of
   the sample's key specifics (checked by hand or with a simple term-overlap score). Keep the outputs in the
   scratchpad or app data, never in the repo.
6. **Iterate** on the prompts until the real-meeting notes meet the acceptance criteria. Record the iterations
   (what changed, why, measured effect) in the ADR, without personal content.

## Out of scope
- Changing how MM3 writes frontmatter, headers, file names or archives.
- Interview-specific or per-meeting-type layouts (decided against; a later template could add them).
- Backfilling existing notes with the new template (the user can use Switch template).

## Tests
- `uv run pytest` including `tests/unit/templates/` (schema, summaries order, guardrails, assembler golden,
  catalogue, CLI count).
- `MM3_EVAL_MODEL=qwen3:8b uv run pytest tests/eval -s -k topic-briefing` passes, and a full eval run shows no
  regression against `tests/eval/baseline.json` (update the baseline only for the new template's entries).

## Acceptance criteria
- Topic Briefing appears in the library and the upload picker, and its notes have MM3's usual frontmatter,
  header, file names and markers.
- On Nick's matched real meetings with `qwen3:8b`: Summary Succinct is 1-2 sentences; Discussion by Topic has 4-9
  numbered topics in a word range comparable to the sample (record the numbers); most of the sample's key specifics
  appear; action items have owners; there are no invented facts (spot-check against the transcript). **Nick reads at
  least one generated note beside its sample and agrees it is "Plaud-like".** Record his verdict.
- Generation time per note is recorded (it will be longer than the other templates; make sure it is still
  acceptable on 8 GB and note it in `docs/PERFORMANCE.md`).
- `ruff check`, `ruff format --check`, `uv run mypy src` and CI's catalogue `--check` pass, and the `mypy src
  tests` error count is no higher than on `main`.

## Phase-specific docs
- `docs/MM3_SPECIFICATION.md` §15: amendment **R29** (a 23rd built-in template, amending A3's count, and its
  structure). Take the next free number if it is used.
- ADR (next free number on `main` at close-out; 15c may run in parallel): the template's design, the anonymised
  sample analysis, the targets and the prompt iterations.
- README (template count and list), `docs/MM3_ARCHITECTURE.md`, `docs/dev-guide/template-format.md` §10, the generated
  catalogue, `docs/user-guide/README.md`, `docs/PERFORMANCE.md`, `CHANGELOG.md`, and the MVP definition-of-done line
  in `MM3_IMPLEMENTATION_PLAN.md` ("22 templates" → "23").
- `prompts/MM3_phase-16-release.md` if it names a template count.

Then the standard close-out checklist.
