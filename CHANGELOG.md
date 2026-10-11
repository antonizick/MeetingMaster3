# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Python scaffold (Phase 02): `uv` project pinned to Python 3.12, `src/meetingmaster3` package tree, `mm3` CLI
  (`serve`, `version`, `config path`, `config show`) and a FastAPI app factory serving `/` and `/healthz`
  on `127.0.0.1:8765`.
- Configuration: pydantic `Settings` (defaults < `config.yaml` < `MM3_*` env), XDG paths with overrides,
  atomic `0600` saves, masked `SecretStr` secrets, `MM3Error` with JSON/HTML handler.
- Security middleware: Host allowlist (DNS rebinding), security headers and CSP, double-submit CSRF with
  Origin check; log secret-redaction filter.
- Quality gates: ruff, strict mypy, pytest (markers registered, 26 tests), coverage, pre-commit (gitleaks,
  audio-file guard, large-file guard), `ci.yml` workflow (lint, types, tests, `pip-audit`, gitleaks).
- `scripts/gen_third_party.py` generates the runtime-dependency table in `THIRD_PARTY_NOTICES.md`.
- Docs: configuration reference, installation and developer setup guides; ADR-0005 verified, ADR-0007 added.
- Project governance files: `LICENSE` (Apache-2.0), `NOTICE`, `THIRD_PARTY_NOTICES.md`, `README.md`,
  `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`.
- Repository hygiene: `.gitignore` (audio, secrets, models and local data excluded),
  `.editorconfig`, `.gitattributes`, `.env.example`.
- GitHub scaffolding: issue forms, pull request template, Dependabot config and a Markdown link
  check workflow.
- Documentation skeleton: `docs/ARCHITECTURE.md`, `docs/PRIVACY.md`, user and developer guide indexes.
- Planning artifacts from Phase 00: specification v1.1, ADR log, implementation plan and phase prompts.
