# Shared Instructions for Every Phase

Read this file in full before starting any phase. Each phase prompt assumes it.

**Phase IDs.** `NN` in this file is the phase ID: two digits, optionally with a lower-case letter suffix for a phase inserted after another one with `/phase-add` (`09a`, `15a`, `15b`…; ADR-0030, ADR-0034). An inserted phase is a normal phase: it is claimed, gets its own branch `phase-15a-<slug>` and worktree `../MeetingMaster3-phase-15a`, and closes out with the full checklist. `15a` sorts after `15` and before `16`.

## 1. Orientation and claim (every phase, before writing code)
1. Read `CLAUDE.md`, `MM3_IMPLEMENTATION_PLAN.md` (including the Phase Log) and the sections of `docs/MM3_SPECIFICATION.md` named in your phase prompt. Always read §15.
2. Confirm that every phase listed under "Depends on" is `✅ Complete`. If one is not, stop and tell Nick.
3. Read the Phase Log entries of the dependency phases. They may record deviations that change what you build.
4. **Claim the phase on `main`** by following §1a. This is the first file change of every phase session. Do not start the Tasks until the claim is verified.
5. If anything in the prompt is ambiguous or contradicts the spec, prefer the spec's §15. If it is still unclear, ask Nick before guessing on anything user-visible or hard to reverse. (Hands-off mode: block-with-question, §1b.)

## 1a. Claiming a phase (mandatory; other agents may be running in parallel)
Nick and other agents read the Status column from `main`. A status change made only on a phase branch, or left uncommitted in a worktree, is invisible to them. So every phase is claimed with a commit on `main` **before** any other work.
1. In the main checkout (`/home/nick/Work/MeetingMaster3`), check that `git branch --show-current` prints `main` and that `git status --short MM3_IMPLEMENTATION_PLAN.md` prints nothing. If either check fails, stop and tell Nick. Never commit another agent's uncommitted changes.
2. Look for an existing claim: the phase's row on `main`, `git branch --list 'phase-NN-*'` and `git worktree list`. If the row is already `🔄 In progress`, or a branch or worktree exists, do not claim again; follow the resume rules in `/phase`.
3. Set the phase's Status cell to `🔄 In progress`, then commit **only that file** to `main`: `git commit -m "chore(plan): start phase NN" -- MM3_IMPLEMENTATION_PLAN.md`.
4. In the Obsidian note `02 Projects/MM3 Implementation Plan.md`, set the phase's row to `🔄 In progress` and add a timestamped log line: "Phase NN started (claim commit `<hash>`, branch `phase-NN-<slug>`, worktree `../MeetingMaster3-phase-NN`)".
5. Create the worktree and branch from that commit: `git worktree add ../MeetingMaster3-phase-NN -b phase-NN-<slug> main`, then run `uv sync` inside it. Do all of the phase's work in the worktree, using absolute paths or `cd /home/nick/Work/MeetingMaster3-phase-NN && …` in every command, because the shell may reset to the main checkout between commands. Never switch the main checkout off `main`: other agents commit their claims there.
6. Verify: `git show main:MM3_IMPLEMENTATION_PLAN.md | grep '^| NN '` must show `🔄 In progress`.

If the phase ends `⛔ Blocked`, commit that status to `main` the same way (`chore(plan): phase NN blocked`) so that `main` doesn't show a stale `🔄`. A `✅ Complete` status reaches `main` through the merge.

## 1b. Hands-off mode: block-with-question (PhaseHypervisor contract 1)
Applies only in hands-off mode (`/phase NN --auto` or `PHX_AUTO=1`, set only by PhaseHypervisor); manual sessions ignore this section. Wherever a manual session would ask Nick (an open owner question this phase needs, an ambiguity you must not guess, the risk rule in `CLAUDE.md`, or a failure you cannot fix within scope), do this instead, then end the session:
1. In the worktree, commit all work on the phase branch: `wip(phase-NN): blocked, <short reason>`. Do not merge; keep the branch and worktree.
2. In the main checkout, in `MM3_IMPLEMENTATION_PLAN.md`:
   - add an Open questions row `| <next #> | <question> | Open (asked <TS>, Phase NN, auto mode). Proposed default: <default> | Phase NN |` (or, for an existing open question, name this phase in its Status cell and keep it `Open`);
   - set the phase's Status to `⛔ Blocked`;
   - add a Phase Log entry `### <TS>: Phase NN: <title> (⛔ Blocked)` with bullets: `- **Timeline:** started <claim TS> (claim commit <hash>) · blocked <TS> to (open)`, then `- **Model:** …`, then `- **Question:** #<id>: <question>`, then what is done, what remains and where to resume.
