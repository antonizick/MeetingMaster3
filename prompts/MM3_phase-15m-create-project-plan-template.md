# Phase 15m: Create Project Plan template (a pre-plan for Claude Code)

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 15k · **Branch:** `phase-15m-create-project-plan-template` · **Worktree:** `../MeetingMaster3-phase-15m`

Inserted with `/phase-add` after 15j, behind 15k (ADR-0034, ADR-0052). Nick often works out a project idea in a long
conversation with an AI assistant (or in a planning meeting) and then wants to start building it with Claude Code.
His standard way to start a multi-session build is the `phased-project` skill (`/phased-project <plan doc> <repo
dir>`), which reads "a plan, pre-plan, spec or idea document", reviews it, asks him the owner decisions and writes
the spec, ADRs, phases and prompts. This phase adds a 24th built-in template, **Create Project Plan**, that turns a
conversation into exactly that kind of document: a pre-plan that separates what Nick decided from what the AI merely
suggested, and flags the facts that still need checking. It works on imported AI conversations (15k, 15l) and on
recorded meetings alike. It only touches the template library, its tests and docs (plus the generator if Task 4
needs it), so **it can run in parallel with 15l**.

## Read first
- `CLAUDE.md`, `prompts/MM3_shared-instructions.md`, `docs/MM3_SPECIFICATION.md` §15 (A3 template count, R6
  map-reduce, R22 templates, R25(c) the two summaries, R29 Default Notes and `params.detail`, **R32** from 15k).
- `docs/dev-guide/template-format.md` (whole file; §8 prompt-writing rules, §9 map-reduce, §10 built-in
  conventions enforced by tests).
- **ADR-0052** (including "Phase 15k implementation") and the **Phase 15k Phase Log entry**: untimed transcripts,
  speaker roles of imported conversations (`user` / `assistant`), names used.
- ADR-0016, ADR-0017 (prompt layout, small-model aids), ADR-0023 (shared section ids), ADR-0039 (`params.detail`,
  `task_candidates`), ADR-0043 (context sizing).
- The phased-project method: `~/.claude/skills/phased-project/SKILL.md` ("Workflow" steps 2-6: what it does with a
  source document) and `/home/nick/Documents/04 Resources/Claude Code Phased Project Method.md`. The output of this
  template is that workflow's **input**.
- The closest built-ins: `starter_templates/decision-log.md`, `project-team-sync.md`, `brainstorming-ideation.md`,
  `key-takeaways-next-steps.md`, `default-notes.md`.

## Nick's request (verbatim intent, 2026-10-24 11:20 CDT)
"I would like to create a new template called 'Create Project Plan'. Using the attached example AI conversation
(again) This is a typical example of the sort of conversation I would have with an AI agent. I would like the 'Create
Project Plan' to derive a good project plan from this that I can hand to my Claude Code environment to start working
on a project with."

During intake he chose: the template produces **input for `/phased-project`** (a pre-plan: goal, scope, requirements,
decisions made and open, architecture or stack, rough phases, risks, acceptance), not the full phased plan itself.
The example conversation is private (below).

## Decisions already made (ADR-0052)
- **Name and id:** "Create Project Plan", id `create-project-plan` (Nick's name; it is neutral, no product name).
  Not the default template; Default Notes stays the default.
- **Shape: a pre-plan for `/phased-project`.** The note is a source document Claude Code can review and refine. It does
  not invent phases, tasks or acceptance tests the conversation does not support; a rough, ordered list of milestones
  is enough, and the phased-project skill does the detailed design.
- **The example conversation is private.** `/home/nick/Documents/01 Inbox/privacy project brainstorming.md` (and its
  share link) is used only locally to compare (copy to `~/.local/share/meetingmaster3/private-eval-15m/`, deleted at
  close-out). Never commit it, quote it in committed files, or put it in fixtures, golden files, the eval baseline or
  the Phase Log. Eval conversations are synthetic.

## Goal
Nick imports his AI conversation (or records a planning meeting), picks **Create Project Plan**, and gets a note he can
pass straight to Claude Code (`/phased-project "<note path>" <repo dir>`): a faithful, well-organised pre-plan of the
project discussed, with his decisions, the AI's unconfirmed suggestions and the claims to verify kept apart, good
enough that the phased-project skill's review needs few corrections.

## What exists (verified 2026-10-24 11:39 CDT; re-check before relying on it)
- **Template library:** 23 built-ins in `src/meetingmaster3/starter_templates/` (`default-notes` is the default).
  Conventions and tests: `template-format.md` §10 (`summary` then `summary-detailed` first; `action-items` with
  `format: tasks` and the `**Unassigned:**` line; `ai-recommendations` last; shared section ids; golden prompts in
  `tests/fixtures/assembler/<id>.txt`; generated `docs/user-guide/template-catalogue.md`).
- **Counts that say 23:** `tests/unit/templates/test_catalogue.py` (`len(templates) == 23`), `test_api.py`
  (`len(ids) == 23`), `test_loader.py` (`len(first) == 23`), `test_cli.py` (`count(" ok ") == 23`, twice); spec
  §15.1 A3/R29, README, `docs/MM3_ARCHITECTURE.md`, `template-format.md` §10, `docs/user-guide/README.md`,
  `CHANGELOG.md`, the plan's MVP definition of done ("23 templates"), `prompts/MM3_phase-16-release.md`.
  `grep -rn "23" --include=*.md --include=*.py` finds the rest.
- **Map-reduce:** long inputs go through `templates/mapreduce.py` (R6, ADR-0016); `params.detail: high` asks the map
  step for richer points (R29). An AI conversation is text-dense: Nick's 35-minute example is about 33 KB (roughly
  8-9 k tokens), and the assistant's turns carry most of the specifics.
