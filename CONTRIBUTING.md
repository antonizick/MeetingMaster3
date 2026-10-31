# Contributing to MeetingMaster3

Thanks for your interest. MeetingMaster3 was built in numbered phases with AI coding agents; the
history is in [`MM3_IMPLEMENTATION_PLAN.md`](MM3_IMPLEMENTATION_PLAN.md) and the rules agents follow are in
[`CLAUDE.md`](CLAUDE.md). Human contributors can ignore the phase machinery: open an issue or a pull request
and keep the checks below green.

## Development setup
Python 3.12 is managed by [uv](https://docs.astral.sh/uv/) (install it first):
```bash
uv sync                      # creates .venv, installs locked deps
uv run pre-commit install    # ruff, mypy, gitleaks, audio-file guard on every commit
uv run pytest                # unmarked tests only in CI; see "Tests"
uv run ruff check . && uv run ruff format --check . && uv run mypy
```
ffmpeg is required on the host. Full guide: [`docs/dev-guide/setup.md`](docs/dev-guide/setup.md).

## Branches and commits
- Branch per change: `feat/<slug>`, `fix/<slug>`, `docs/<slug>` (agents use `phase-NN-<slug>`).
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
and an ADR in [`docs/MM3_DECISIONS.md`](docs/MM3_DECISIONS.md) for non-trivial choices.

## Secret scanning
A `gitleaks` pre-commit hook (and a CI job) scans for secrets, and another hook blocks audio files
outside `tests/fixtures/audio/*.fixture.*`. Install the hooks with `uv run pre-commit install`.
Deliberately fake tokens in unit tests are allowlisted in `.gitleaks.toml`.

## Adding a template
Templates are plain Markdown files with YAML frontmatter. The format, validation rules and how to write
good prompts are in [`docs/dev-guide/template-format.md`](docs/dev-guide/template-format.md); the built-in
ones live in `src/meetingmaster3/starter_templates/` and are listed in the
[catalogue](docs/user-guide/template-catalogue.md) (regenerate it with `uv run python scripts/gen_template_catalogue.py`).

## Adding an LLM backend
See [`docs/dev-guide/adding-a-backend.md`](docs/dev-guide/adding-a-backend.md): implement the `LLMBackend`
protocol, register its kind, and test it with a mocked transport (never a live key in CI).

## Conduct and security
See [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). Report vulnerabilities privately per [`SECURITY.md`](SECURITY.md).
