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

## Dependencies
Add with `uv add <pkg>` (runtime) or `uv add --dev <pkg>`; commit `pyproject.toml` and `uv.lock`.
Optional groups `ml` and `bedrock` are placeholders filled in by Phases 06 and 08. After any change:
`uv run python scripts/gen_third_party.py` to refresh `THIRD_PARTY_NOTICES.md`, and check the licence
first. The vulnerability audit CI runs is
`uv export --frozen --no-emit-project --no-hashes | uvx pip-audit -r /dev/stdin --no-deps --disable-pip`.

## Layout
See [`../ARCHITECTURE.md`](../ARCHITECTURE.md). Tests live in `tests/unit/` (and later `integration/`,
`e2e/`); `tests/conftest.py` isolates XDG directories into a temp path so tests never touch your real
config.

## Local CI
`act` was not available on the reference machine, so the workflow `.github/workflows/ci.yml` is
mirrored by the commands above; run them before pushing.

## Hooks
`scripts/check_no_audio.py` blocks audio/video files except `tests/fixtures/audio/*.fixture.*`.
`.gitleaks.toml` allowlists the intentionally fake tokens in three unit-test files.
