# Phase 15i: Meeting index and hybrid search (meaning + words)

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 15h · **Branch:** `phase-15i-meeting-index-search` · **Worktree:** `../MeetingMaster3-phase-15i`

Inserted with `/phase-add` after 15h (ADR-0034, ADR-0049). Nick wants an **Ask AI agent**: broad questions answered from
the meeting notes and transcripts on file, RAG-style, understanding meaning and intent rather than only matching words
(the agent itself is Phase 15j). Nothing in MeetingMaster3 can search across meetings today. This phase builds the
foundation 15j stands on: an embedding call in the LLM backends, a local index of every MM3 note and companion
transcript (word index plus meaning vectors), kept in step with the vault, and a hybrid search that the user can
already try on a **Search** page and with `mm3 search`. Splitting it out keeps each session focused and lets the
retrieval quality be checked before an LLM writes answers on top of it.

## Read first
- `CLAUDE.md`, `prompts/MM3_shared-instructions.md`, `docs/MM3_SPECIFICATION.md` §5, §9 and §15 (R5 VRAM handoff, R9,
  R18, R21, R25 readable transcript, R28 rename; S1-S6).
- **ADR-0049** (this feature's decisions, planning), ADR-0009 (adapter style), ADR-0010/0012 (companion data block,
  round-trip), ADR-0013 (GPU semaphore), ADR-0047 (vault scan by `mm3-id`), ADR-0040 (rename).
- `prompts/MM3_phase-15j-ask-ai-agent.md`: what will consume this phase's API. Design the search API for it.
- Phase Log entries of 15g and 15h (backend quirks, the capable-model filter, Settings backend form).

## Nick's request (verbatim intent, 2026-10-22 13:32 CDT)
"I want to add a feature called 'Ask AI agent' where the user can ask broad questions and the AI agent will use the
meeting notes and transcripts on file to answer the question. For example: "How many times have we discussed "X"
topic, Who was principally in those discussions and what was their role? Also, create a table of all of the meetings
and all of the dates and all of the attendees that have participated in discussions about this topic""

During intake: "What I gave you was an example question only (To be fair, which is probably somewhat typical). What
I'm looking for is the user to be able to add broad questions about meetings that are documented and using a RAG style
Capability have the AI answer questions. I would want the AI to be able to derive meaning and intent and not be only a
simple word search, although a word search may be a capability we would want it to have. Ideally, we would be able to
use local models or bedrock or open router to support this capability."

## Decisions already made (ADR-0049)
- **Hybrid retrieval:** an SQLite FTS5 word index **and** embedding vectors over the same passages, results fused.
  Word search alone was rejected (misses meaning); a free tool-calling agent was rejected for retrieval.
