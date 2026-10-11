# Phase 15: Hardening, Security Review & QA

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 13, 14 · **Branch:** `phase-15-hardening-qa`

## Read first
`CLAUDE.md`, `prompts/_shared-instructions.md`, all of `docs/SPECIFICATION.md` (especially §10, §13 and §15), `SECURITY.md`, `docs/PRIVACY.md`, `docs/ARCHITECTURE.md`, and every Phase Log entry, collecting all the open follow-ups.

## Goal
Turn a feature-complete MVP into a trustworthy one: a documented threat model, a security review with the findings fixed, a clean dependency and licence audit, end-to-end and regression coverage, **measured** performance on the 8 GB reference machine, and an accessibility pass.

## Tasks
1. **Threat model** (`docs/THREAT_MODEL.md`): assets (meeting audio, transcripts, notes, voiceprints, API keys, HF token, vault integrity); trust boundaries (browser ↔ localhost server, server ↔ filesystem/vault, server ↔ LLM providers, model downloads, container ↔ host); STRIDE per boundary; mitigations mapped to code; residual risks. Cover: malicious websites attacking localhost (DNS rebinding, CSRF, CORS), malicious audio files (ffmpeg parser attack surface: run with limits and timeouts, consider seccomp/no-network in Docker), malicious template files (prompt injection is in scope as a quality issue; template content must never execute code or reach arbitrary paths), **prompt injection from transcript content** (spoken text like "ignore previous instructions": ensure no tool use or filesystem actions are driven by LLM output; the output only fills sections), path traversal, secret leakage (logs, errors, HTML, exports, crash dumps), supply chain, and Docker escape surface.
2. **Security review:** run `/security-review` and `/code-review high` (or the equivalent manual review) over the codebase. Run `bandit` (ruff `S` is already on), `pip-audit`, `gitleaks` over the full git history, and `trivy` (or `grype`) on both images. Fix all high and medium findings; record low ones with rationale. Verify every S1–S8 control from spec §15.3 with a test, and build a control → test mapping table in SECURITY.md.
3. **Fuzz and robustness:** hypothesis fuzzing of the note/transcript parser and template loader with hostile inputs; very long audio (simulate a 3 h duration with the fake pipeline and check ETA, memory and progress behaviour; spec §3 edge case); a corrupt audio file; disk full during write (atomicity holds); vault unmounted mid-job; Ollama down mid-generation (clear error, resumable); browser closed during a job (job continues; reopening shows progress).
4. **Performance measurement on the reference machine** (RTX 2070 Max-Q 8 GB): with Nick's permission, use private recordings via `MM3_PRIVATE_TEST_AUDIO` (never committed), at roughly 10, 30 and 60 minutes. Measure per stage: wall time, RTF, peak VRAM (`nvidia-smi --query-gpu=memory.used -lms 500` logged) and peak RAM, for `large-v3-turbo` and `medium`, with diarization on. Measure LLM generation time with the recommended local model. Update `hardware/recommendations.yaml` (mark values `measured`), the README hardware table and the UI expectation text (R17). Write `docs/PERFORMANCE.md` with the method and the raw numbers.
5. **Quality regression:** run the full `tests/eval/` suite across all 22 templates with the recommended local model, and record the scores as a baseline (`tests/eval/baseline.json`) with a script that flags regressions.
6. **E2E coverage:** Playwright suite covering upload → speakers → generate → review → regenerate → save → re-open; settings; template library; consent dialog; OOM retry path (simulated); and error pages. Runs with the fake pipeline in CI (if feasible, otherwise documented as local-only).
7. **Accessibility:** axe-core (vendored, test-only) run via Playwright on the main pages; fix serious issues; check keyboard-only operation of the core flow.
8. **Licence audit:** regenerate THIRD_PARTY_NOTICES from the lockfile and vendored assets; make sure every licence is compatible with Apache-2.0 distribution; record the model-weight terms. Flag any GPL or AGPL dependency for Nick's decision.
9. **Close the follow-ups:** resolve or explicitly defer (to the roadmap, with a reason) every follow-up recorded in earlier Phase Log entries.

## Acceptance criteria
- `docs/THREAT_MODEL.md` exists, and every mitigation links to code and a test.
- No high or medium findings open from any scanner; scan outputs are summarised in the Phase Log.
- Measured performance numbers are published and replace the estimates.
- The full test suite (unit, integration and e2e with the fake pipeline) is green in CI; `gpu`/`models` tests are green locally on the reference machine.

## Phase-specific docs
THREAT_MODEL, PERFORMANCE, SECURITY (control table, reporting), PRIVACY (final data inventory), README (measured numbers, known limitations), THIRD_PARTY_NOTICES, and ADRs for any security-motivated design changes. Then the standard close-out checklist.
