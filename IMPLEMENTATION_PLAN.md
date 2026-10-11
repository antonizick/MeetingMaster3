# MeetingMaster3: Implementation Plan

**Spec:** [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) (v1.1). **Decisions:** [`docs/DECISIONS.md`](docs/DECISIONS.md). **Agent rules:** [`CLAUDE.md`](CLAUDE.md). **Shared phase instructions:** [`prompts/_shared-instructions.md`](prompts/_shared-instructions.md)
**Last updated:** 2026-10-11 (Phase 05 complete)

> ⚠️ **Mandatory:** every agent that works on this project keeps this file accurate. **Before doing any other work, set your phase to `🔄 In progress` and commit that change to `main`** (claim protocol: `prompts/_shared-instructions.md` §1a). Other agents read this table from `main`. At the end, set it to `✅ Complete` or `⛔ Blocked` and add a Phase Log entry. See `CLAUDE.md`.

## How to run a phase
Open Claude Code in `/home/nick/Work/MeetingMaster3` and type one of:
- `/phase`: run the next eligible phase. It checks dependencies, tells you if you're on the wrong model, resumes an `In progress` phase, and asks about any open questions it needs.
- `/phase 03`: run a specific phase.
- `/phase status`: show progress and what's next, without doing any work.

The command lives in `.claude/commands/phase.md`. Under the hood it reads `CLAUDE.md`, this file and `prompts/_shared-instructions.md`, then executes `prompts/phase-NN-*.md`. You never need to paste a prompt. Review the agent's close-out summary. Completed phases are merged into `main` automatically (the phase branch is then deleted); nothing is pushed without your confirmation.

Phases run in order. Phases whose dependencies are all complete may run in parallel, for example 05 ∥ 08 and 12 ∥ 13. Each phase is claimed by a `chore(plan): start phase NN` commit on `main` and runs in its own worktree, `../MeetingMaster3-phase-NN`, so parallel sessions never share a checkout. `/phase status` flags any branch or worktree whose row is not `🔄 In progress`.

**Status values:** ⬜ Not started · 🔄 In progress · ⛔ Blocked · ✅ Complete. Always write the icon **and** the word, so the column is easy to scan and still searchable.

## Phases

