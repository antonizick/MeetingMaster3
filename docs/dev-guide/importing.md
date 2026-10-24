# Importing: parser interface and the `import` job

Phase 15k (spec R32, ADR-0052). Package `src/meetingmaster3/importing/`. Phase 15l adds Grok share links (`grok_share.py`, `fetch.py`) on this interface.

## The interface (`importing/model.py`)
```python
@dataclass(frozen=True)
class ImportedTurn:
    speaker: str  # "Alice", "Grok"; "" when the file names nobody or only a role
    role: Literal["user", "assistant", "other"] | None
    text: str  # Markdown inside an AI answer is kept
    start: float | None = None  # seconds; None = untimed (never invent a time)
    end: float | None = None
    confidence: float = 1.0  # 0-1, how sure the parser is about speaker/role
    words: tuple[Word, ...] = ()  # word timings (MM3 companions only)


@dataclass(frozen=True)
class ImportedConversation:
    turns: list[ImportedTurn]
    title: str | None
    started_at: datetime | None
    source_format: str  # the parser id
    warnings: list[str]
    timed: bool  # property: every turn has a start
```

A parser is `Callable[[str, str], ImportedConversation]` (`text, filename`) and raises **only** `MM3Error`. `detect.py:PARSERS` maps ids to parsers; `FORMAT_NAMES` in `model.py` gives the UI name ("Imported from …").

| Id | Module | Detected by |
|---|---|---|
| `mm3-companion` | `timestamped.parse_companion` | frontmatter plus `<!-- mm3:transcript-data v` (the data block is used exactly) |
| `webvtt` | `timestamped.parse_vtt` | `WEBVTT` header |
| `srt` | `timestamped.parse_srt` | at least half the blocks are `N` + `hh:mm:ss,mmm --> …` (any SRT cue with the `.srt` extension) |
| `timestamped-text` | `timestamped.parse_timestamped` | at least 25 % of the non-blank lines start a timed cue: `[h:mm:ss] Name: text`, `**[hh:mm:ss] Name:** text`, `00:04 Alice` or `Alice 00:00:04` header lines (a "name" of more than six words, or one ending in a full stop, is a sentence) |
| `chat-markdown` | `chat.parse_labelled` | two or more role markers (headings, `**Name:**`, `Name:`; role words in `USER_WORDS`/`ASSISTANT_WORDS`), or two repeated custom names (`NOT_SPEAKERS` like "Note" or "Step" never count); markers inside code fences are ignored |
| `chat-unlabelled` | `chat.parse_unlabelled` | everything else |
| `grok-share` (15l) | `grok_share.parse_share` | checked first: a JSON object whose `responses` list holds objects with `sender` (a downloaded share is always read with it, never detected) |

`detect_and_parse(data, filename, *, max_bytes)` decodes first (`decode`: UTF-8, BOM stripped, newlines normalised; NUL bytes, invalid UTF-8 or many control characters → `E_IMPORT_UNREADABLE`; over the limit → `E_IMPORT_TOO_LARGE`, 413; nothing → `E_IMPORT_EMPTY`), takes a leading YAML frontmatter's `title` and `date`/`created` (except for companions), detects, parses, and caps the turns at 20 000. Any `ValueError`/`IndexError`/`KeyError`/`RecursionError` from a parser becomes `E_IMPORT_UNREADABLE`. A Hypothesis test feeds arbitrary text to it.

**Adding a parser:** write `parse_x(text, filename) -> ImportedConversation`, add its id to `PARSERS` and `FORMAT_NAMES`, and either add a content check to `detect()` or call it directly.

