# Developer setup

## Prerequisites
[uv](https://docs.astral.sh/uv/) (it provisions Python 3.12, pinned in `.python-version`) and git.
ffmpeg from Phase 04. Docker from Phase 14.

## First run
```bash
uv sync                      # .venv + locked dependencies, including the dev group
uv run pre-commit install    # ruff, ruff-format, mypy, gitleaks, large-file and audio guards
uv run mm3 serve --reload    # dev server with auto-reload on 127.0.0.1:8765
```

## Quality gates (all must pass before a phase closes)
```bash
uv run pytest                # add -m "not gpu and not models and not network and not slow and not e2e" to mirror CI
uv run ruff check .
uv run ruff format --check .
uv run mypy                  # strict, src/ only (configured in pyproject.toml)
uv run pre-commit run --all-files
```
Coverage: `uv run pytest --cov`. Markers (`gpu`, `models`, `network`, `slow`, `e2e`) are registered
in `pyproject.toml`; `--strict-markers` is on.

Browser tests (CI runs them in their own job):
```bash
MM3_E2E_BROWSER=/usr/bin/chromium uv run pytest -m e2e tests/e2e   # or: uv run playwright install chromium
MM3_AXE_REPORT=/tmp/axe.json ...                                    # also write the full axe-core report
```
They use the fake pipeline (`MM3_FAKE_PIPELINE=1`; `MM3_FAKE_STAGE_SECONDS` sets each fake stage's
duration, `MM3_FAKE_LLM_SECONDS` how long each fake model call takes (so progress bars can be watched),
`MM3_FAKE_OOM=1` makes the fake transcription run out of GPU memory unless retried with
`medium`). They fail on any request to a host other than the app and on any page error. The
accessibility test injects the vendored axe-core (`tests/e2e/vendor/`) and fails on serious or
critical WCAG 2.1 AA violations.

On the reference machine, also run the GPU tests (`uv run --extra ml pytest -m "gpu and models"
tests/integration`; one of them is the socket audit: a diarized job may contact only loopback), the
generation eval with its regression check (`docs/PERFORMANCE.md` "Quality baseline") and, for
performance changes, `scripts/measure_performance.py`.

## Dependencies
Add with `uv add <pkg>` (runtime) or `uv add --dev <pkg>`; commit `pyproject.toml` and `uv.lock`.
Optional groups are `ml` (WhisperX stack) and `bedrock`. After any change:
`uv run --extra ml --extra bedrock python scripts/gen_third_party.py` refreshes `THIRD_PARTY_NOTICES.md`
and exits non-zero if a licence needs a decision (copyleft, unknown, unexpected proprietary); `--check`
only verifies. The vulnerability audits CI runs are
`uv export --frozen --no-emit-project --no-hashes | uvx pip-audit -r /dev/stdin --no-deps --disable-pip`
and `scripts/pip_audit_ml.sh` (the `ml` extra, with the ADR-0014 advisories ignored by id: review that
list on every WhisperX upgrade). Phase 15 also ran `uvx bandit -r src`, gitleaks over the full history
and trivy on both images (`docker run aquasec/trivy image meetingmaster3:gpu`); repeat before a release.

## Layout
See [`../ARCHITECTURE.md`](../ARCHITECTURE.md). Tests live in `tests/unit/` (including `test_fuzz.py`, Hypothesis fuzzing of
every parser of vault files, and `test_security_controls.py`), `tests/integration/` (GPU), `tests/e2e/`
(Playwright) and `tests/eval/` (generation quality with a real model); `tests/conftest.py` isolates XDG directories into a temp path so tests never touch your real
config.

A script run outside pytest (screenshots, measurements, one-off debugging) does not get that isolation: an app
it builds reads and writes your real `config.yaml` and `mm3.db`. Point it at temp folders first, e.g.
`MM3_CONFIG_DIR=$(mktemp -d) MM3_DATA_DIR=$(mktemp -d) uv run python script.py`. (A Phase 10 screenshot script
without this set the real vault to a temp folder and left an orphaned Recent entry.)

## Local CI
`act` was not available on the reference machine, so the workflow `.github/workflows/ci.yml` is
mirrored by the commands above; run them before pushing.

## Hooks
`scripts/check_no_audio.py` blocks audio/video files except `tests/fixtures/audio/*.fixture.*`.
`.gitleaks.toml` allowlists the intentionally fake tokens in four unit-test files.
