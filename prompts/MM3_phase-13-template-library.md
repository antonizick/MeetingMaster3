# Phase 13: Expanded Template Library (22 Templates)

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 09 (can run in parallel with 10–12) · **Branch:** `phase-13-template-library`

## Read first
`CLAUDE.md`, `prompts/MM3_shared-instructions.md`, and `docs/MM3_SPECIFICATION.md` §6, §15.1 (A3), and Appendices A and B. `docs/dev-guide/template-format.md` (normative, Phase 09). The 5 stage-1 templates in `src/meetingmaster3/starter_templates/` (match their quality and conventions). Phase 09's Phase Log entry (eval scores and prompt lessons).

**Phase 09 interfaces:** the template schema already supports `params.ai_recommendations: false` (the template must then have no `ai-recommendations` section), per-section `temperature`, `max_tokens` and `format` (`markdown`, `tasks`, `bullets`). Golden snapshots: extend `tests/unit/templates/test_assembler.py` (it is parametrised over `builtin_files()`, so new templates get snapshots automatically; regenerate with `MM3_UPDATE_GOLDEN=1`). `tests/unit/templates/test_schema.py::test_builtin_templates_are_valid` checks every shipped file, and `test_five_stage_one_templates_ship` must be updated to the full list. Quality: run `uv run python -m tests.eval.run_eval --model qwen3:8b --templates <id>` (synthetic meetings in `tests/eval/meetings/`; add meetings for interviews, stand-ups or board minutes as needed, CC0 and fictional). Prompt lessons from Phase 09 are in `docs/dev-guide/template-format.md` §8: placeholders not realistic examples, an explicit "nothing here" sentence per section, keep the `**Unassigned:**` structure line in task sections, and say what does not belong in a section.

## Goal
Ship the remaining **17 templates** so the built-in library has 22. Each one is purpose-built, validated, and produces distinctly useful output for its meeting type.

## Templates to author (Appendix A numbering)
1 General Discussion Summary · 3 Strategic Meeting Summary · 5 Detailed Meeting Minutes · 6 Job Interview Notes · 7 Multi-Participant Project Team Sync · 9 Brainstorming / Ideation Capture · 10 Sales / Client Call Summary · 11 Agile Stand-up Notes · 12 One-on-One / Coaching Notes · 13 Formal Board / Governance Minutes · 14 Workshop / Training Recap · 15 Retrospective / Lessons Learned · 16 Q&A Extraction · 17 Speaker-Attributed Notes · 18 Chronological Timeline · 19 Risks, Issues & Mitigations · 20 Key Takeaways + Next Steps

(Stage 1 already covers 2 Executive Summary, 4 Action-Item as Action-Focused, 8 Decision Log, plus Technical Deep-Dive and Just the Facts.)

## Tasks
1. For each template: a kebab-case `id`, name, description, tags, a section list suited to the meeting type (reusing the common section ids `summary`, `decisions`, `action-items`, `open-questions`, `next-steps` and `ai-recommendations` where they fit, so regeneration and future tooling stay consistent; add type-specific ids such as `candidate-strengths`, `hiring-recommendation`, `motions-and-votes`, `blockers`), and section prompts with structural examples. `ai-recommendations` is always last. Where an "AI Recommendations" section is inappropriate (e.g. Formal Board Minutes), make it optional through a template param, and document the exception.
2. **Sensitive templates:** Job Interview Notes must avoid commentary on protected characteristics (age, gender, ethnicity, religion, disability, family status, etc.), stick to job-relevant evidence, and include a reminder that hiring recommendations are advisory. One-on-One and Coaching Notes use a respectful, non-judgmental tone. Board Minutes use formal style and record motions and votes exactly as stated, never inferring outcomes.
3. **Fit with Nick's existing notes:** the `/home/nick/Documents/02 Projects/` folder contains example meeting summaries (e.g. interview summaries). Read 1–2 of them **for style only**: structure, tone and heading conventions. **Do not copy any content from them into the repo**, because they contain private information.
4. **Validation and tests:** every template passes the loader validation. Golden assembler snapshots for each template against a fixed synthetic transcript. A parametrised test asserts the invariants: unique ids, `ai-recommendations` last or explicitly disabled, every section has a prompt block, the header is included, and `format: tasks` is used for action sections.
5. **Eval:** extend `tests/eval/` with 4–5 new synthetic transcripts that match key types (interview, stand-up, retrospective, board meeting, sales call). Run the eval with the recommended 8 GB local model and record the results in the Phase Log. Fix prompts that fail the checks.
6. **Template index:** generate `docs/user-guide/template-catalogue.md` (name, when to use it, sections) from the template files with a script (`scripts/gen_template_catalogue.py`), so it never drifts. CI checks that the generated file is up to date.

## Acceptance criteria
- 22 built-in templates, all valid, all with golden snapshots, and the catalogue doc generated.
- The eval passes for the 5 type-specific transcripts on the local model.
- Templates install into the vault without overwriting the user's modified copies (Phase 09 behaviour unchanged).

## Phase-specific docs
The template catalogue (generated), `docs/user-guide/templates.md` (pointer to the catalogue, tips for choosing), README feature list (22 templates), CHANGELOG. Then the standard close-out checklist.
