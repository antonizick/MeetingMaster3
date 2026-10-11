# MeetingMaster3: Agent Instructions

These rules apply to every AI agent working in this repository. They are **mandatory**.

## What this project is
A free, open-source (Apache-2.0), self-hostable, local-first meeting intelligence app. It turns meeting audio into speaker-attributed transcripts and secretary-grade, Obsidian-native Markdown notes. Python 3.12 / FastAPI / WhisperX / HTMX + Alpine. Single user, runs on localhost.

## Source-of-truth documents (read before working)
| File | Purpose |
|---|---|
| `docs/SPECIFICATION.md` | Canonical product spec. **§15 Amendments override §1–14.** |
| `IMPLEMENTATION_PLAN.md` | Phase table, status, phase log. **Keep it accurate.** |
| `prompts/_shared-instructions.md` | Conventions and close-out checklist for every phase |
| `prompts/phase-NN-*.md` | The prompt for the phase you are executing |
| `docs/DECISIONS.md` | ADR log; append, never rewrite |

## Mandatory documentation upkeep
Documentation is part of the deliverable. A phase is **not complete** until all of the following are done:
1. `IMPLEMENTATION_PLAN.md`: set the phase's status, written as icon plus word (`⬜ Not started` before; `🔄 In progress` when you start; `✅ Complete` or `⛔ Blocked` at the end) and add a dated entry to the Phase Log (what was built, deviations, follow-ups). **`🔄 In progress` must be committed to `main` before any other work** (the claim protocol in `prompts/_shared-instructions.md` §1a), because parallel agents read the status from `main`. A status that exists only on a phase branch or in a worktree does not count.
2. `CHANGELOG.md`: add entries under `[Unreleased]`.
3. Update every affected document: `README.md`, `SECURITY.md`, `docs/ARCHITECTURE.md`, user and developer guides, `THIRD_PARTY_NOTICES.md` (any new dependency or vendored asset), `.gitignore` / `.dockerignore`.
4. `docs/DECISIONS.md`: add an ADR for any non-trivial technical choice or deviation from the spec. If the spec itself changes, add an amendment to SPECIFICATION §15.
5. **Later phase prompts:** if your work changes an assumption a later prompt relies on (paths, names, interfaces), edit that prompt file so it stays correct.
6. The Obsidian project note `/home/nick/Documents/02 Projects/Meeting Master 3 Implementation Plan.md`: update the status and add a short dated log line.
7. Any change to the host OS (installing packages or services, NVIDIA Container Toolkit, Docker config, systemd units) must also be documented in `/home/nick/Documents/04 Resources/OSMods/` per Nick's global instructions. Read that folder's README first.

## Engineering rules
- Work only within the phase's scope. Record out-of-scope findings in the Phase Log as follow-ups.
- Tests are required: `uv run pytest` must pass, and `uv run ruff check` and `uv run mypy` must be clean, before a phase closes. Tests that need a GPU or models carry the markers `@pytest.mark.gpu` / `@pytest.mark.models` and are skipped in CI.
- Never commit secrets, audio, vault contents, `.env`, model weights or personal data. Test fixtures must be synthetic or CC-licensed, with attribution in `tests/fixtures/README.md`.
- Follow the security baseline in SPECIFICATION §15.3 (localhost bind, Host/Origin/CSRF checks, sanitised rendering, vault path confinement, atomic writes, masked secrets, cloud egress consent, voiceprint privacy).
- Pin and lock dependencies (`uv add`, which updates `uv.lock`). Check licences before adding a dependency.
- Git: work on branch `phase-NN-<slug>` in its own worktree `../MeetingMaster3-phase-NN`; the main checkout stays on `main`. Use Conventional Commits, and commit at logical checkpoints. **Never push, create a GitHub repo, or open a PR without Nick's explicit confirmation in the session.**
- The reference dev machine has an RTX 2070 Max-Q (8 GB VRAM), Arch-based Omarchy Linux, host Python 3.14 (use uv's 3.12), Docker and Ollama installed.
