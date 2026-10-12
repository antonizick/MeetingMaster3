# Shared Instructions for Every Phase

Read this file in full before starting any phase. Each phase prompt assumes it.

**Phase IDs.** `NN` in this file is the phase ID: two digits, optionally with a lower-case letter suffix for an interim tuning round between hardening and release (`15a`, `15b`…; ADR-0030). A round is a normal phase: it is claimed, gets its own branch `phase-15a-<slug>` and worktree `../MeetingMaster3-phase-15a`, and closes out with the full checklist. `15a` sorts after `15` and before `16`.

## 1. Orientation and claim (every phase, before writing code)
1. Read `CLAUDE.md`, `IMPLEMENTATION_PLAN.md` (including the Phase Log) and the sections of `docs/SPECIFICATION.md` named in your phase prompt. Always read §15.
2. Confirm that every phase listed under "Depends on" is `✅ Complete`. If one is not, stop and tell Nick.
3. Read the Phase Log entries of the dependency phases. They may record deviations that change what you build.
4. **Claim the phase on `main`** by following §1a. This is the first file change of every phase session. Do not start the Tasks until the claim is verified.
5. If anything in the prompt is ambiguous or contradicts the spec, prefer the spec's §15. If it is still unclear, ask Nick before guessing on anything user-visible or hard to reverse.

## 1a. Claiming a phase (mandatory; other agents may be running in parallel)
Nick and other agents read the Status column from `main`. A status change made only on a phase branch, or left uncommitted in a worktree, is invisible to them. So every phase is claimed with a commit on `main` **before** any other work.
1. In the main checkout (`/home/nick/Work/MeetingMaster3`), check that `git branch --show-current` prints `main` and that `git status --short IMPLEMENTATION_PLAN.md` prints nothing. If either check fails, stop and tell Nick. Never commit another agent's uncommitted changes.
2. Look for an existing claim: the phase's row on `main`, `git branch --list 'phase-NN-*'` and `git worktree list`. If the row is already `🔄 In progress`, or a branch or worktree exists, do not claim again; follow the resume rules in `/phase`.
3. Set the phase's Status cell to `🔄 In progress`, then commit **only that file** to `main`: `git commit -m "chore(plan): start phase NN" -- IMPLEMENTATION_PLAN.md`.
4. In the Obsidian note `02 Projects/Meeting Master 3 Implementation Plan.md`, set the phase's row to `🔄 In progress` and add a dated log line: "Phase NN started (branch `phase-NN-<slug>`, worktree `../MeetingMaster3-phase-NN`)".
5. Create the worktree and branch from that commit: `git worktree add ../MeetingMaster3-phase-NN -b phase-NN-<slug> main`, then run `uv sync` inside it. Do all of the phase's work in the worktree, using absolute paths or `cd /home/nick/Work/MeetingMaster3-phase-NN && …` in every command, because the shell may reset to the main checkout between commands. Never switch the main checkout off `main`: other agents commit their claims there.
6. Verify: `git show main:IMPLEMENTATION_PLAN.md | grep '^| NN '` must show `🔄 In progress`.

If the phase ends `⛔ Blocked`, commit that status to `main` the same way (`chore(plan): phase NN blocked`) so that `main` doesn't show a stale `🔄`. A `✅ Complete` status reaches `main` through the merge.

## 2. Target repository layout (evolves; keep `docs/ARCHITECTURE.md` in sync)
```
MeetingMaster3/
├── CLAUDE.md  IMPLEMENTATION_PLAN.md  README.md  LICENSE  NOTICE  THIRD_PARTY_NOTICES.md
├── SECURITY.md  CONTRIBUTING.md  CODE_OF_CONDUCT.md  CHANGELOG.md
├── pyproject.toml  uv.lock  .python-version  .pre-commit-config.yaml
├── .gitignore  .dockerignore  .editorconfig  .env.example
├── .github/ (workflows/, ISSUE_TEMPLATE/, PULL_REQUEST_TEMPLATE.md, dependabot.yml)
├── docker/ (Dockerfile, compose.yaml, compose.cpu.yaml)
├── docs/ (SPECIFICATION.md, DECISIONS.md, ARCHITECTURE.md, user-guide/, dev-guide/)
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
- [ ] `IMPLEMENTATION_PLAN.md`: Status set (`✅ Complete` or `⛔ Blocked`, icon plus word; a `⛔ Blocked` status is also committed to `main` per §1a), Phase Log entry added (date, summary, deviations, follow-ups, test counts).
- [ ] `CHANGELOG.md` `[Unreleased]` updated.
- [ ] README, SECURITY, ARCHITECTURE, user and dev guides, THIRD_PARTY_NOTICES, .gitignore and .dockerignore updated where affected.
- [ ] ADR added to `docs/DECISIONS.md` for any notable choice; spec amendment added if the spec changed.
- [ ] Later phase prompts corrected if your work changed their assumptions.
- [ ] Obsidian note `02 Projects/Meeting Master 3 Implementation Plan.md` updated.
- [ ] OSMods documentation updated if the host system was modified.
- [ ] Work committed on the phase branch. Standing instruction from Nick (2026-10-11): once the phase is `✅ Complete` and every check passes, merge it into `main` locally without asking (fast-forward where possible), then remove the worktree (`git worktree remove ../MeetingMaster3-phase-NN`), delete the merged phase branch (`git branch -d`) and remove any temporary files or processes you created. Merge from the main checkout. Conflicts in `IMPLEMENTATION_PLAN.md` and `CHANGELOG.md` are expected when phases ran in parallel: keep every row and entry from both sides, and use the branch's final status for this phase's row. Do not merge a `⛔ Blocked` phase or one with failing checks. Never push, create a GitHub repo or open a PR without his explicit confirmation.
- [ ] Final message to Nick: what was built, how to try it, what's next, and any open questions.