| Phase | Phase Name | Phase Purpose | AI Model to Use | Depends on | Status | Prompt to Initiate This Phase |
|---|---|---|---|---|---|---|
| 00 | Planning & spec refinement | Review the PrePlan, resolve decisions, write the spec v1.1, this plan and the phase prompts | Opus 5.5 | none | ✅ Complete | n/a (this session) |
| 01 | Repository foundation & governance | Create a GitHub-ready repo: LICENSE, NOTICE, README, SECURITY, CONTRIBUTING, CoC, CHANGELOG, .gitignore, .github templates, docs skeleton | Sonnet 5.5 | 00 | ✅ Complete | [phase-01-repo-foundation.md](prompts/phase-01-repo-foundation.md) |
| 02 | Python scaffold, config & CI | uv/Python 3.12 project, FastAPI app factory, `mm3` CLI, pydantic+YAML config, XDG paths, security middleware, lint/type/test CI | Sonnet 5.5 | 01 | ✅ Complete | [phase-02-python-scaffold.md](prompts/phase-02-python-scaffold.md) |
| 03 | Data model & Markdown round-trip | Domain models, note and companion-transcript writer/parser, section markers, frontmatter, naming, archive, vault path safety, diffs | Opus 5.5 | 02 | 🔄 In progress | [phase-03-data-model-markdown.md](prompts/phase-03-data-model-markdown.md) |
| 04 | Job orchestration & audio ingest | SQLite storage, job queue (single GPU worker), stage pipeline, checkpoints and resume, cancel, SSE progress, upload and ffmpeg normalisation | Opus 5.5 | 03 | ⬜ Not started | [phase-04-jobs-orchestration.md](prompts/phase-04-jobs-orchestration.md) |
| 05 | Hardware detection & recommendations | GPU/VRAM detection, hardware profiles, transcription and LLM model recommender, `mm3 doctor` | Sonnet 5.5 | 02 | ✅ Complete | [phase-05-hardware-awareness.md](prompts/phase-05-hardware-awareness.md) |
| 06 | Transcription & diarization pipeline | WhisperX transcribe, align and diarize as job stages; HF token; OOM retry; language check; non-diarized fallback; VRAM release | Opus 5.5 | 04, 05 | ⬜ Not started | [phase-06-transcription-pipeline.md](prompts/phase-06-transcription-pipeline.md) |
| 07 | Speaker mapping & voiceprint store | Speaker embeddings, local voiceprint store, match suggestions, confirm/rename API, mapping cascade, privacy controls | Opus 5.5 | 06 | ⬜ Not started | [phase-07-speakers-voiceprints.md](prompts/phase-07-speakers-voiceprints.md) |
| 08 | LLM backend abstraction | Common backend interface; Ollama, Bedrock, OpenAI-compatible/OpenRouter; registry; connection tests; context budgeting; egress flag | Sonnet 5.5 | 02 | 🔄 In progress | [phase-08-llm-backends.md](prompts/phase-08-llm-backends.md) |
| 09 | Template engine & note generation | Template schema and loader, 5 starter templates, prompt assembler, map-reduce, section generation, end-to-end transcript → vault note | Opus 5.5 | 03, 07, 08 | ⬜ Not started | [phase-09-templates-generation.md](prompts/phase-09-templates-generation.md) |
| 10 | Web UI: core flow | HTMX/Alpine shell, vault setup, upload, hardware confirm, live job progress, Name Speakers screen, Write to Vault | Sonnet 5.5 | 09 | ⬜ Not started | [phase-10-web-ui-core.md](prompts/phase-10-web-ui-core.md) |
| 11 | Review workspace & regeneration | Side-by-side audio player and synced transcript with Markdown editor; per-section regeneration with diffs and archive; re-open existing notes | Opus 5.5 | 10 | ⬜ Not started | [phase-11-review-regeneration.md](prompts/phase-11-review-regeneration.md) |
| 12 | Settings, template library & feedback | Settings UI (backends, keys, HF token, hardware, vault, retention), config round-trip, template library management, ratings | Sonnet 5.5 | 10 | ⬜ Not started | [phase-12-settings-library-feedback.md](prompts/phase-12-settings-library-feedback.md) |
| 13 | Expanded template library | Author the remaining 17 templates (22 total), with validation and prompt-assembly golden tests | Sonnet 5.5 | 09 | ⬜ Not started | [phase-13-template-library.md](prompts/phase-13-template-library.md) |
| 14 | Docker & deployment | Multi-stage GPU and CPU images, compose with volumes and GPU reservation, host Ollama connectivity, non-root user, size budget, install docs | Sonnet 5.5 | 11, 12 | ⬜ Not started | [phase-14-docker-deployment.md](prompts/phase-14-docker-deployment.md) |
| 15 | Hardening, security review & QA | Threat model, security review and fixes, dependency and licence audit, E2E tests, measured performance on 8 GB, accessibility pass | Opus 5.5 | 13, 14 | ⬜ Not started | [phase-15-hardening-qa.md](prompts/phase-15-hardening-qa.md) |
| 16 | Release v0.1.0 & GitHub publication | Final docs, screenshots, CHANGELOG, version and tag, release notes, GitHub repo creation (with confirmation), MVP sign-off | Sonnet 5.5 | 15 | ⬜ Not started | [phase-16-release.md](prompts/phase-16-release.md) |

### Model rationale
- **Opus 5.5** (`/model claude-opus-5-5`) handles phases with subtle correctness or design risk: the round-trip parser, job state machine, ML pipeline and VRAM handling, voiceprint matching, prompt engineering, the interactive review workspace, and security review.
- **Sonnet 5.5** (`/model claude-sonnet-5-5`) handles well-trodden engineering with clear specs: scaffolding, adapters, CRUD UI, template authoring, Docker and docs. It's faster and cheaper, with ample capability for this work.

### Dependency graph
```
00 → 01 → 02 ─┬→ 03 → 04 ─┐
              ├→ 05 ───────┴→ 06 → 07 ─┐
              └→ 08 ───────────────────┴→ 09 ─┬→ 10 ─┬→ 11 ─┐
                                              │      └→ 12 ─┴→ 14 ─┐
                                              └→ 13 ────────────────┴→ 15 → 16
```

### MVP definition of done (checked in Phase 16)
- [ ] Upload audio → diarized transcript → named speakers → structured note written to the Obsidian vault, all on the 8 GB reference machine with Ollama, fully offline after model download.
- [ ] Side-by-side review, edit, per-section regeneration with diff and archive, and re-open of an existing note.
- [ ] 22 templates; library management; Bedrock and OpenRouter work with BYOK.
- [ ] Docker Compose deployment (GPU and CPU) documented and verified.
- [ ] Repo is GitHub-ready: README, LICENSE, NOTICE, THIRD_PARTY_NOTICES, SECURITY, CONTRIBUTING, CoC, CHANGELOG, .gitignore, .dockerignore, CI green.
- [ ] All docs in this table and the spec are accurate.

