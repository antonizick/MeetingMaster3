# Phase 16: Release v0.1.0 & GitHub Publication

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 15 · **Branch:** `phase-16-release`

## Read first
`CLAUDE.md`, `prompts/_shared-instructions.md`, `IMPLEMENTATION_PLAN.md` (the MVP definition of done and all Phase Log entries), and `docs/SPECIFICATION.md` §1, §12 and §15.4. Open question Q3 (GitHub owner, name and visibility).

**Phase 15 notes:** the "Deferred to the roadmap" bullets in the Phase 15 Phase Log entry are the input for
`docs/ROADMAP.md`. Before tagging, repeat the scans listed in `docs/dev-guide/setup.md` (gitleaks over the full
history, `scripts/pip_audit_ml.sh`, trivy on both images, `uv run --extra ml --extra bedrock python
scripts/gen_third_party.py --check`). **Publishing images (GHCR) carries GPL obligations** for the Debian packages in
them, ffmpeg included (THIRD_PARTY_NOTICES "Docker images"); decide with Nick how sources are offered. Items only
Nick can verify (MVP checklist): a live Bedrock and OpenRouter run with his keys, and a Firefox click-through (only
Chromium is automated). The quality baseline is `tests/eval/baseline.json` (`tests/eval/baseline.py` flags
regressions); measured numbers are in `docs/PERFORMANCE.md`; the README already has a "Known limitations" section.

## Goal
Ship MeetingMaster3 **v0.1.0**: documentation complete and accurate, the repository clean and GitHub-ready, a tagged release, and, **only with Nick's explicit confirmation**, the repository published to GitHub.

## Tasks
1. **Docs completeness audit:** walk through every file in spec §15.4 and every `docs/` page. Remove all "coming in Phase NN" placeholders, verify every command in README and the guides by running it, check that the screenshots are current (`docs/assets/`; the review workspace can be captured with `MM3_E2E_SCREENSHOTS=<dir>` when running `tests/e2e/test_review_flow.py`), and confirm that the configuration reference matches the `Settings` model exactly (generate it or diff it with a script). Write `docs/ROADMAP.md` from spec §12 plus the deferred follow-ups.
2. **README final:** a compelling intro, a screenshot or GIF of the workflow, features, privacy guarantees, the measured hardware table, Quickstart (Docker) in ≤ 5 commands, native install, configuration, templates, backends, FAQ/troubleshooting (HF token, OOM, Ollama connectivity, GPU in Docker), contributing, security, license, and acknowledgements (WhisperX, faster-whisper, pyannote, Obsidian; not affiliated).
3. **Versioning:** set the version to `0.1.0` in `pyproject.toml` (single source; the app reads `importlib.metadata`). Finalise `CHANGELOG.md`: move `[Unreleased]` to `[0.1.0] - <date>`, edited for readability. Draft the release notes in `docs/releases/v0.1.0.md`: highlights, requirements, known limitations, upgrade notes (none), and checksums or digests of the images if they are published.
4. **Repository hygiene:** `git log` and the tree contain no secrets (gitleaks over the full history), no audio except the `*.fixture.*` clips, no large files and no private paths; grep for `/home/nick` and personal info in committed files and replace them with generic examples (CLAUDE.md may keep the machine notes only if Nick agrees; ask him, and otherwise move them to an untracked `CLAUDE.local.md`). Check that `.gitignore` and `.dockerignore` are final, that the LICENSE, NOTICE and THIRD_PARTY_NOTICES are final, and that GitHub community files are present (the community profile checklist will be satisfied).
5. **Clean-clone verification:** clone the repo into a temporary directory and follow the README Quickstart verbatim (Docker) and the native install, and confirm both work with no undocumented step.
6. **MVP sign-off:** check every box in `IMPLEMENTATION_PLAN.md` → "MVP definition of done", with evidence (a link to the test, Phase Log entry or doc). Anything unmet goes to Nick with a recommendation: fix now, or document as a known limitation.
7. **Publication (requires confirmation):** present Nick with a summary: repo owner/name/visibility (Q3), description, topics (`obsidian`, `whisper`, `meeting-notes`, `transcription`, `local-first`, `self-hosted`, `ollama`, `diarization`), and what will be pushed. **Only after he explicitly confirms** in the session: `gh repo create`, push `main` and the tag `v0.1.0`, enable private vulnerability reporting, Dependabot alerts and branch protection on `main` (require CI), create the GitHub release from the release notes, and enable the GHCR image publish workflow (if Nick wants images published). Update the README badges and the URLs in `pyproject.toml`, SECURITY and CONTRIBUTING to the real repo URL. Also replace the `OWNER/REPO` placeholder in `.github/ISSUE_TEMPLATE/config.yml`, and confirm the private security contact route referenced from `SECURITY.md` and `CODE_OF_CONDUCT.md` (Phase 01 left it unset on purpose; no email was invented).
8. **Close the plan:** mark Phase 16 Complete, add a final Phase Log entry with the release summary, update the Obsidian project note (consider moving it to `05 Archive/` or keeping it in Projects for post-MVP work; ask Nick).

## Acceptance criteria
- A clean clone works from the README alone.
- The tag `v0.1.0` exists, and the CHANGELOG and release notes are finalised.
- If publication was confirmed: the GitHub repo is live with CI green, a release is published, and security features are enabled. If it was not confirmed: everything is ready, and the exact commands are written in the Phase Log.
- `IMPLEMENTATION_PLAN.md` accurately reflects the final state of every phase.

## Phase-specific docs
All of them (this phase audits everything). Then the standard close-out checklist.
