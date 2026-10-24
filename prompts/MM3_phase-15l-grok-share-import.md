# Phase 15l: Import a Grok conversation from its share link

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 15k · **Branch:** `phase-15l-grok-share-import` · **Worktree:** `../MeetingMaster3-phase-15l`

Inserted with `/phase-add` after 15j, behind 15k (ADR-0034, ADR-0052). Phase 15k lets Nick import an AI conversation
from an exported Markdown file. His preferred workflow is quicker: copy the **share link** Grok gives him
(`https://x.com/i/grok/share/…`) and paste it into MeetingMaster3. A share link is also better data than the Markdown
export: it carries who said each message and when, so speakers are exact and `[mm:ss]` references work. This phase
adds a share-link importer for Grok only, behind 15k's parser interface. It is the app's first feature that fetches
content from a third-party website, so the fetch is tightly confined. It can run in parallel with **15m**.

## Read first
- `CLAUDE.md`, `prompts/MM3_shared-instructions.md`, `docs/MM3_SPECIFICATION.md` §15 (**R32** from 15k, S1-S6).
- **ADR-0052** including "Phase 15k implementation", and the **Phase 15k Phase Log entry**: the `importing` package,
  `detect_and_parse`, `ImportedConversation`/`ImportedTurn`, the import job type and API, the untimed rule, the
  prefix-collapsing helper. They override the names below if 15k changed them.
- `docs/dev-guide/importing.md` (15k), `docs/THREAT_MODEL.md`, `docs/PRIVACY.md`, ADR-0009 (httpx adapters),
  ADR-0028 (security hardening).

## Nick's request (verbatim intent, 2026-10-24 11:20 CDT)
"I want to add a feature that will allow me to start the workflow by importing a transcript or a export from an AI
conversation (Rather than starting the workflow only from an audio sound file)."

During intake, about his example (`privacy project brainstorming.md`, also at an `x.com/i/grok/share/…` link): "It
would be greatly preferred if you and MeetingMaster3 workflow can use the URL from x.com as that makes my workflow
much much easier, but uploading an MD file With transcripts or notes should also be an option for the user." He chose
**Grok links only** for now.

## Decisions already made (ADR-0052)
- **Grok share links only**, fetched **only when the user pastes one** and starts the import. Accepted forms:
  `https://x.com/i/grok/share/<id>`, `https://twitter.com/i/grok/share/<id>`, `https://grok.com/share/<id>` (with or
  without query strings, which are dropped). Anything else is refused with a hint to export Markdown instead. Other
  providers (ChatGPT, Claude) are follow-ups, not this phase.
- **Fixed host allowlist, no generic URL fetcher** (no SSRF surface): the app builds the request URL itself from the
  validated share id; it never follows a redirect to another host.
- The endpoint is **undocumented** and may change or disappear. When it fails, the import fails with a clear
  `MM3Error` that says so and points to the Markdown upload. The terms-of-service position (a single request for a
  conversation the user shared publicly, like opening it in a browser) is recorded in ADR-0052; the fetcher must not
  log in, send cookies, crawl, or fetch anything but the one share.
- **Private data.** Nick's example share is used only for the local check; never commit its id, URL, response or
  content. Committed fixtures are synthetic JSON in the same shape.

## Goal
Nick pastes a Grok share link on the New meeting page (Import), MM3 fetches the conversation, shows the 15k preview
with every turn already attributed correctly and timed from the conversation's start, he names the speakers, picks a
template and gets a note, with `[mm:ss]` references that match the conversation's real timing.