## Open questions (owner input needed; see SPECIFICATION §15.5)
| # | Question | Proposed default | Needed by |
|---|---|---|---|
| Q1 | Audio retention after writing to the vault | **Decided 2026-10-11:** keep as Opus for 90 days, then auto-delete; per-meeting pin; opt-in copy to vault (ADR-0006) | Phase 04 |
| Q2 | Companion transcript optional? | **Decided 2026-10-11:** always on by default; can be disabled with a warning | Phase 09 |
| Q3 | GitHub owner, repo name, visibility | **Deferred:** Nick provides these during Phase 16 | Phase 16 |
| Q4 | Test audio source | **Decided 2026-10-11:** a CC clip plus Nick's own shareable recordings. Short clips are committed as `*.fixture.*`; long ones stay out of git | Phase 06 |
| Q5 | Personal machine details in `CLAUDE.md` before publishing | **Deferred to Phase 16:** move them to an untracked `CLAUDE.local.md` | Phase 16 |

## Phase Log
Newest entries at the bottom. Format: `### YYYY-MM-DD: Phase NN: <title> (<status>)`, then bullets: built, deviations, follow-ups, tests.

### 2026-10-11: Phase 00: Planning & spec refinement (Complete)
- Reviewed `Meeting Master 3 PrePlan.md` and `Meeting Master 3 Design pre-notes.md`. Wrote `docs/SPECIFICATION.md` v1.1 (the original text reformatted, plus the §15 amendments and appendices).
- Owner decisions: Apache-2.0; HTMX + Alpine; 22 templates in two stages; Ollama, Bedrock and OpenAI-compatible backends. Recorded as ADR-0001…0004; ADR-0005 is proposed.
- Created `CLAUDE.md`, this plan, `prompts/_shared-instructions.md`, phase prompts 01–16 and the Obsidian project note.
- `git init` (branch `main`); nothing committed yet.
- Follow-up (same day): every owner question needed before Phase 16 is resolved. Q1 is audio retention: Opus for 90 days with pin (ADR-0006, spec R8). Added the `/phase` command and status icons. This project is the reference implementation of the `phased-project` skill (`~/.claude/skills/phased-project/`).