- **Speakers in imported conversations** (by plan; confirm in 15k's log): the user is a named person (e.g. "Nick"),
  the assistant is "Grok", "ChatGPT", "Claude" or "AI". The transcript may have no times (`timed: false`).
- **Nick's example (private), what it shows** (structure only; read the file itself for content): a feasibility
  conversation that moves from an idea, through the assistant's critique and alternatives (existing products compared,
  build vs adopt), to the user's stated constraints (platform, budget, preference for supported products, a stated
  quality bar, an excluded option), a chosen approach and concrete steps (install method, an automated update with
  signature checking, a separate paid service, settings to enable, a verification test). The assistant states many
  **specific facts** (prices, package and version details, counts, survey figures, legal claims) that a plan must mark
  as unverified. The user asks many side questions that are not part of the plan, and several of the user's turns are
  questions the assistant answered, not decisions.
- **Eval:** `tests/eval/run_eval.py`, `checker.py` (`expected.sections`, `expected.forbidden`, `expected.numbered`,
  `expected.limits`), `baseline.json`, synthetic meetings in `tests/eval/meetings/*.yaml` (`templates: [id]`).

## Tasks
1. **Study the target.** Read the phased-project skill's workflow and the playbook, and list what a good source
   document gives it (the problem and goal, constraints and environment facts, decisions with reasons, open owner
   questions, risky assumptions, facts to verify). Read Nick's example privately and note what a plan of it should
   contain and leave out. Write a short **anonymised** summary of these findings for the ADR (no personal details).
2. **Write `starter_templates/create-project-plan.md`.** Default sections (adjust with evidence and justify; keep the
   count manageable for an 8 GB local model):
   - `summary` **Summary Succinct** (1-2 sentences: what is being built and the chosen approach) and
     `summary-detailed` **Summary Detailed** (R25(c));
   - `project-goal` **Goal and Success Criteria**: the problem, the desired outcome, the user's stated quality bar
     ("north star"), how success will be judged;
   - `context-constraints` **Context and Constraints**: environment, platform, existing resources, budget, skills,
     preferences and exclusions **as the user stated them**;
   - `requirements` **Requirements**: must / should / won't, each traceable to the conversation;
   - `decisions` **Decisions Made**: only what the user decided or clearly agreed to, each with its reason; the AI's
     proposals that the user did not accept go elsewhere (reuse the common `decisions` id);
   - `options-considered` **Options Considered**: the alternatives discussed, with pros, cons and why each was
     chosen or rejected (a table is fine);
   - `solution-outline` **Proposed Solution**: architecture or stack, components and how they fit, as discussed;
   - `milestones` **Rough Phases**: an ordered list of 3-8 milestones with their outcome, derived from the steps
     discussed; no invented work;
   - `risks` **Risks and Mitigations** (reuse the common id);
   - `facts-to-verify` **Facts to Verify**: every specific external claim the plan relies on (prices, versions,
     package names, limits, legal or statistical claims), saying who stated it (usually the AI) and that it is
     unverified;
   - `open-questions` **Open Questions for the Owner**: decisions still open, phrased as questions with the options
     discussed;
   - `acceptance` **Definition of Done**: how the user will check the result works (tests or checks mentioned);
   - `action-items` **Next Steps** (`format: tasks`, owner rule; the user's own immediate steps, AI suggestions
     marked as such);
   - `ai-recommendations` last (standard): here, gaps in the plan the phased-project review should look at.
   `_system`: a senior technical project planner turning a working conversation into a pre-plan for an engineering
   agent. Rules: the **user's** decisions and constraints carry authority, the assistant's statements are proposals
   and claims; never present an assistant suggestion as decided unless the user agreed; keep specifics (names,
   versions, figures, commands) but route external facts to *Facts to Verify*; leave out side questions that do not
   change the plan; never invent requirements, phases or numbers; write for a reader who has not seen the
   conversation. Make the wording work for recorded meetings too ("the participants" when there is no assistant).
   Use `params.detail: high` if the map step needs it (measure).