3. Commit only that file to `main`: `git commit -m "chore(plan): phase NN blocked" -- MM3_IMPLEMENTATION_PLAN.md`, and push `main` if a remote exists.
4. In the Obsidian note: row `⛔ Blocked`, `updated:` field, and a timestamped log line naming the question.
5. Final message: what was done, the question and its proposed default, then the `PHX-RESULT` line with `"status":"blocked"` and the question IDs (see `/phase`).

A question is **open** while its Status cell starts with `Open`; `Answered …`, `Decided …` and `Deferred …` are not open.

**Resuming** a `⛔ Blocked` phase in hands-off mode: if a question needed by it is still open, refuse without changing anything. Otherwise set the row to `🔄 In progress`, change `blocked <TS> to (open)` to `blocked <TS> to <TS now>` in its Timeline, commit only the plan file to `main` (`chore(plan): resume phase NN`), update the Obsidian note, then run `git merge main` in the worktree, read the answer and continue as a normal resume.

## 2. Target repository layout (evolves; keep `docs/MM3_ARCHITECTURE.md` in sync)
```
MeetingMaster3/
├── CLAUDE.md  MM3_IMPLEMENTATION_PLAN.md  README.md  LICENSE  NOTICE  THIRD_PARTY_NOTICES.md
├── SECURITY.md  CONTRIBUTING.md  CODE_OF_CONDUCT.md  CHANGELOG.md
├── pyproject.toml  uv.lock  .python-version  .pre-commit-config.yaml
├── .gitignore  .dockerignore  .editorconfig  .env.example
├── .github/ (workflows/, ISSUE_TEMPLATE/, PULL_REQUEST_TEMPLATE.md, dependabot.yml)
├── docker/ (Dockerfile, compose.yaml, compose.cpu.yaml)
├── docs/ (MM3_SPECIFICATION.md, MM3_DECISIONS.md, MM3_ARCHITECTURE.md, user-guide/, dev-guide/)
├── prompts/ (phase prompts)
├── src/meetingmaster3/
│   ├── __init__.py  __main__.py  cli.py  app.py          # app factory, `mm3` CLI
│   ├── config/        # pydantic settings, YAML load/save, paths
│   ├── domain/        # pure dataclasses / pydantic models (Meeting, Transcript, Segment, SpeakerMap, Section…)
│   ├── markdown/      # note + transcript writer/parser, section markers, frontmatter, archive, diff
│   ├── vault/         # vault path safety, atomic writes, naming, re-open, recents
│   ├── storage/       # SQLite (schema, migrations, repositories)
│   ├── jobs/          # job model, queue, stages, progress bus, checkpoints
│   ├── audio/         # ffprobe/ffmpeg ingest + normalisation
│   ├── hardware/      # GPU/VRAM detection, profiles, recommender
│   ├── transcription/ # WhisperX wrapper, alignment, diarization, OOM handling
│   ├── speakers/      # embeddings, voiceprint store, matching, mapping cascade
│   ├── llm/           # backend interface, ollama.py, bedrock.py, openai_compat.py, registry, chunking
│   ├── templates/     # template schema, loader, prompt assembler, generator
│   ├── feedback/      # ratings
│   ├── web/           # routers, jinja templates, static/ (app.css, app.js, vendor/), security middleware
│   └── starter_templates/*.md
└── tests/ (unit/, integration/, e2e/, fixtures/)
```

