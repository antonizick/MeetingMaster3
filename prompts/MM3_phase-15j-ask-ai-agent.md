# Phase 15j: Ask AI agent (questions answered from your meetings)

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 15i · **Branch:** `phase-15j-ask-ai-agent` · **Worktree:** `../MeetingMaster3-phase-15j`

Inserted with `/phase-add` after 15h, behind 15i (ADR-0034, ADR-0049). Nick wants to ask broad questions about his
documented meetings and get answers that understand meaning and intent, with counts, people, roles and tables that he
can trust, using a local model, Bedrock or OpenRouter. Phase 15i built the meeting index and the hybrid (meaning +
words) search. This phase builds the agent on top of it: it plans searches, reads the meetings that matter, and writes
an answer whose facts (which meetings, dates, attendees, how many) come from the files, not from the model's memory.
Every answer is kept as a linked note in the vault and on an **Ask** page in MeetingMaster3.

## Read first
- `CLAUDE.md`, `prompts/MM3_shared-instructions.md`, `docs/MM3_SPECIFICATION.md` §8, §9 and §15 (R6 map-reduce, R22,
  R28 rename, **R30** from 15i; S1-S6).
- **The Phase 15i Phase Log entry and ADR-0049** (including "Phase 15i implementation"): the search API
  (`search.query`, `group_by_meeting`, `meeting_facts`), settings keys, index skip rules, measured relevance. Re-read
  them: they override the names below if 15i changed them.
- ADR-0016/0017 (map-reduce, prompt layout, small-model aids), ADR-0029 (model checks), ADR-0038 (long tasks with
  ETA), ADR-0042 (capable-model picker), ADR-0045 (Bedrock/OpenRouter reasoning switches), ADR-0040 (rename rewrites
  links in other vault notes).

## Nick's request (verbatim intent, 2026-10-22 13:32 CDT)
"I want to add a feature called 'Ask AI agent' where the user can ask broad questions and the AI agent will use the
meeting notes and transcripts on file to answer the question. For example: "How many times have we discussed "X"
topic, Who was principally in those discussions and what was their role? Also, create a table of all of the meetings
and all of the dates and all of the attendees that have participated in discussions about this topic""

During intake: "What I gave you was an example question only (To be fair, which is probably somewhat typical). What
I'm looking for is the user to be able to add broad questions about meetings that are documented and using a RAG style
Capability have the AI answer questions. I would want the AI to be able to derive meaning and intent and not be only a
simple word search […] Ideally, we would be able to use local models or bedrock or open router to support this
capability." On consent: "implement the same cloud consent model that we already have in other parts of the program
where the user either has to explicitly consent for each [question] or there could be a sticky setting in the settings
that acts as a permanent consent for this feature." On answers: "the answers are retained and linkable from both the
meeting master UI as well as between the Obsidian documents so that the user can easily find and click into these
answers from either environment."

## Decisions already made (ADR-0049)
- **Agent shape:** a fixed, testable pipeline driven by the model's JSON output (plan searches → hybrid retrieval →
  read each candidate meeting → optional follow-up searches → answer), **not** native tool-calling (none of the three
  adapters has it, and small local models are unreliable with it). Works with local Ollama, Bedrock and
  OpenAI-compatible/OpenRouter through the existing `generate()`.
- **Facts are computed by code:** which meetings are relevant (the model judges relevance per meeting; code counts),
  their dates, titles, links and attendees (frontmatter `participants`, `mm3-speakers`, speakers in the matching
  passages) come from the files. The model writes the narrative, roles and contributions, citing meetings it was shown;
  citations to anything else are removed.
- **Consent (S6):** a question sent to a cloud backend needs a consent box ticked for that question, **unless** the
  backend's separate sticky Settings switch "Always allow Ask AI agent to send meeting excerpts to this backend"
  (`ask_consent_remembered`, new, off by default) is on. Note writing's `consent_remembered` does **not** cover Ask.
  Local backends never ask.