3. **Hand-off.** The note must be directly usable as `/phased-project`'s source document. Check that the MM3 section
   markers, frontmatter and header lines do not confuse it (run the skill's review step by hand on the generated
   note, read-only, in a scratch directory; do not bootstrap a project). If Nick agrees, add one line to the skill's
   description of sources and to the playbook ("an MM3 Create Project Plan note is a good source") and keep the two
   in sync (Nick's global rule); otherwise record it as a follow-up.
4. **Generator support, only if needed.** If a convention check (two summaries, task owner rule, timestamps) does not
   fit a conversation with an AI, prefer prompt work; any schema or generator change needs `template-format.md`,
   validation tests and an ADR note.
5. **Tests and fixtures.** Golden prompt snapshot (`MM3_UPDATE_GOLDEN=1`), schema validity, the count updates (23 →
   24 everywhere), catalogue regenerated, and a guardrail test in the style of
   `test_sensitive_templates_keep_their_guardrails` that the `_system` keeps the "assistant suggestions are not
   decisions" and "facts to verify" rules.
6. **Eval.** Add two or three **synthetic** conversations to `tests/eval/meetings/` with `templates:
   [create-project-plan]`: an untimed user/assistant chat in the shape of Nick's example (an idea, critique,
   alternatives, constraints, a chosen approach, steps, assistant-stated figures) and one recorded-meeting-style
   planning discussion. Expected: key decisions in `decisions`, a rejected option in `options-considered` and **not** in
   `decisions`, the assistant's figures in `facts-to-verify`, 3-8 milestones, no side-question topic in the plan
   (`expected.forbidden`). Run with local `qwen3:8b`; if Nick's keys are configured, also one cloud model (keep cost
   under about USD 1 and say what it was). Add the results to `baseline.json`.
7. **Private check.** Import Nick's example through the 15k flow (or his share link, if 15l is done), generate with
   `qwen3:8b` and, if keyed, one cloud model; show Nick both notes and ask whether the plan is good enough to hand to
   Claude Code. Iterate on the prompts with his feedback. Also try the template on one real recorded planning meeting
   if Nick names one.

## Out of scope
- Bootstrapping a project from the note (creating repos or running `/phased-project` for real), writing ADRs or
  phase prompts inside MM3, a "send to Claude Code" button, new export formats.
- Changing other templates or the default template.

## Tests
- `uv run pytest` (schema, golden prompt, counts, catalogue, guardrails), `ruff check`, `ruff format --check`,
  `mypy src`; the eval (Task 6) marked `models`/`network` as usual.

## Acceptance criteria
- In the real app, Nick's example conversation imported and run through **Create Project Plan** with local `qwen3:8b`
  produces a note whose Decisions list only what he decided, whose Options Considered show the rejected approaches
  with reasons, whose Facts to Verify list the assistant's prices, figures and package claims, and whose Rough Phases
  match the steps discussed; Nick judges it good enough to hand to Claude Code.
- The phased-project review step reads the note without confusion from MM3's markers or header.
- The template appears in the picker and the library with its description, and works on a recorded meeting too.
- All template-count references say 24.

## Phase-specific docs
- ADR-0052: append "Phase 15m implementation" (anonymised findings, section choices, eval results). Spec §15: add
  **R33** (the 24th built-in) and amend A3's count.
- `docs/user-guide/template-catalogue.md` (generated), a short "From an AI conversation to a Claude Code project"
  section in `docs/user-guide/importing.md` (import, pick the template, then `/phased-project "<note>" <repo dir>`),
  `template-format.md` §10, README feature list, `CHANGELOG.md`.
- `prompts/MM3_phase-16-release.md`: the template count (24) and the MVP definition of done line.

Then the standard close-out checklist.
