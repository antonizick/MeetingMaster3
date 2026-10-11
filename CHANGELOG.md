# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Hardware awareness (Phase 05): GPU/VRAM detection (nvidia-smi, torch.cuda if present, CPU fallback; no ML extras needed),
  hardware profiles `cpu`/`vram8`/`vram16`/`vram24plus` with a `hardware.profile` override, data-driven transcription
  and local-LLM recommendations (`recommendations.yaml`, marked estimated vs measured), ETA estimates, risk warnings,
  `GET /api/hardware` and `POST /api/hardware/refresh`, and the `mm3 doctor` command.
- LLM backend abstraction (Phase 08): `LLMBackend` interface; Ollama, OpenAI-compatible (OpenRouter, OpenAI and custom presets) and AWS Bedrock (Converse/ConverseStream, optional `bedrock` extra) adapters; `BackendRegistry`; typed `llm.backends` config with masked API keys; context budgeting (70% rule) and speaker-turn chunking; cloud-egress consent check; `/api/llm/*` endpoints; cloud model suggestions data file; `mm3 llm list` and `mm3 llm test`; Ollama `unload_all()` for VRAM handoff.
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
