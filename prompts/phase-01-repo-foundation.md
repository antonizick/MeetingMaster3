# Phase 01: Repository Foundation & Governance

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 00 · **Branch:** `phase-01-repo-foundation`

## Read first
`CLAUDE.md`, `prompts/_shared-instructions.md`, `IMPLEMENTATION_PLAN.md`, and `docs/SPECIFICATION.md` §1, §2, §11, §15 (especially §15.3 and §15.4).

## Goal
Make the repository ready to publish on GitHub from day one, with no application code yet. Every governance, licensing, security and contribution file exists, is accurate for the current state ("pre-alpha, under construction"), and is structured so that later phases only append to it.

## Tasks
1. **Licensing:** `LICENSE` (full Apache-2.0 text, copyright "2026 Nick Antoncic and MeetingMaster3 contributors"). `NOTICE` (project name, copyright, short attribution line). `THIRD_PARTY_NOTICES.md` with a table (Component | Version | License | Use | Redistributed? Y/N), pre-filled with the planned stack (FastAPI, WhisperX, faster-whisper, CTranslate2, pyannote.audio, PyTorch, HTMX, Alpine.js) marked "planned". Add a section on **model weights**: Whisper (MIT), pyannote gated models (users accept the terms on Hugging Face themselves) and LLMs (user-chosen). Weights are never bundled.
2. **README.md:** name and one-line pitch; status badge placeholders (CI, license); "⚠️ Pre-alpha" notice; features (planned MVP); privacy stance; architecture at a glance (short ASCII diagram); roadmap pointer; links to the spec, plan, CONTRIBUTING and SECURITY; license. Add empty headings for Quickstart, Installation, Configuration, Hardware guidance and FAQ (marked "coming in Phase NN") so later phases fill them in.
3. **SECURITY.md:** supported versions (none released yet); how to report a vulnerability privately (GitHub private vulnerability reporting, with an email fallback placeholder for Nick to confirm; **do not invent an email address**); scope; the security model summary from spec §15.3 (localhost-only default, no auth in MVP, cloud egress consent, voiceprints as biometric data, secrets handling); a "Data the app stores and where" table (to be completed in later phases).
4. **CONTRIBUTING.md:** dev setup (uv, Python 3.12, pre-commit; marked as arriving in Phase 02), branch and commit conventions (Conventional Commits), testing markers, how to add a template or backend (stub sections), DCO sign-off (`git commit -s`) recommended, and the "docs are part of done" rule.
5. **CODE_OF_CONDUCT.md:** Contributor Covenant v2.1, with contact method "see SECURITY.md / maintainer"; no invented emails.
6. **CHANGELOG.md:** Keep a Changelog 1.1.0 format, SemVer, `[Unreleased]` with "Added: project governance files".
7. **`.gitignore`:** Python, uv/venv, caches, IDE files, OS files, `.env*` (but not `.env.example`), **audio files** (`*.wav *.mp3 *.m4a *.flac *.ogg *.opus *.webm *.mp4 *.aac`, with an exception for `tests/fixtures/audio/*.fixture.*` files), model caches (`models/`, `.cache/huggingface`), local app data (`data/`, `*.db`, `*.sqlite*`), `jobs/`, test vault output (`tests/**/_vault_out/`), coverage, `dist/`, `build/`.
8. `.editorconfig` (UTF-8, LF, 4-space Python, 2-space YAML/JSON/HTML/JS/CSS, final newline). `.gitattributes` (`* text=auto eol=lf`, plus binary audio).
9. **`.github/`:** `ISSUE_TEMPLATE/bug_report.yml` (with fields for hardware profile, backend, OS and Docker vs native, and a reminder not to attach private audio), `feature_request.yml`, `config.yml` (security reports point to SECURITY.md); `PULL_REQUEST_TEMPLATE.md` (checklist: tests, docs updated, CHANGELOG, no secrets or audio); `dependabot.yml` (pip/uv, github-actions, docker; weekly); `workflows/docs-check.yml`, a placeholder that runs a Markdown link check (lychee, offline mode) on push and PR. The Python CI arrives in Phase 02. Pin actions by commit SHA where practical.
10. **docs skeleton:** `docs/ARCHITECTURE.md` (component list from spec §4 + the §15 refinements; target layout from shared instructions §2; "to be expanded"), `docs/user-guide/README.md`, `docs/dev-guide/README.md` (index pages listing future pages with their owning phase), `docs/PRIVACY.md` (what data exists, where it lives, what can leave the machine and when).
11. `.env.example` with commented placeholders: `MM3_CONFIG_DIR`, `MM3_DATA_DIR`, `MM3_MODELS_DIR`, `MM3_VAULT_PATH`, `HF_TOKEN`, `OPENROUTER_API_KEY`, `AWS_PROFILE`/`AWS_REGION`, `MM3_HOST`, `MM3_PORT`.
12. Add a secret-scanning plan: document in CONTRIBUTING that Phase 02 adds a `gitleaks` pre-commit hook.

## Out of scope
Any Python code, pyproject or Docker files.

## Acceptance criteria
- Every file listed in spec §15.4 that can exist without code exists, is non-trivial and is internally consistent: no "TODO" left without a phase owner, and no invented contact details.
- `git status` shows no ignored-file leakage. Check with `git check-ignore -v` on samples: `x.wav` is ignored, `tests/fixtures/audio/sample.fixture.opus` is not, `.env` is ignored, `.env.example` is not.
- The README renders cleanly and all relative links resolve.
- First commit(s) on the phase branch: `chore: initial repository governance`.

## Phase-specific docs
Everything above is the deliverable. Then apply the standard close-out checklist in `_shared-instructions.md`.
