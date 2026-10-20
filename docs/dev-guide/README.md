# Developer Guide

Pages are added as the code lands. Planned index:

| Page | Owning phase |
|---|---|
| [`setup.md`](setup.md) (uv, Python 3.12, pre-commit, tests) | 02 (written) |
| [`note-format.md`](note-format.md) (normative: names, frontmatter, section markers, transcript data block, archives, vault writes) | 03 (written) |
| [`jobs-and-stages.md`](jobs-and-stages.md) (job states, Stage protocol, checkpoints, resume, SSE, retention, fake pipeline; transcription, speaker and generation stages) | 04 (written), 06, 07, 09 |
| [`storage.md`](storage.md) (SQLite schema and migrations) | 04 (written) |
| `transcription.md` (WhisperX, VRAM handling) | 06 |
| [`adding-a-backend.md`](adding-a-backend.md) | 08 (written) |
| [`template-format.md`](template-format.md) (normative: template files, validation, prompt assembly, writing good prompts, map-reduce; replaces the planned `adding-a-template.md`) | 09 (written), 13 |
| `web-ui.md` (HTMX/Alpine conventions, vendored assets) | 10 |
| `release-process.md` | 16 |

See also [`../ARCHITECTURE.md`](../ARCHITECTURE.md), [`../MM3_DECISIONS.md`](../MM3_DECISIONS.md) and
[`../../CONTRIBUTING.md`](../../CONTRIBUTING.md).