## 3. Conventions
- **Prefix.** Project documents carry the project prefix `MM3_` (see `CLAUDE.md`). New project-specific documents follow the same rule; convention-bound files (`README.md`, `LICENSE`, `CHANGELOG.md`, `CLAUDE.md`…) keep their names.
- **Timestamps, not dates.** Every place that records when (Phase Log, ADRs, amendments, owner questions, vault log, "Last updated", changelog release headings) uses `YYYY-MM-DD HH:MM TZ` (from `date '+%Y-%m-%d %H:%M %Z'`, never a bare or guessed date). Run `date` when you write each one. Entries that predate 2026-10-20 keep their bare dates.
- **Python:** 3.12, type hints everywhere, `mypy --strict` on `src/` (relax per module only with a comment), ruff for lint and format, line length 100.
- **Layering:** `domain` and `markdown` do no I/O except where explicitly designed. ML imports (`whisperx`, `torch`, `pyannote`) happen **lazily inside** `transcription/` and `speakers/`, so the app starts and unit tests run without them.
- **Errors:** user-facing errors have a code, a message and a remediation hint (`MM3Error(code, message, hint)`).
- **Logging:** stdlib logging, structured fields, secrets redacted by a filter. Transcript content is not logged at INFO.
- **Config:** every new setting is added to the pydantic model with a default and documented in `docs/user-guide/configuration.md`.
- **Tests:** pytest. Markers: `gpu`, `models`, `network`, `slow`, `e2e`; CI runs only unmarked tests. Use fakes (FakeTranscriber, FakeLLMBackend) so the full pipeline runs in CI.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`).

## 4. Phase close-out checklist (all items required)
- [ ] All acceptance criteria in the phase prompt are met, with a short verification note for each.
- [ ] `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy src` all pass (from Phase 02 onward).
- [ ] `MM3_IMPLEMENTATION_PLAN.md`: Status set (`✅ Complete` or `⛔ Blocked`, icon plus word; a `⛔ Blocked` status is also committed to `main` per §1a), Phase Log entry added (timestamp, summary, deviations, follow-ups, test counts).
- [ ] **Timeline bullet written** as the first bullet of the Phase Log entry: *started* = the claim commit's time (`git log -1 --format=%cd --date=format-local:'%Y-%m-%d %H:%M %Z' <claim hash>`), *finished* = `date '+%Y-%m-%d %H:%M %Z'` taken as the last step before the final commit, *merged* = the merge time or `not merged yet`, plus `blocked <TS> to <TS>` for any `⛔` interval. Never reuse an earlier timestamp.
- [ ] `CHANGELOG.md` `[Unreleased]` updated.
- [ ] README, SECURITY, ARCHITECTURE, user and dev guides, THIRD_PARTY_NOTICES, .gitignore and .dockerignore updated where affected.
- [ ] ADR added to `docs/MM3_DECISIONS.md` for any notable choice, **with its row in the index table at the top**; spec amendment added if the spec changed.
- [ ] Later phase prompts corrected if your work changed their assumptions.
- [ ] Obsidian note `02 Projects/MM3 Implementation Plan.md` updated.
- [ ] OSMods documentation updated if the host system was modified.
- [ ] Work committed on the phase branch. Once the phase is `✅ Complete` and every check passes, merge it into `main` without asking (fast-forward where possible), from the main checkout. Conflicts in `MM3_IMPLEMENTATION_PLAN.md` and the changelog are expected when phases ran in parallel: keep every row and entry from both sides, and use the branch's final status for this phase's row. Then push `main` if a remote exists (create a **private** GitHub repo if the plan calls for one; ADR-0004), `git worktree remove ../MeetingMaster3-phase-NN` and `git branch -d phase-NN-<slug>`. Do not merge a `⛔ Blocked` phase or one with failing checks. Making a repo public or publishing a release needs Nick's explicit confirmation (hands-off mode: block-with-question, §1b).
- [ ] Final message to Nick: what was built, how to try it, what's next, and any open questions. In hands-off mode, its last line is the `PHX-RESULT` line (see `/phase`).