## What exists (verified 2026-10-24 11:39 CDT; re-check before relying on it)
- **The share endpoint (checked by hand during planning, unauthenticated, no cookies):** `GET
  https://grok.com/rest/app-chat/share_links/<id>` returned `200` JSON (about 135 KB for a 35-minute voice chat):
  - top level: `responses` (list), `conversation` (`conversationId`, `title`, `createTime`, `modifyTime`,
    `mediaTypes` such as `["audio"]` for voice mode, …), `isPublic`, `allowIndexing`, and other keys to ignore;
  - each response: `responseId`, `parentResponseId`, `sender` (`"human"` | `"assistant"`), `message` (Markdown text),
    `createTime` (ISO 8601, UTC, milliseconds), `partial` (bool), `model`, plus many empty attachment/search fields.
  - The example had 107 responses (63 human, 44 assistant), one root, **no branches**, none partial. Even here the
    voice-mode **human messages repeat as growing prefixes** (18 of them are prefixes of the next), so 15k's prefix
    collapsing applies.
  - The share id seen has the form `bGVnYWN5LWNvcHk_<uuid>` (a base64 prefix, `_`, a UUID). Treat the id as opaque:
    validate it as `[A-Za-z0-9_-]{8,200}`.
  - The `x.com/i/grok/share/<id>` page itself is a JavaScript shell: its HTML does not contain the messages'
    timestamps, so do not scrape HTML.
- **15k's interface** (as built, 2026-10-24; `docs/dev-guide/importing.md`): `importing.detect_and_parse(data,
  filename, *, max_bytes)` and the registry `importing.detect.PARSERS` (id → `parse(text, filename)`, plus
  `model.FORMAT_NAMES` for the UI name); `ImportedConversation(turns, title, started_at, source_format, warnings)` with
  `ImportedTurn(speaker, role, text, start, end, confidence, words)`; `importing.chat.collapse_prefixes` /
  `is_growing_prefix` for growing human prefixes; `importing.convert.to_transcript`. The **separate route
  `POST /api/imports`** (not `options.job_type` on `/api/jobs`) parses the upload before creating the job; job type
  `import` with stages `import_parse` → `await_speaker_confirmation` (`ImportConfirmationStage`, question kind
  `import_confirmation`, preview `import.json`) → `generate` → `write`. The upload is stored as **`source.<ext>`**
  (never `original.*`, which the retention code treats as audio). Untimed rule: `Transcript.timed`. CLI
  `mm3 import <file> [--speaker user=… --speaker assistant=… --yes]`.
- **HTTP:** `httpx` is a dependency (LLM adapters, `llm/_http.py` has bounded retries and error normalisation). The
  app is localhost-only (S1); outbound requests so far go only to configured LLM backends.

## Tasks
1. **Link parsing** (`importing/grok_share.py`): `parse_share_url(text) -> str` (the id) for the accepted forms,
   trimming whitespace and angle brackets; refuse other hosts, `http://`, user-info, ports, other paths
   (`E_IMPORT_URL_UNSUPPORTED` with the Markdown hint). Unit-test hostile inputs (`grok.com.evil.com`, `@`, IDN
   look-alikes, `..`, encoded slashes, very long ids).
2. **Fetch** (`importing/fetch.py`): one `httpx` GET to the fixed endpoint built from the id, HTTPS only, certificate
   verification on, no cookies, `follow_redirects=False` (a redirect is an error), timeout about 20 s, a response cap of
   `importing.max_mb` read as a stream, `Accept: application/json`, a plain `User-Agent` naming MeetingMaster3. Map
   404/403/410 to "this link is not shared publicly, or was deleted", other status codes and non-JSON answers to "Grok
   changed or is unavailable; export the conversation to Markdown and upload it". Respect a configured HTTPS proxy
   (`HTTPS_PROXY`) as httpx does. No retries on 4xx; one retry on 5xx/timeouts.
