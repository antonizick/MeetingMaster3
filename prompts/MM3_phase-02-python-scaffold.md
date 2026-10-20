# Phase 02: Python Scaffold, Configuration & CI

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 01 · **Branch:** `phase-02-python-scaffold`

## Read first
`CLAUDE.md`, `prompts/MM3_shared-instructions.md`, and `docs/MM3_SPECIFICATION.md` §4, §11, §14, §15.2 (R1–R3) and §15.3 (S1, S2, S5). Also ADR-0005 in `docs/MM3_DECISIONS.md`.

## Goal
A running, empty-but-real application skeleton: `uv run mm3 serve` starts a FastAPI app on `127.0.0.1:8765` with security middleware, config loading and a health page. CI enforces lint, types, tests and security checks.

## Tasks
1. **Toolchain:** install `uv` if missing. If a system package is needed, document it per the OSMods rule. Prefer `curl -LsSf https://astral.sh/uv/install.sh | sh` into `~/.local/bin`, or `pacman -S uv`; ask Nick which he prefers. `.python-version` = `3.12`. **Verify ADR-0005:** confirm that the planned ML stack (whisperx, torch, pyannote.audio) resolves on 3.12 with `uv pip compile --dry-run` or an equivalent quick check, without installing it yet. Record the result and update ADR-0005 to Accepted or amend it.
2. **pyproject.toml:** project metadata (Apache-2.0, authors, URLs as placeholders); `src/` layout; package `meetingmaster3`; script `mm3 = "meetingmaster3.cli:main"`. Core deps: fastapi, uvicorn[standard], jinja2, pydantic, pydantic-settings, pyyaml (or ruamel.yaml if comment-preserving round-trip is needed; justify the choice in an ADR), python-multipart, sse-starlette (or native StreamingResponse), httpx, typer (CLI). **Optional dependency groups:** `ml` (whisperx, torch, etc.; pinned later in Phase 06), `bedrock` (boto3; Phase 08). Dev group: pytest, pytest-asyncio, pytest-cov, hypothesis, ruff, mypy, types-PyYAML, pip-audit, pre-commit.
3. **Package skeleton:** create the module tree from shared instructions §2, each module with `__init__.py` and a one-line docstring. Implement:
   - `config/paths.py`: XDG resolution plus `MM3_*_DIR` overrides; dirs created with `0700`.
   - `config/settings.py`: a pydantic `Settings` model covering server (host, port, allowed_hosts), vault (path, output_subfolder default `Meetings/{yyyy}/`, templates_subfolder default `MeetingMaster3/templates/`), transcription (placeholder), llm (placeholder backends dict), privacy (audio_retention, voiceprints_enabled default false), and a `secrets` block. Load order: defaults < config.yaml < env vars. `save()` writes atomically with mode `0600`. Secrets are `SecretStr`, masked on dump for the API.
   - `errors.py`: `MM3Error(code, message, hint)` plus a FastAPI exception handler that returns JSON or HTML depending on `Accept`.
   - `logging.py`: configure logging with a **secret-redaction filter** (redacts known secret values and patterns like `hf_…`, `sk-…`, AWS keys).
   - `app.py`: `create_app(settings)`. Middleware: **TrustedHost** (allowlist `127.0.0.1`, `localhost`, plus configured hosts) to defend against DNS rebinding; **security headers** (CSP `default-src 'self'`, `frame-ancestors 'none'`, `X-Content-Type-Options`, `Referrer-Policy: no-referrer`); **CSRF**, a double-submit token: a cookie (`SameSite=Strict`) plus a header or form field required on POST/PUT/PATCH/DELETE, with an Origin check. Routes: `GET /healthz` (JSON) and `GET /`, a Jinja2 base layout with a placeholder home page. `static/` with `app.css`.
   - `cli.py`: Typer app with `serve` (host, port, reload; warns loudly if host is not loopback), `config path` (prints the paths), `config show` (masked) and `version`.
4. **Quality gates:** ruff (lint and format, rules E,F,I,B,UP,S,SIM,RUF), mypy strict on `src/`, pytest config with markers `gpu models network slow e2e` registered and CI deselecting them (`-m "not gpu and not models and not network and not slow and not e2e"`), and coverage reporting.
5. **pre-commit:** ruff, ruff-format, mypy (local hook through uv), gitleaks, check-added-large-files (`--maxkb=500`), end-of-file-fixer, trailing-whitespace, and a custom hook that blocks committing audio files outside `tests/fixtures/audio/*.fixture.*`.
6. **CI** (`.github/workflows/ci.yml`): on push and PR; ubuntu-latest; setup uv with cache; `uv sync --frozen`; ruff; mypy; pytest; `pip-audit` (via `uv export | pip-audit -r -`); gitleaks action. Actions pinned. Keep the Phase 01 docs-check workflow.
7. **Tests:** settings precedence (defaults/yaml/env), 0600 permissions on save, secret masking, redaction filter, the TrustedHost rejection of `Host: evil.com`, a CSRF-rejected POST, security headers present, healthz, and the CLI `version` and `config path` commands.

## Out of scope
Domain models, ML, LLMs and real UI pages.

## Acceptance criteria
- `uv sync && uv run mm3 serve` serves `http://127.0.0.1:8765/` and `/healthz`. A request with a foreign Host header gets 400.
- `uv run pytest`, ruff and mypy are clean. The CI workflow is valid; run it locally with `act` if available, otherwise document why not.
- ADR-0005 is updated with the verified Python and ML-stack compatibility result.

## Phase-specific docs
README Installation (dev) and Quickstart (dev server); `docs/user-guide/configuration.md` (every setting, defaults, env var names, file locations); `docs/dev-guide/setup.md`; CONTRIBUTING dev setup (no longer "coming"); SECURITY (middleware controls, now implemented); THIRD_PARTY_NOTICES (actual deps from the lockfile, which a script `scripts/gen_third_party.py` may generate). Then the standard close-out checklist.
