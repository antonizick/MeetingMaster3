# Contributing to MeetingMaster3

Thanks for your interest. The project is pre-alpha and is being built in numbered phases; read
[`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) and [`CLAUDE.md`](CLAUDE.md) first.

## Development setup
Python 3.12 is managed by [uv](https://docs.astral.sh/uv/) (install it first):
```bash
uv sync                      # creates .venv, installs locked deps
uv run pre-commit install    # ruff, mypy, gitleaks, audio-file guard on every commit
uv run pytest                # unmarked tests only in CI; see "Tests"
uv run ruff check . && uv run ruff format --check . && uv run mypy
```
ffmpeg is required on the host from Phase 04. Full guide: [`docs/dev-guide/setup.md`](docs/dev-guide/setup.md).

## Branches and commits
- Branch per phase or change: `phase-NN-<slug>`, `feat/<slug>`, `fix/<slug>`.
- [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`,
  `chore:`, `refactor:`.
- Sign off commits (`git commit -s`, Developer Certificate of Origin) - recommended.

## Tests
`pytest` with markers `gpu`, `models`, `network`, `slow`, `e2e`. CI runs only unmarked tests, so use
fakes (`FakeTranscriber`, `FakeLLMBackend`) for anything needing a GPU, models or network.
Test fixtures must be synthetic or Creative Commons, with attribution in `tests/fixtures/README.md`.
Never commit real recordings, vault content, tokens or `.env`.

## Docs are part of "done"
A change is not complete until the affected docs are updated: README, CHANGELOG (`[Unreleased]`),
SECURITY, ARCHITECTURE, guides, `THIRD_PARTY_NOTICES.md` for any new dependency or vendored asset,
and an ADR in [`docs/DECISIONS.md`](docs/DECISIONS.md) for non-trivial choices.

## Secret scanning
A `gitleaks` pre-commit hook (and a CI job) scans for secrets, and another hook blocks audio files
outside `tests/fixtures/audio/*.fixture.*`. Install the hooks with `uv run pre-commit install`.
Deliberately fake tokens in unit tests are allowlisted in `.gitleaks.toml`.

## Adding a template
_Stub - documented in Phase 09 (schema) and Phase 13 (library)._

## Adding an LLM backend
_Stub - documented in Phase 08._

## Conduct and security
See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). Report vulnerabilities privately per [`SECURITY.md`](SECURITY.md).