3. **Parse** (`grok-share` parser behind 15k's interface): validate the JSON with a pydantic model that ignores
   unknown keys; rebuild the thread from `parentResponseId` (with branches, follow the **latest** child at each step,
   and warn that alternatives were skipped); drop `partial` responses and empty messages; roles from `sender`; times
   = `createTime` minus the first message's `createTime` (so the transcript is timed); collapse growing human
   prefixes (keep the **last** message's time for the merged turn, or the first; pick and justify); title from
   `conversation.title` (generic titles like "Discussion Request" fall back to the first user sentence, shortened);
   date from `conversation.createTime` in the user's local time zone; assistant name "Grok". Keep Markdown in
   messages; strip nothing else.
4. **Job and API.** `POST /api/imports` accepts either a file or `options.share_url` (validate the link before the
   job is created, as 15k does for files); the fetch happens in the `import_parse` stage (so it shows progress, can be
   cancelled and resumed), and the fetched JSON is stored as the job's source (`source.json`, never `original.*`) so a
   resume does not fetch again. `mm3 import <url>` works too.
5. **UI.** The Import choice on New meeting gets a **Paste a Grok share link** field next to the file input (one or
   the other), with a one-line note that MeetingMaster3 will download that conversation from grok.com. The confirmation
   preview shows times. Errors from Tasks 1-2 appear inline with their hint.
6. **Privacy and docs of the egress.** This is the first non-LLM outbound request: `docs/PRIVACY.md` (what is sent:
   the share id, your IP and the user agent; nothing about your vault), `docs/THREAT_MODEL.md` (SSRF ruled out by the
   fixed host; hostile JSON; size; prompt injection in imported text), `SECURITY.md` if it lists outbound traffic,
   and the offline/Docker notes (the container needs outbound HTTPS for this feature only).
7. **Private check.** With Nick's example link, fetch, preview, and write a note with local `qwen3:8b` and Default
   Notes. Compare the turn count and roles with his Markdown export processed by 15k (the share link should need no
   fixes). Keep artefacts in `~/.local/share/meetingmaster3/private-eval-15l/`, deleted at close-out.

## Out of scope
- ChatGPT, Claude, Gemini or any other share links; logging in to any service; fetching attachments, images or cited
  web pages; a browser extension; generic URL import.

## Tests
- Unit: URL parsing (accepted forms and hostile inputs); the fetch with `respx` (200, 3xx refused, 403/404/410, 5xx
  retry once, timeout, oversize stream, non-JSON, wrong JSON shape); the parser on synthetic share JSON in
  `tests/fixtures/imports/grok-share-*.json` (CC0, written for this phase: linear, branched, partial and empty
  messages, growing prefixes, unicode); times relative to the first message; title fallback.
- Jobs: import from a URL end to end with a faked fetch; resume after the fetch does not fetch again; cancel during
  the fetch.
- Web: the link field, inline errors, CSRF; e2e with a faked fetch.
- A `network`-marked test that fetches a **synthetic share Nick creates for testing** only if he provides one in
  `MM3_TEST_GROK_SHARE` (skipped otherwise; never his real conversations).
- `uv run pytest`, `ruff check`, `ruff format --check`, `mypy src`.

## Acceptance criteria
- In the real app, pasting Nick's example `x.com/i/grok/share/…` link produces the preview with correct speakers on
  every turn (no fixes needed) and times from the conversation, and a note with valid `[mm:ss]` references.
- A `grok.com/share/…` link works the same; a ChatGPT link, a random URL and an `http://` link are refused with the
  Markdown hint, and no request is made for them (asserted in tests).
- With the network off, the error says so and the file upload still works.

## Phase-specific docs
- ADR-0052: append "Phase 15l implementation" (endpoint, JSON fields used, branch rule, prefix rule, timing rule,
  failure messages, ToS note). Spec §15: extend **R32** with share links and S6 or a new S-item for the fetch.
- `docs/user-guide/importing.md` (how to get a Grok share link, what is downloaded, what to do when it fails),
  `docs/dev-guide/importing.md`, `docs/PRIVACY.md`, `docs/THREAT_MODEL.md`, `configuration.md` if settings were added,
  README feature list, `CHANGELOG.md`.

Then the standard close-out checklist.
