# Phase 03: Data Model & Markdown Round-Trip

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 02 · **Branch:** `phase-03-data-model-markdown`

## Read first
`CLAUDE.md`, `prompts/MM3_shared-instructions.md`, and `docs/MM3_SPECIFICATION.md` §3 (edge cases), §5, §9, §13 (risks), §15.2 (R9–R13) and §15.3 (S4), plus Appendix B.

## Goal
A pure-Python, exhaustively tested core that represents meetings and **writes and parses** Obsidian notes and companion transcripts losslessly. It replaces only marker-delimited sections and preserves everything the user wrote outside them. Every later phase depends on this being correct.

## Tasks
1. **`domain/`** (pydantic v2 models, no I/O):
   - `Word(start, end, text, score?)`, `Segment(id, start, end, speaker_label, text, words[])`, `Transcript(segments, language, duration, model, diarized: bool)`.
   - `SpeakerMap(label → display name)`, with `apply(transcript)` returning a copy with names resolved; unmapped labels are shown as "Speaker 1", "Speaker 2" and so on.
   - `MeetingMeta(id: UUID, title, date: datetime, participants, tags, location, template_id, backend, model, generated_at, audio_ref?)`.
   - `Section(id, title, body_markdown)` and `Note(meta, header_markdown, sections: list[Section], preamble, interstitial_text, trailing_text)`. Model the document as an ordered sequence of `Text | Section` nodes so that user content between sections is preserved exactly.
2. **`markdown/frontmatter.py`:** read and write YAML frontmatter. Preserve **unknown keys and their order** (the user may add Obsidian properties). The keys are those in spec §5 plus R9. Datetimes are ISO-8601. Wikilink values are quoted.
3. **`markdown/sections.py`:** marker grammar `<!-- mm3:section:<id> -->` … `<!-- /mm3:section:<id> -->`, where ids match `[a-z0-9][a-z0-9-]*`. The parser is strict per R11: it detects missing, duplicate, mis-nested or mismatched markers and returns structured `MarkerError`s, without guessing. Operations: `replace_section(doc, id, new_body)`, `append_section(doc, section)` and `list_sections(doc)`. Content outside markers must be byte-identical after any operation.
4. **`markdown/note_writer.py` / `note_parser.py`:** render a full note (frontmatter, H1 title, Appendix B header block, sections, with AI Recommendations always last), and parse it back. **Round-trip property:** `parse(render(note)) == note`, and for any user-edited file, `render(parse(text)) == text` when nothing was changed.
5. **`markdown/transcript_writer.py` / `transcript_parser.py`:** companion transcript format. The frontmatter is R9's companion keys. The body has one block per speaker turn: `**[00:01:23] Alice:** text`. Merge consecutive same-speaker segments. Embed machine data losslessly so that re-open can recover segments with timings: either an HTML comment per turn `<!-- mm3:seg id=… start=… end=… label=SPEAKER_00 -->`, or a fenced data block at the end. Choose one, justify it in an ADR, and keep the file pleasant to read in Obsidian. Renaming speakers rewrites names but keeps labels.
6. **`vault/`:**
   - `naming.py`: R13 sanitisation, the `YYYY-MM-DD - Title.md` and `.transcript.md` names, collision suffixes.
   - `paths.py`: resolve the output folder (with `{yyyy}`/`{mm}` placeholders), **confine to the vault root** (resolve symlinks; reject escape), and create folders.
   - `io.py`: atomic write (temp file in the same dir, fsync, `os.replace`); never overwrite an existing note unless `overwrite=True` is passed explicitly.
   - `archive.py`: R12 archive paths and writing.
7. **`markdown/diff.py`:** a unified diff and a structured side-by-side diff (line pairs with change type) between two section bodies, using `difflib` (no new dependency) and ready for the UI in Phase 11.
8. **Filename-parser helper** (spec §3, step 2): `parse_filename(name) → (date?, title?)` for common recorder patterns (`2026-10-11 Product Sync.m4a`, `20261011_143000.wav`, `Zoom_Recording_2026-10-11...`), tested with examples.

## Tests (aim for ≥ 95% coverage of `domain/`, `markdown/` and `vault/`)
- Hypothesis property tests for round-trips, including notes with arbitrary user text before, between and after sections, unicode, CRLF input (normalise or preserve; decide and document), and empty sections.
- Golden-file tests in `tests/fixtures/notes/`: a sample note and companion transcript that open cleanly in Obsidian. Check manually against Nick's vault conventions by viewing one in Obsidian if possible.
- Marker-error cases (each R11 failure mode).
- Path-escape attempts (`../`, absolute paths, a symlink pointing outside the vault) are rejected. Collisions get suffixes. Atomic write leaves no temp files behind on success or failure.

## Out of scope
Persistence (SQLite), LLM calls, UI.

## Acceptance criteria
- The round-trip properties hold under hypothesis (≥ 500 examples).
- A manual edit outside markers survives `replace_section`, byte-for-byte.
- A sample note and transcript pair are committed as fixtures and documented.

## Phase-specific docs
`docs/dev-guide/note-format.md` is the **normative** description of the note and transcript format: frontmatter keys, markers, archive and naming. Later phases and future parsers depend on it. Add ADRs for the transcript data-embedding choice and the line-ending policy. Update ARCHITECTURE. Then the standard close-out checklist.