- **Embeddings come through the LLM backends** (a new optional `embed()` call), **local by default**: Ollama
  `nomic-embed-text` (Apache-2.0, 274 MB; already pulled on Nick's machine). Bedrock (Amazon Titan Text Embeddings V2)
  and OpenAI-compatible `/embeddings` are supported as options. No new Python dependency (no ONNX runtime in core).
- **Cloud embedding sends the full text of every indexed meeting** to the provider at indexing time, so it requires its
  own explicit, sticky consent in Settings (separate from note writing's `consent_remembered`), with that consequence
  stated plainly. Without it a cloud embedder is refused (`E_CONSENT_REQUIRED`) and nothing is sent.
- Split: **15i** builds the index and search; **15j** builds the agent, answers and the Ask page.

## Goal
With Nick's real vault, `Settings → Search & Ask` shows an index of every MM3 meeting (notes and companion
transcripts) built with the local embedding model, kept current as meetings are written, saved, renamed or removed;
the **Search** page and `mm3 search "<question>"` return the passages most related to a question **by meaning and by
words**, grouped by meeting, each linking to the meeting (and the transcript moment), and the same search is available
to 15j as a Python API.

## What exists (verified 2026-10-22 13:44 CDT; re-check before relying on it)
- **No search of any kind.** No FTS table, no embeddings, no `embed` method; `LLMBackend` (`llm/base.py:LLMBackend`) has
  `generate`, `stream`, `list_models`, `test_connection`, `context_window`, `warm` only.
- SQLite is 3.53 with **FTS5 available** (checked with uv's Python 3.12). `numpy` 2.5 is locked (only via the `ml`
  extra: check whether it is a core dependency before using it in core code; if not, pure-Python cosine over
  `array('f')` is fine at this scale, or add `numpy` to core with a licence note).
- Ollama: `llm/ollama.py` calls `/api/chat`, `/api/tags`, `/api/show`, `/api/ps`, `/api/generate`; Ollama's
  `/api/embed` (`{"model", "input": [..]}` → `{"embeddings": [[..]]}`) is not used. `ollama list` on Nick's machine
  shows `nomic-embed-text:latest` (and `qwen3:8b`). `ModelInfo.can_generate` exists; an embedding-only model must
  stay hidden from the note pickers (15h filter `templates/model_check.py:assess`) but be offered as an embedder.
- Bedrock: `llm/bedrock.py` uses `converse`; embeddings need `invoke_model` (`amazon.titan-embed-text-v2:0`,
  `{"inputText", "dimensions", "normalize"}`). The IAM policy in `docs/user-guide/llm-backends.md` already allows
  `bedrock:InvokeModel`; the model may need access enabled in the account (say so in the docs).
- OpenAI-compatible: `llm/openai_compat.py` has no `/embeddings` call. Whether **OpenRouter** serves `/embeddings`
  must be checked (docs or a live call if Nick has a key in this session); if it does not, the OpenRouter preset is
  marked "no embeddings" and the user is told to use local Ollama.
- Vault scanning: `vault/relink.py:index_vault` walks the vault (hidden folders skipped, 50 000 files max) and
  `vault/picker.py:read_identity` classifies a file from its frontmatter: live note (`is_note`), companion transcript
  (`is_transcript`), readable transcript (`is_readable`, never parsed back, R25) and archives (`archived`).
- Parsers: `markdown/note_parser.py:parse_note` (frontmatter `title`, `date`, `participants`, `tags`, `mm3-speakers`,
  `mm3-template`; sections), `markdown/sections.py:scan_sections`/`list_sections` (section ids and spans),
  `markdown/transcript_format.py:parse_transcript` (the lossless data block: segments with times and speaker labels;
  names from `mm3-speakers`).
- Writers that change meeting files: the write stage (`templates/stages.py`), review save (`review/save.py`), template
  switch (`review/switch.py`), regeneration accept, rename (`review/rename.py`, R28), upgrade (`review/upgrade.py`),
  Meetings "Remove"/relink (`web/pages.py`, `vault/relink.py`).
- Background work: the job runner holds a **GPU semaphore** (`jobs/runner.py`, `_gpu`, R5); long review actions use
  `review/progress.py:TaskRegistry`/`LongTask` (in memory, polled, cancellable, ETA).
- Settings: `config/settings.py` (pydantic, `BackendConfig.consent_remembered`), the declarative Settings screen
  (`web/settings_fields.py`, `web/settings_ui.py`, ADR-0020); navigation tuples in `web/pages.py` (around line 67).
- Data dir layout (R3): `mm3.db` (migrations in `storage/migrations.py`, currently v4).

## Tasks
1. **`embed()` in the backends.** Add an optional capability to the backend protocol: `supports_embeddings` and
   `async embed(model: str, texts: Sequence[str]) -> list[list[float]]` (batching, timeouts, retries and error mapping
   like `generate`; `MM3Error` codes, e.g. `E_LLM_EMBED_UNSUPPORTED`). Implement it for Ollama (`/api/embed`), Bedrock
   (`invoke_model`, Titan V2, 1024 dimensions, normalised; one text per call, bounded concurrency) and OpenAI-compatible
   (`/embeddings`; OpenRouter per the check above), plus `FakeLLMBackend` (deterministic vectors so tests can assert
   ranking). Embedding models are listed for the embedder picker (Ollama: models whose `/api/show` capabilities include
   `embedding`; Bedrock: Titan/Cohere embedding ids; never in the note pickers). `mm3 llm test` reports embedding
   support.
2. **Settings.** New `search` section (pydantic, defaults, documented in `configuration.md`): `enabled` (true),
   `embedding_backend` (default: the first local backend, normally `ollama`), `embedding_model` (`nomic-embed-text`),
   `chunk_tokens` (about 350) and `chunk_overlap` (about 50), `index_transcripts` (true), and the sticky
   `cloud_embedding_consent` per backend (ADR-0049; a `BackendConfig` field next to `consent_remembered`, off by
   default, shown in the backend form with the warning "Indexing sends the full text of every meeting to <provider>").
   A Settings card **Search & Ask** shows the embedder, index status (meetings, passages, model, last update,
   errors) and **Update index** / **Rebuild index** / **Delete index** buttons.
3. **Index store.** A separate, rebuildable SQLite file `<data>/search.db` (derived data, never in the vault, created
   0600, `secure_delete` on, own schema version), holding: documents (`mm3_id`, vault-relative path, kind
   `note`/`transcript`, title, date, participants and speaker names, sha256, mtime, indexed time), passages (document,
   order, text, `section_id`/heading for notes, start/end seconds and speaker names for transcripts), an **FTS5** table
   over the passage text (porter/unicode61 tokenizer, external content), and vectors (passage, embedding model id,
   dimensions, float32 blob). The embedding model id and dimensions are recorded; a different model forces a rebuild
   (never mix vectors). ADR: separate file vs `mm3.db` migration; default separate file.
4. **Chunking and indexing.** Index only live MM3 notes and companion transcripts (skip readable transcripts, archives,
   answer notes from 15j (`mm3-kind: answer`), non-MM3 files, hidden folders, symlinks; S4 confinement). Notes: one or
   more passages per section, prefixed with the meeting title, date and section heading; the frontmatter and the
   header lines (participants, date) become document metadata. Transcripts: consecutive speaker turns from the data
   block grouped into about `chunk_tokens` windows with overlap, each carrying its start/end time and speaker names
   (resolved through `mm3-speakers`), prefixed with "Speaker: …". Incremental: compare sha/mtime, re-index only changed
   files, drop documents whose files are gone, and follow a rename by `mm3-id` (no re-embedding when only the path
   changed). Indexing runs as a background task (progress, cancel, ETA, reusing `TaskRegistry`/`LongTask` or a small
   equivalent) and **never competes with a transcription job for the GPU**: it waits for the job runner's GPU
   semaphore (or for an idle runner) before calling a local embedder, in batches, and lets the embedder unload
   (`keep_alive` short) so R5 still holds. Triggers: a scan at start-up (after migrations, non-blocking), after each
   of the writers listed above (enqueue the affected `mm3_id`; a cheap call), the Settings buttons, and
   `mm3 search index [--rebuild]`. If the embedder is unavailable (Ollama down, model not pulled, no consent), the word
   index is still built and the status says why vectors are missing and how to fix it (`ollama pull nomic-embed-text`).
5. **Hybrid search API.** `search.query(text, *, limit, filters) -> SearchResult` in a new package
   `src/meetingmaster3/search/` (`index.py`, `chunking.py`, `store.py`, `query.py`): FTS5 BM25 top-N with the user
   text **escaped into safe FTS5 terms** (never raw FTS syntax from the user; quotes and operators cannot break or
   widen the query), plus vector cosine top-N (brute force is fine for tens of thousands of passages; measure), fused
   with reciprocal-rank fusion (k = 60; record any tuning). Filters: date range, participants/speakers, kind, `mm3_id`
   list. Results carry passage text, a highlighted snippet, `mm3_id`, title, date, kind, section or start time,
   speakers, and both scores; a `group_by_meeting()` helper returns meetings ranked by their best passages with all
   their hits. Word-only mode works without vectors and says so. Also expose `meeting_facts(mm3_ids)` (title, date,
   participants from frontmatter, speakers who spoke in the hits) for 15j's code-built tables.
6. **Search page and CLI.** A **Search** entry in the navigation (`/search`): one query box, optional date range and
   person filter, results grouped by meeting (title, date, how many passages matched), each passage as a sanitised
   snippet (S3) linking to `/meetings/{mm3-id}` and, for transcript passages, to the moment (`#t=<seconds>` or the
   review page's existing seek mechanism), a "meaning + words" / "words only" indicator, and a link to the index
   status. Server-rendered (HTMX), CSP-clean, keyboard accessible, paged. CLI `mm3 search "<text>" [--limit]
   [--from --to] [--json]` and `mm3 search index [--rebuild]`, `mm3 search status`.
7. **Consent and privacy.** Query embedding with a cloud embedder sends the query text, and indexing sends every
   meeting: both require `cloud_embedding_consent` for that backend; the search page shows the "local" / "cloud:
   <provider>" badge for the embedder (S6). Transcript text is never logged at INFO. Deleting the index removes
   `search.db` (and its WAL/SHM). `docs/PRIVACY.md` and `docs/THREAT_MODEL.md` describe the index (what it holds,
   where, how to delete it, what goes to a cloud embedder).
8. **Measure on the real vault.** With Nick's vault and local `nomic-embed-text`: number of meetings and passages,
   full index time, incremental update time after one note save, search latency (word, vector, hybrid), `search.db`
   size, and a small private relevance check: 5-10 questions Nick would ask (ask him for a few, or write them from
   the meeting titles), with the top meetings found by word-only vs hybrid. Private material goes in
   `~/.local/share/meetingmaster3/private-eval-15i/` and is deleted at close-out; only aggregate numbers go in
   `docs/PERFORMANCE.md`. If hybrid is not clearly better than words for meaning-type questions, record it and try a
   different chunk size or `bge-m3`/`qwen3-embedding` via Ollama before closing (ADR the choice).

## Out of scope
- Answer generation, the Ask page, answer notes, Ask consent (15j).
- In-process embedding models (ONNX, sentence-transformers), external vector databases, sqlite-vec, re-ranking models.
- Indexing non-MM3 vault notes (possible later; keep the indexer's file filter in one place so it can be widened).

## Tests
- Unit: `embed()` for Ollama (respx), OpenAI-compatible (respx, including "not supported"), Bedrock (Stubber, Titan
  request body and error mapping), fake backend; chunking of notes (sections, headers, overlap) and transcripts (turn
  grouping, times, speaker names via `mm3-speakers`, non-diarized transcript); indexer skips readable transcripts,
  archives, answer notes, symlinks and files outside the vault; incremental update (changed, deleted, renamed by
  `mm3-id` without re-embedding); model change forces a rebuild; FTS5 escaping (quotes, `NEAR`, `*`, `-`, `:`,
  parentheses, empty and very long input); RRF fusion; filters; word-only fallback; consent refusal sends nothing.
- A synthetic test corpus in `tests/fixtures/` (notes + companions; synthetic text, attribution in
  `tests/fixtures/README.md`) where one topic appears in three meetings **in different words** (for example "budget
  overrun" / "spending more than planned" / "costs exceeded the forecast") and the fake or a real local embedder
  ranks all three above unrelated meetings (`@pytest.mark.models` for the real embedder).
- Web: Search page renders, escapes snippets, links, pagination; Settings card buttons with CSRF; the GPU-wait rule
  (indexing does not start while a fake GPU job holds the semaphore).
- e2e (Chromium): search for a phrase in the fixture vault and open the meeting at the passage.
- `uv run pytest`, `ruff check`, `ruff format --check`, `mypy src`; `mypy src tests` no worse than `main`.

## Acceptance criteria
- With Nick's vault: the index builds with `nomic-embed-text`, its status in Settings is correct, and a question
  phrased differently from the notes' words finds the right meetings (shown in the private relevance check).
- Saving, renaming or removing a meeting updates the index without a rebuild; a transcription job is never slowed by
  indexing on the GPU.
- `/search` and `mm3 search` return grouped, linked results; FTS syntax in a query cannot cause an error page.
- A cloud embedder without its consent sends nothing and says why; with Ollama stopped, word search still works.

## Phase-specific docs
- ADR-0049: append "Phase 15i implementation" (store layout, chunk sizes, fusion, GPU rule, OpenRouter embeddings
  finding, measured numbers); new ADRs for further choices. Spec §15: add **R30** (meeting index and search).
- `docs/user-guide/` (new `search-and-ask.md`, started here and completed in 15j; `configuration.md`, `settings.md`,
  `llm-backends.md` embedding models and Bedrock access), `docs/dev-guide/adding-a-backend.md` (`embed()`),
  `docs/MM3_ARCHITECTURE.md` (search package, `search.db`), `docs/PERFORMANCE.md`, `docs/PRIVACY.md`,
  `docs/THREAT_MODEL.md`, README feature list, `.gitignore`/`.dockerignore` if anything new, `THIRD_PARTY_NOTICES.md`
  (nomic-embed-text and Titan are models the user pulls/calls, not bundled: mention like the other models),
  Docker docs (the bundled Ollama needs `nomic-embed-text` pulled).
- If anything changes 15j's assumptions (API names, settings keys), edit `prompts/MM3_phase-15j-ask-ai-agent.md`.

Then the standard close-out checklist.