## The unlabelled heuristic (`chat.py`)
1. `split_paragraphs`: blank-line paragraphs (a fenced code block stays whole), export chrome dropped (`CHROME`: `N / N`, Copy, Share, Regenerate…).
2. `collapse_prefixes`: a paragraph that the next one repeats and extends (`is_growing_prefix`: word tokens, case and punctuation ignored; exact token prefix, or a `SequenceMatcher` ratio ≥ 0.85 against the next paragraph's head for four words or more) is dropped. This repeats, so 2-5 growing copies collapse to the last.
3. `user_score` (log-odds that the paragraph is the user's): fillers +3 each (cap 7.5), stutters ("I, I") +1.5, conversational opening +1, first person +0.35 each (cap 2), questions to the assistant +0.8 (cap 1.6); tool-status line −6, em dash −1.4 each (cap 4.2), Markdown −2.5, "your/you'd…" −0.4 (cap 2), figures and currency −0.5 (cap 2), semicolons −0.6, longer than 300 characters without fillers −1.5 to −3.5.
4. `assign_roles`: forward-backward over two states with emissions `sigmoid(score)`, a first-turn prior of 0.8 for the user, and staying probabilities 0.12 (user → user, rare once prefixes are collapsed) and 0.45 (assistant → assistant, multi-paragraph answers). The posterior of the chosen role is the turn's `confidence`; below `convert.LOW_CONFIDENCE` = 0.8 it is highlighted.
5. A tool-status line ("Checking current numbers.", `is_tool_status`) joins the following assistant paragraph.

Measured: 28/28 paragraphs on the synthetic fixture (`tests/fixtures/imports/voice-mode-unlabelled.md`, ground truth in `.labels`), 99/101 (98 %) on the private example the phase was built for (ADR-0052, Phase 15k implementation).

## From conversation to transcript (`convert.py`)
`to_transcript(conv, user_name=…, assistant_name="AI")` returns a `Transcript` and its `ImportSpeaker`s (`label`, `role`, `detected`, `default_name`). One segment per turn (`id` = turn index), labels `SPEAKER_00`, `SPEAKER_01`… in order of first appearance. In an AI conversation all user turns share one label and all assistant turns another (an unlabelled one always has both, so any turn can be moved); a person in a transcript is keyed by name. Untimed: `start = end = 0`, `timed=False`, `duration=None`. Default names: the user → `options.import_speakers.user`, else the first participant, else `importing.user_name`; the assistant → `import_speakers.assistant`, else the name in the export ("Grok", "Claude"), else "AI".

## The `import` job (`importing/stages.py`, `jobs/pipeline.py`)
`IMPORT_STAGES`: `import_parse` ("Reading the file") → `await_speaker_confirmation` ("Check the speakers", question kind `import_confirmation`) → `generate` → `write`. No GPU, ffmpeg or audio; `audio_path` is `None`, so retention, the player and **Keep forever** do nothing (pinning is refused with `E_AUDIO_MISSING`). The registry overrides the import's own stages as `import:<name>`.

Job folder:

| File | Written by | Content |
|---|---|---|
| `source.<ext>` | upload | the file (`md`, `markdown`, `txt`, `text`, `vtt`, `srt`, else `txt`) |
| `import.json` | `import_parse` | the preview: format, warnings, speakers, every turn (`index`, `label`, `role`, `text`, `start`, `confidence`, `low`) |
| `transcript.parsed.json` | `import_parse` (artifact) | the parsed `Transcript` |
| `transcript.imported.json` | confirmation | the corrected transcript, read by `generate`/`write` (`templates.stages.load_final_transcript`) |
| `speaker_map.json`, `transcript.named.json`, `speakers.confirmed.json` | confirmation | as for a meeting |

The answer is `{"speakers": {label: name}, "turns": {"<index>": label}}` (only moved turns). `normalise_answer` checks the shape, `check_answer` (web form) checks labels and turns against the preview, and the stage ignores unknown labels with a warning. `options.import_confirmed: true` (`mm3 import --yes`) skips the pause; a transcript with no speakers never pauses. `import_parse` records the parser id in `options.import_format`; `generate` and `write` add `mm3-source: import` and `mm3-source-format` to the note and the companion (`templates.stages.source_properties`).

## API
`POST /api/imports`: the same multipart shape as `POST /api/jobs` (`file` plus JSON `options`) and the same CSRF, Host and Origin checks and `preflight`. The file is streamed under `importing.max_mb` and **parsed once** before the job exists, so a bad file is a 422/413 with nothing left behind. Missing title and date come from the file (`import_defaults`), then the file name. Answer the check with `POST /api/jobs/{id}/input` or the form route `POST /ui/jobs/{id}/import-check`. `GET /jobs/{id}/speakers` renders `import_check.html` for import jobs.

Headless: `headless.process(…, ProcessRequest(path, options, job_type="import"))`; CLI `mm3 import`.

## Grok share links (Phase 15l)
- **`grok_share.parse_share_url(text) -> str`** returns the share id or raises `E_IMPORT_URL_UNSUPPORTED` (422): https only, hosts `x.com`, `twitter.com`, `grok.com` and their `www.` forms compared exactly (ASCII), paths `/i/grok/share/<id>` or `/share/<id>` with an optional trailing slash, id `[A-Za-z0-9_-]{8,200}`; no user info, port, encoding, `..` or backslash; query and fragment dropped. `looks_like_share_url` tells `mm3 import` a link from a file name.
- **`fetch.fetch_share(share_id, *, max_bytes, check, sleep, transport=None) -> bytes`**: the only outbound request to a non-LLM site. It builds `https://grok.com/rest/app-chat/share_links/<id>` itself (`share_url` refuses an invalid id), uses a fresh `httpx.Client` (`follow_redirects=False`, `verify=True`, `trust_env=True` for `HTTPS_PROXY`, 20 s timeouts, 60 s deadline), streams under `max_bytes`, calls `check()` between chunks (the stage passes `ctx.check_cancelled`), clears cookies after each attempt and retries a 5xx or timeout once (`sleep`). Errors: `E_IMPORT_SHARE_NOT_FOUND` (401/403/404/410), `E_IMPORT_SHARE_UNAVAILABLE` (3xx, other statuses, not JSON), `E_IMPORT_OFFLINE` (transport errors, timeouts), `E_IMPORT_TOO_LARGE`. Tests mock it with `respx` (unmatched requests fail).
- **`grok_share.parse_share_data(data)`** (or `parse_share(text, filename)`): pydantic models that ignore unknown keys; the thread follows the latest child at each branch (`_thread`); partial, empty and unknown-sender messages are dropped with warnings; growing user prefixes merge at the first copy's time; `start` is relative to the first kept message and `end` is the next turn's start; one missing `createTime` makes the whole conversation untimed. Title: `conversation.title` unless in `GENERIC_TITLES`, then `title_from(first user message)`. `started_at` is local time.
- **Job.** `POST /api/imports` without a file part and with `options.share_url` → `stages.share_options` stores `import_share_id`, `import_fill` (the empty ones of `title`, `meeting_date`, `meeting_time`) and the placeholder title `SHARE_PLACEHOLDER_TITLE`; `source_filename` is `SHARE_SOURCE_NAME` ("Grok share link"). `ImportParseStage` calls `download_share` when there is no `source.*` (atomic `source.json`), reads it with `parse_share_source`, deletes it if it is unreadable (so a resume downloads again), and `fill_details` writes the filled details and the duration to `ctx.options` and the job row. The New meeting page's `awaitDownload` polls `GET /api/jobs/{id}` until `import_parse` completes, or shows its error inline and deletes the job. Headless: `ProcessRequest(share=True)`, `headless.build_share_options`.
- **Tests.** `tests/unit/importing/test_grok_share.py` (links, fetch, parser), `test_share_jobs.py` (API, stage, resume, cancel, CLI), the e2e cases in `tests/e2e/test_import_flow.py`, fixtures `tests/fixtures/imports/grok-share-*.json`. The `network` test `test_live_synthetic_share` runs only with `MM3_TEST_GROK_SHARE` set to a synthetic share made for testing.
