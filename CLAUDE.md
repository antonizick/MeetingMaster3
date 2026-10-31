# MeetingMaster3: Agent Instructions

These rules apply to every AI agent working in this repository. They are **mandatory**.

## What this project is
A free, open-source (Apache-2.0), self-hostable, local-first meeting intelligence app. It turns meeting audio into speaker-attributed transcripts and secretary-grade, Obsidian-native Markdown notes. Python 3.12 / FastAPI / WhisperX / HTMX + Alpine. Single user, runs on localhost.

## Naming and timestamps (mandatory, since 2026-10-20)
- **Project prefix: `MM3`.** Project documents are named `MM3_<NAME>` (`MM3_IMPLEMENTATION_PLAN.md`, `docs/MM3_DECISIONS.md`, `prompts/MM3_phase-NN-<slug>.md`…) so they can be told apart from other projects' documents without their path. Any new project-specific document gets the prefix. `CLAUDE.md`, `README.md`, `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, the `/phase` and `/phase-add` command files, and branch and worktree names keep their conventional names.
- **Timestamps everywhere a date is recorded** (Phase Log, ADRs, amendments, owner questions, vault log, "Last updated", changelog release headings): `YYYY-MM-DD HH:MM TZ` (from `date '+%Y-%m-%d %H:%M %Z'`, never a bare or guessed date). Entries that predate the rule keep their bare dates.

## Source-of-truth documents (read before working)
| File | Purpose |
|---|---|
| `docs/MM3_SPECIFICATION.md` | Canonical product spec. **§15 Amendments override §1–14.** |
| `MM3_IMPLEMENTATION_PLAN.md` | Phase table, status, phase log. **Keep it accurate.** |
| `prompts/MM3_shared-instructions.md` | Conventions and close-out checklist for every phase |
| `prompts/MM3_phase-NN-*.md` | The prompt for the phase you are executing |
| `docs/MM3_DECISIONS.md` | ADR log; append, never rewrite |

## Mandatory documentation upkeep
Documentation is part of the deliverable. A phase is **not complete** until all of the following are done:
1. `MM3_IMPLEMENTATION_PLAN.md`: set the phase's status, written as icon plus word (`⬜ Not started` before; `🔄 In progress` when you start; `✅ Complete` or `⛔ Blocked` at the end) and add a timestamped entry to the Phase Log whose **first bullet is the Timeline** (`started` = the claim commit's time, `finished` = `date` as your last step, `merged`, any `blocked` interval; format in the plan's Phase Log header), then what was built, deviations, follow-ups. **`🔄 In progress` must be committed to `main` before any other work** (the claim protocol in `prompts/MM3_shared-instructions.md` §1a), because parallel agents read the status from `main`. A status that exists only on a phase branch or in a worktree does not count.
2. `CHANGELOG.md`: add entries under `[Unreleased]`.
3. Update every affected document: `README.md`, `SECURITY.md`, `docs/MM3_ARCHITECTURE.md`, user and developer guides, `THIRD_PARTY_NOTICES.md` (any new dependency or vendored asset), `.gitignore` / `.dockerignore`.
4. `docs/MM3_DECISIONS.md`: add an ADR for any non-trivial technical choice or deviation from the spec. If the spec itself changes, add an amendment to MM3_SPECIFICATION §15.
5. **Later phase prompts:** if your work changes an assumption a later prompt relies on (paths, names, interfaces), edit that prompt file so it stays correct.
6. The owner's Obsidian project note `MM3 Implementation Plan.md` (its path is in `CLAUDE.local.md` or the owner's global instructions; skip this item if there is none): update the status and add a short timestamped log line (and update `updated:` in the note's frontmatter).
7. Any change to the host OS (installing packages or services, NVIDIA Container Toolkit, Docker config, systemd units) must also be documented in the owner's OS-modification log (path in `CLAUDE.local.md` or the owner's global instructions; skip this item if there is none). Read that folder's README first.

## Risk rule (mandatory)
Sessions may run with bypassed permissions. **If an action looks high-risk, irreversible or a bad idea, stop and ask Nick instead of doing it.** In an interactive session, ask. In a hands-off session (`/phase NN --auto` or `PHX_AUTO=1`, started by PhaseHypervisor), block the phase with the question recorded (block-with-question, `prompts/MM3_shared-instructions.md` §1b). Examples: deleting data you did not create, touching another project's files outside the scope your prompt names, changing system-wide config not covered by the prompt, spending money beyond a stated cap, making a repo public, publishing a release, force-pushing shared history.

## Engineering rules
- Work only within the phase's scope. Record out-of-scope findings in the Phase Log as follow-ups.
- Tests are required: `uv run pytest` must pass, and `uv run ruff check` and `uv run mypy` must be clean, before a phase closes. Tests that need a GPU or models carry the markers `@pytest.mark.gpu` / `@pytest.mark.models` and are skipped in CI.
- Never commit secrets, audio, vault contents, `.env`, model weights or personal data. Test fixtures must be synthetic or CC-licensed, with attribution in `tests/fixtures/README.md`.
- Follow the security baseline in MM3_SPECIFICATION §15.3 (localhost bind, Host/Origin/CSRF checks, sanitised rendering, vault path confinement, atomic writes, masked secrets, cloud egress consent, voiceprint privacy).
- Pin and lock dependencies (`uv add`, which updates `uv.lock`). Check licences before adding a dependency.
- Git: work on branch `phase-NN-<slug>` in its own worktree `../MeetingMaster3-phase-NN`; the main checkout stays on `main`. Use Conventional Commits, and commit at logical checkpoints. **Git authority (standing instruction from Nick, 2026-10-26 08:44 CDT; ADR-0004 in PhaseHypervisor):** commit, merge, push and create **private** GitHub repos without asking, at checkpoints and at close-out. Only making a repo **public**, publishing a GitHub **release**, or force-pushing shared history needs Nick's explicit confirmation (in hands-off mode: block-with-question). If an action looks high-risk or a bad idea, stop and ask anyway.
- The reference dev machine has an RTX 2070 Max-Q (8 GB VRAM), Arch-based Omarchy Linux, host Python 3.14 (use uv's 3.12), Docker and Ollama installed.