- **Every answer is saved automatically** as a vault note (default folder `MM3 Answers/`) with `[[links]]` to the
  meetings it used, and listed on the Ask page; it can be opened, re-asked and deleted from MeetingMaster3. Meeting
  notes are **not** edited: Obsidian's backlinks show the answers from each meeting, and the review page lists them.

## Goal
On a new **Ask** page, Nick types a broad question about his meetings (for example the "how many times did we discuss
X, who led it, in what role, and a table of the meetings, dates and attendees" question), picks a backend and model
(local by default), watches progress, and gets a cited answer with a code-built table, saved as a note in
`MM3 Answers/` that links to every meeting it used; the answer is reachable from the Ask page's history, from each cited
meeting's review page, and from Obsidian (backlinks and the answers folder).

## What exists (verified 2026-10-22 13:44 CDT, before 15i; re-check after 15i)
- No question answering anywhere; 15i adds `src/meetingmaster3/search/` (index, hybrid query, `meeting_facts`), the
  `search` settings, the Search page and `mm3 search`.
- LLM: `llm/base.py:GenerateRequest`/`GenerateResult` (messages, `max_tokens`, `temperature`, `usage`), `stream()`;
  `llm/budget.py` (`estimate_tokens`, `usable_tokens`, `window_for`, `fits_window`); local models plan for
  `generation.max_context` (16 384) tokens; reasoning switches per backend (ADR-0045); the capable-model picker
  (`templates/picker.py`, `settings/_model_picker.html`, `templates/model_check.py:assess`, ADR-0042) and cost estimate
  (`llm/cost.py`).
- Consent: `llm/consent.py:enforce_consent(backend, cloud_consent=, remembered=)`; `BackendConfig.consent_remembered`
  (`config/settings.py`) with its checkbox in `settings/_backend_form.html`; review actions pass `cloud_consent` in the
  request body (`web/review.py:RegenerateBody`).
- Long tasks: `review/progress.py:TaskRegistry`/`LongTask` (start, poll, cancel, steps, smoothed ETA; in memory).
- Vault writes: `vault/io.py:atomic_write_text` (never overwrite unless asked), `vault/naming.py:sanitize_title`,
  `with_counter`, `vault/paths.py` confinement. Frontmatter helpers in `markdown/frontmatter.py`. Vault scanners
  (`vault/picker.py:read_identity`, `vault/relink.py`, `vault/links.py` rename link rewriting) key on `mm3-id` and
  `mm3-kind`; an answer note must not look like a meeting (no `mm3-id`).
- Review page: `web/review.py`, `templates/review.html` (`/meetings/{mm3-id}`); navigation tuples in `web/pages.py`.
- Notes from `default-notes` have a **Meeting Context** section (purpose and each person's stated role) and
  **Discussion by Topic**; older templates differ, so roles must also be inferred from transcript passages.

## Tasks
1. **Answer pipeline** (`src/meetingmaster3/ask/`, pure logic separated from I/O): (a) **Plan**: one call that turns
   the question into JSON: 2-6 search queries (paraphrases, synonyms, named entities), optional date range and people
   filters, and what the user wants (count, people/roles, table, timeline, summary). Validate the JSON; one repair
   retry; fall back to the raw question. (b) **Retrieve** with 15i's hybrid search for every query, merged by meeting,
   capped at `ask.max_meetings` (default 25, setting) with the reason when capped. (c) **Read** each candidate meeting
   in one call (map step): the question, the meeting's header facts and its matching passages with neighbours and
   timestamps (plus the note's Meeting Context section when present), fitted to the model's window with the budget
   helpers. Returns JSON: `relevant` (yes/partly/no), a 1-3 sentence finding, people involved with role and
   contribution, and 0-3 supporting quotes with times. (d) **Follow up**: if few meetings are relevant, allow at most
   one more planning round with the findings so far (bounded; recorded in the answer's trace). (e) **Facts** by code:
   relevant meetings (count), table rows (date, meeting link, attendees, people who spoke on the topic, their stated
   role where known), sorted by date. (f) **Answer**: one call with the question, the per-meeting findings and the
   facts; Markdown answer that cites meetings as `[[note stem]]` (only stems it was given; others are stripped and the
   strip is recorded), followed by the code-rendered table and a Sources list. Temperatures per R6 (0.2 extraction,
   0.4 narrative). Fits qwen3:8b at 16 384 (map calls per meeting; the answer call gets findings, never raw
   transcripts). Reasoning off per ADR-0045. A question with no relevant meetings gets an honest "no meetings found"
   answer listing what was searched.
2. **Settings and consent.** `ask` settings section (pydantic, documented): `default_backend`/`default_model` (default:
   the note-generation default), `max_meetings`, `answers_subfolder` (`MM3 Answers/`), `keep_history` (on). New
   `BackendConfig.ask_consent_remembered` with its own checkbox in the backend form ("Always allow Ask AI agent to send
   meeting excerpts to this backend"). `enforce_consent(..., remembered=cfg.ask_consent_remembered)` before **any**
   cloud call of a run (the plan call included); the request carries `cloud_consent` for a single question. The Ask
   page states, before sending, that excerpts from up to `max_meetings` meetings go to `<provider>` and shows the
   15h cost estimate where a price is known. Embedding the question uses 15i's embedder and its own consent.
3. **Answer notes in the vault.** Each finished answer is written atomically to
   `<vault>/<answers_subfolder>/YYYY-MM-DD HHMM - <sanitised short question>.md` (R13 sanitising, counter on
   collision, S4 confinement; never overwrite). Frontmatter: `mm3-kind: answer`, `mm3-answer-id` (UUID), `question`,
   `asked` (timestamp), `mm3-backend`, `mm3-model`, `mm3-sources` (wikilinks to the meeting notes), `tags:
   [mm3/answer]`; **no `mm3-id`**, so the meeting scanners, picker, relink, upgrade and the search index ignore it
   (verify each; 15i skips `mm3-kind: answer`). Body: the question, the answer, the table, Sources (one line per
   meeting: `[[note stem]]`, date, why it was relevant, transcript moments as MeetingMaster3 links), and a short
   "How this was answered" trace (queries, meetings read, model, time). Renaming a meeting (R28) already rewrites
   wikilinks in other notes, so citations stay valid: add a test.
4. **History store.** An `answers` table in `mm3.db` (migration v5 or next): answer id, question, asked time, backend,
   model, vault path, cited `mm3_id`s, status, duration, token usage. The Ask page lists history newest first (paged,
   like Meetings), each linking to the answer view and offering **Open in Obsidian** (`obsidian://open?vault=…&file=…`,
   built from the vault folder name; verify on Nick's machine) and **Delete** (confirm; deletes the vault note and the
   row). A note deleted or moved in Obsidian shows "file not found" with **Forget** (re-found by `mm3-answer-id` like
   ADR-0047 when possible).
5. **Ask page** (`/ask`, in the navigation): question box, backend/model picker (15h's capable picker; local default),
   optional date range and people filters, consent box for cloud backends (hidden when `ask_consent_remembered`), and
   the run as a long task: steps ("Planning searches", "Reading meeting 4 of 12: <title>", "Writing the answer"),
   elapsed time, ETA, Cancel. The answer view (`/ask/{answer-id}`) renders the saved note server-side, sanitised (S3),
   with meeting links going to `/meetings/{mm3-id}` (and the moment for quotes), plus **Ask again** (same question,
   current index) and **Ask a follow-up** (new question, the previous answer's question and findings as context, kept
   in the trace). Keyboard accessible, CSP-clean, HTMX.
6. **Links from meetings.** The review page shows "Answers that cite this meeting" (from the `answers` table) linking
   to each answer view. Do not edit meeting notes (ADR-0012); Obsidian's backlinks pane covers the vault side.
7. **CLI.** `mm3 ask "<question>" [--backend --model --from --to --allow-cloud] [--no-save] [--json]`: prints the
   answer and the saved note's path; `--allow-cloud` is the per-question consent; without it a cloud backend whose
   `ask_consent_remembered` is off is refused.
8. **Evaluation.** A synthetic corpus (extend 15i's fixture vault: about 8 meetings, one topic across 3 meetings in
   different words with different people and roles, decoys that share words but not the topic) and 4-6 questions with
   expected answers (relevant meeting set, count, people, attendees table). An eval script (in `tests/eval/`, like
   `run_eval.py`) scores recall/precision of the meeting set, count correctness, table correctness and citation
   validity. Run it with local `qwen3:8b` and, if Nick's keys are configured, Haiku 5.5 on Bedrock and OpenRouter
   (cost per question measured; stop and ask Nick before spending more than about USD 2). Run Nick's example question
   privately on his real vault (`~/.local/share/meetingmaster3/private-eval-15j/`, deleted at close-out) and show him
   the answer. Record aggregate numbers in `docs/PERFORMANCE.md` (time per question by backend and number of meetings).

## Out of scope
- Native tool-calling, autonomous multi-step agents beyond the bounded follow-up round, web search, actions that
  change meetings.
- Answering from non-MM3 vault notes; chat-style multi-turn sessions beyond "Ask a follow-up".
- Index or embedding changes (15i) except fixes needed for this phase (recorded as deviations).

## Tests
- Unit (fake backend): plan JSON parsing, repair and fallback; retrieval merge and cap; the map call fits the window
  (budget) for long meetings; relevance counting and the code-built table (dates, attendees, sorting, speakers from
  `mm3-speakers`); citation stripping; "no meetings found"; follow-up bound; consent: cloud refused without the box or
  `ask_consent_remembered`, and `consent_remembered` alone does **not** allow it, and nothing is sent when refused
  (assert the fake saw no call); answer note writing (frontmatter, name sanitising, collision counter, confinement,
  never overwrite); scanners and the search index ignore answer notes; rename keeps citations valid; history CRUD and
  "file not found".
- Web: Ask page, consent box visibility, task progress and cancel, answer view sanitising, review page "Answers that
  cite this meeting", delete with CSRF.
- e2e (Chromium): ask a question against the fixture vault with a fake backend, see the answer and table, open a cited
  meeting, return to the answer from the meeting's review page.
- Eval (Task 8) marked `models`/`network` as appropriate; `uv run pytest`, `ruff check`, `ruff format --check`,
  `mypy src`; `mypy src tests` no worse than `main`.

## Acceptance criteria
- In the real app with Nick's vault and local qwen3:8b, Nick's example question (with a topic he picks) returns a
  correct count, the principal people with roles, and a table of meetings, dates and attendees whose rows match the
  files; every cited meeting link opens the meeting.
- The same works with Bedrock (and OpenRouter if keyed) after consent; with neither the box nor the sticky Ask switch,
  nothing is sent.
- The answer appears as a note in `MM3 Answers/` that links to the meetings (and shows in their Obsidian backlinks),
  on the Ask page history, and on each cited meeting's review page; deleting it from MeetingMaster3 removes both.
- A question phrased with different words than the notes still finds the meetings (meaning, not only words).

## Phase-specific docs
- ADR-0049: append "Phase 15j implementation" (pipeline prompts and JSON schemas, budgets, citation rule, answer note
  format, eval results); new ADRs for further choices. Spec §15: add **R31** (Ask AI agent) and extend S6 with the Ask
  consent switch.
- `docs/user-guide/search-and-ask.md` (complete it: how to ask good questions, what is sent where, where answers are
  kept, how to delete them), `configuration.md`, `settings.md`, `docs/MM3_ARCHITECTURE.md`, `docs/PRIVACY.md`,
  `docs/THREAT_MODEL.md` (prompt injection from meeting text into the agent: the agent only reads and writes an answer
  note, never acts; citations validated), `docs/PERFORMANCE.md`, README feature list and a screenshot of the Ask page
  (`docs/assets/`, e2e screenshot mechanism with a fake backend).
- `prompts/MM3_phase-16-release.md`: add the Ask and Search pages to the screenshot list if 15j changes anything
  planned there.

Then the standard close-out checklist.