### 2026-10-11: Phase 01: Repository foundation & governance (Complete)
- Built on branch `phase-01-repo-foundation`: `LICENSE` (Apache-2.0), `NOTICE`, `THIRD_PARTY_NOTICES.md` (planned stack plus model-weights section), `README.md` (pre-alpha, placeholder sections with owning phases), `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `CHANGELOG.md`, `.gitignore`, `.editorconfig`, `.gitattributes`, `.env.example`, `.github/` (bug and feature issue forms, config, PR template, Dependabot, `docs-check.yml` with SHA-pinned actions), `docs/ARCHITECTURE.md`, `docs/PRIVACY.md`, user and developer guide indexes.
- Deviations: `main` had no commits, so the branch was created on the unborn `main` and its first commit holds the Phase 00 planning artifacts (`docs: add Phase 00 planning artifacts`). Copyright holder is written "Nick Antonizick" (the prompt said "Antoncic", which looks like a typo; matches git user and email). Dependabot docker directory is `/docker` (where Phase 14 puts the Dockerfile). No ADR needed.
- Verification: `git check-ignore` confirms `x.wav` and `.env` ignored, `tests/fixtures/audio/sample.fixture.opus` and `.env.example` not. A script checked every relative Markdown link: 0 broken. `lychee` is not installed locally, so the `docs-check` workflow itself is untested until it runs on GitHub. No tests exist yet (no code).
- Follow-ups: Phase 02 adds gitleaks and the Python CI and fills CONTRIBUTING dev setup. Phase 16 must replace `OWNER/REPO` in `.github/ISSUE_TEMPLATE/config.yml`, confirm the private security contact in `SECURITY.md` and `CODE_OF_CONDUCT.md` (no email was invented), and set the README badge URLs. `THIRD_PARTY_NOTICES.md` versions are "tbd" until pinned.

### 2026-10-11: Phase 02: Python scaffold, configuration & CI (Complete)
- Built on branch `phase-02-python-scaffold`: `pyproject.toml` (hatchling, `src/` layout, `mm3` script, `ml`/`bedrock` placeholder extras, dev group), `uv.lock`, `.python-version` 3.12; the full module tree with docstring-only placeholders; `config/paths.py`, `config/settings.py`, `errors.py`, `logging.py`, `app.py`, `cli.py`, `web/security.py`, `web/routes.py`, Jinja base layout and `app.css`; `.pre-commit-config.yaml`, `.gitleaks.toml`, `scripts/check_no_audio.py`, `scripts/gen_third_party.py`, `.github/workflows/ci.yml` (actions pinned to commit SHAs; docs-check kept).
- Toolchain: uv 0.13.0 installed with the installer script into `~/.local/bin` (Nick's choice); documented in OSMods (`uv Python Toolchain.md` + README). **ADR-0005 verified:** whisperx 3.8.6 / torch 2.8.0 / pyannote-audio 4.0.7 resolve on 3.12 (nothing installed yet). Added ADR-0007 (PyYAML, env naming, header-only CSRF).
- Deviations: env var names are nested (`MM3_SERVER__PORT`, `MM3_VAULT__PATH`, `MM3_SECRETS__HF_TOKEN`) instead of the flat names in Phase 01's `.env.example`; `.env.example` and the Phase 10 and 14 prompts were corrected. CSRF accepts the header only (no form field). sse-starlette was not added (Phase 04 can use `StreamingResponse`). `act` is not installed, so CI was not run locally; its steps were run by hand and `pip-audit` reported no known vulnerabilities. `pre-commit run --all-files` passes (the end-of-file fixer also touched `CODE_OF_CONDUCT.md` and `prompts/phase-08-llm-backends.md`).
- Verification: `uv run mm3 serve` answered `/` 200, `/healthz` ok, `Host: evil.com` 400. 26 tests pass (86% coverage); ruff, ruff-format and mypy strict clean.
- Follow-ups: Starlette's TestClient warns that `httpx` is deprecated in favour of `httpx2` (revisit when it is stable, Phase 15 dependency pass). CSP will need Alpine's CSP build or `'unsafe-eval'` (Phase 10). The gitleaks action needs a licence only for organisation repos (Phase 16 check).

### 2026-10-11: Phase 05: Hardware detection & recommendations (Complete)
- Built on branch `phase-05-hardware-awareness`: `hardware/detect.py` (nvidia-smi, then torch.cuda if importable, then CPU fallback via `/proc`; cached with refresh; AMD/Apple reported as unsupported), `hardware/profiles.py` (`cpu`/`vram8`/`vram16`/`vram24plus`, auto from total VRAM with a user override), `hardware/recommend.py` plus data file `hardware/recommendations.yaml` (transcription model, compute type, batch size, diarization, RTF range with `estimated`/`measured` status, ETA function, local LLM suggestions, VRAM-handoff note, risk warnings with severity), `hardware/doctor.py`, `web/hardware.py` (`GET /api/hardware`, `POST /api/hardware/refresh`) and `mm3 doctor`. New setting `hardware.profile` (`auto` default).
- Verification: on the reference machine `uv run mm3 doctor` reports the RTX 2070 Max-Q, 8.0 GB, profile `vram8`, `large-v3-turbo` / `int8_float16` / batch 8, about 2-4 minutes for 60 minutes of audio (estimated), and exits 0. The `gpu`-marked test passes. 79 tests pass (53 new), coverage 88%; ruff, ruff format and mypy strict clean. The app and all unit tests run with no torch installed.
- Deviations: profile thresholds sit below nominal sizes (7000/14000/22000 MiB) so real cards (8192 MiB for "8 GB") land in the right profile; a card under about 7 GB uses the `cpu` profile. `doctor` treats a missing ffmpeg/ffprobe, wrong Python, unwritable vault or data dir as blocking, and a missing vault, HF token, ML extras or Ollama as warnings. Added a mypy `ignore_missing_imports` override for `torch` (lazy import, extra not installed). Ollama URL is read from `llm.backends.ollama.base_url` with a `http://localhost:11434` default; Phase 08 should keep that key or update `hardware/doctor.py`. No ADR needed; no host changes, so no OSMods entry.
- Follow-ups: Phase 06 and Phase 15 replace the `estimated` numbers in `recommendations.yaml` with `measured` ones. Phase 06 adds model-download and ML-extras checks to `mm3 doctor`; Phase 10 renders `/api/hardware` and uses `Recommendation.transcription.estimate()`; Phase 12 exposes `hardware.profile`.
