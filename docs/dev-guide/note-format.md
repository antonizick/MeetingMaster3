# Note and Transcript Format (normative)

> **Status:** normative since Phase 03 (format version 1). Code that reads or writes MM3 files
> must follow this page; if the code and this page disagree, that is a bug in one of them.
> Implementation: `src/meetingmaster3/markdown/` and `src/meetingmaster3/vault/`.
> Decisions: ADR-0010 (transcript data block), ADR-0011 (line endings), ADR-0012 (round-trip
> rules). Spec: §5, §9, §15.2 R9–R13 and R18.

MeetingMaster3 writes two plain Markdown files per meeting into the vault: the **note** and its
**companion transcript**. Both are ordinary Obsidian notes: there is no lock-in, and everything
MM3 needs to re-open, regenerate or rename lives in the files themselves.

## 1. File names and folders
| File | Name |
|---|---|
| Note | `YYYY-MM-DD - <Title>.md` |
| Companion transcript | `YYYY-MM-DD - <Title>.transcript.md` |
| Section archive | `Archive/YYYY-MM-DD - <Title>.<section-id>.YYYYMMDD-HHMM.md` |
| Whole-note archive | `Archive/YYYY-MM-DD - <Title>.YYYYMMDD-HHMM.md` |

* The folder is `vault.output_subfolder` with `{yyyy}`, `{mm}` and `{dd}` filled from the meeting
  date (default `Meetings/{yyyy}/`); any other `{...}` placeholder is an error. `Archive/` sits
  inside that folder.
* **Title sanitising (R13):** Unicode NFC; the characters `* " \ / < > : | ? # ^ [ ]`, control
  characters and line/paragraph separators become spaces; zero-width and bidi-override characters
  (Unicode category Cf) are removed; whitespace runs collapse to one space; leading and trailing
  dots and spaces are stripped; the result is cut to **150 UTF-8 bytes** on a character boundary.
  An empty result becomes `Untitled meeting`.
* **Collisions:** the note and its companion share one *stem*. MM3 picks the first of `stem`,
  `stem (2)`, `stem (3)`, ... for which **neither** file exists. Archive names collide the same
  way (`... .20261011-1430 (2).md`). Nothing is ever overwritten silently.
* **Links:** the note links to `[[<stem>.transcript]]` and the companion to `[[<stem>]]`.
* **Renaming a meeting (R28, ADR-0040)** changes the stem of every file of the meeting at once: note,
  companion, readable transcript (regenerated), archives (same stamps and suffixes, e.g.
  `<new stem>.20261012-1240.md`, with `mm3-archived-from`/`mm3-transcript`/`mm3-audio` re-pointed and the
  body kept), and the vault audio copy (`<new stem>.opus`). In the note it rewrites `title`, `date` (keeping
  its YAML shape), `mm3-transcript`, `mm3-audio`, the H1, the `Date & Time` header line and the link in the
  `Transcript` header line, each only if it is still what MM3 wrote. In the companion it rewrites `mm3-note`
  and `# Transcript: <title>`. Every other byte is kept (§3.6), including in the data block, and so are links
  to the meeting in other vault notes (rewritten in place, target only). `mm3-id` never changes. The files
  move to the new date's output folder only if the note was in the old date's output folder.

## 2. Encoding and line endings
* UTF-8. A leading BOM is tolerated and preserved on re-write; MM3 never adds one.
* **Line endings are preserved (ADR-0011).** A file's style is decided by its first line break
  (`\r\n` → CRLF, otherwise LF). Text MM3 did not change keeps its exact bytes, including mixed
  endings. Content MM3 writes (a regenerated section, a re-emitted property) uses the file's
  style. New files are LF.
* Lines are split on `\n` only. Other Unicode line separators (`U+2028`, `U+0085`, ...) are
  ordinary characters.

## 3. Frontmatter
A YAML block that starts on the first line with `---` and ends at the next line that is exactly
`---` (trailing spaces allowed). It must be a mapping with text keys.

### 3.1 Note properties (in the order MM3 writes them)
| Key | Value | Written |
|---|---|---|
| `title` | text | always |
| `date` | ISO-8601 datetime, e.g. `2026-10-11T14:00:00` | when known |
| `participants` | list of names | always (may be `[]`) |
| `tags` | list of tags, without `#` and without spaces | always (may be `[]`) |
| `location` | text | when set |
| `mm3-version` | integer format version (currently `1`) | always |
| `mm3-id` | UUIDv4 linking the note to app data | always (**required** to be an MM3 note) |
| `mm3-template` | template id | when set |
| `mm3-transcript` | wikilink `"[[<stem>.transcript]]"` | when a companion exists |
| `mm3-speakers` | mapping `SPEAKER_xx: Name` (confirmed names only) | when any |
| `mm3-generated` | ISO-8601 datetime | when generated |
| `mm3-backend`, `mm3-model` | provenance text | when set |
| `mm3-audio` | wikilink to an audio copy in the vault (R8, opt-in) | when set |
| `mm3-source`, `mm3-source-format` | `import` and the parser id (`chat-unlabelled`, `timestamped-text`…) | on an imported meeting (R32) |

`mm3-source` and `mm3-source-format` are written after MM3's own keys and kept like user properties, so every later rewrite (regeneration, template switch, rename) keeps them; they are also written on the imported meeting's companion. Any other key is a **user property**: MM3 keeps it, its value and its position.

### 3.2 Companion transcript properties
| Key | Value |
|---|---|
| `mm3-version` | `1` |
| `mm3-id` | same UUID as the note (**required**) |
| `mm3-note` | wikilink `"[[<stem>]]"` |
| `mm3-speakers` | mapping `SPEAKER_xx: Name` (confirmed names only) |
| `duration` | `H:MM:SS` text (display copy) |
| `language` | language code (display copy) |
| `mm3-transcription-model` | model id (display copy) |
| `mm3-diarized` | `true` / `false` (display copy) |

An imported meeting's companion has no `mm3-transcription-model` (there was no transcription), and an untimed one has no `duration`. The "display copy" values are derived from the data block (§6), which is authoritative.

### 3.3 Archive properties
Archives carry `mm3-archived` (ISO-8601 datetime) and `mm3-archived-from` (wikilink to the note).
Section archives also have `mm3-archived-section` and `mm3-archived-id` and **no `mm3-id`**, so
they are never mistaken for live notes. A whole-note archive is the original file with only the two
archive properties added. **Pickers that list MM3 notes must skip files with `mm3-archived`.**

### 3.4 Value style
* Lists are flow style: `tags: [meeting, product]` (the vault's convention and spec §5).
* Strings are plain unless they would be read as something else; then they are double-quoted with
  JSON-style escapes. Wikilinks are always double-quoted. Strings that YAML 1.1 (PyYAML) **or**
  YAML 1.2 (Obsidian) would read as numbers, booleans or null are quoted, e.g. `"yes"`, `"0o17"`.
* Datetimes and dates are unquoted ISO-8601.
* Every emitted property is re-parsed and must yield the same value; MM3 falls back to other YAML
  styles if needed.

### 3.5 Reading user-edited properties
Parsing is lenient so that edits in Obsidian's Properties view never lock a note:
`participants: Alice, Bob` becomes a list, `tags: a b` splits on commas and spaces, a date
without a time means midnight, wikilink aliases (`[[x|alias]]`) are accepted, and values that
cannot be understood are ignored with a warning (`ParsedNote.warnings`). A missing or invalid
`mm3-id` means "not an MM3 note" (`not_an_mm3_note` / `invalid_mm3_id`).

### 3.6 Re-writing
When MM3 re-writes a file it read, the frontmatter block is reused **verbatim** if no property
changed. Otherwise every unchanged key keeps its original raw text, comments included; changed
keys are re-emitted in place; removed keys disappear; new MM3 keys are inserted after the
preceding MM3 key in the order of §3.1. If the YAML cannot be split per key (flow-style top
level, anchors shared across keys, duplicate keys), the whole block is re-emitted.

## 4. Note body
```markdown
# Product Sync
- **Date & Time:** 2026-10-11 14:00
- **Participants:** Alice Chen, Bob Okafor
- **Tags:** #meeting #product
- **Location / Context:** Zoom

<!-- mm3:section:summary -->
## Summary

The team agreed to ...
<!-- /mm3:section:summary -->

<!-- mm3:section:ai-recommendations -->
## AI Recommendations

- ...
<!-- /mm3:section:ai-recommendations -->
```
* The H1 and the Appendix B header (R10) come straight after the frontmatter and are **outside**
  every section. MM3 renders them from metadata when it creates the note; after that they are user
  text. The header has `Date & Time` (when known; a time of exactly midnight means "time not
  recorded" and is shown as the date alone), `Participants` (`Not recorded` if none), `Tags`
  (when any) and `Location / Context` (when set).
* Sections follow, separated by one blank line. **AI Recommendations (`ai-recommendations`) is
  always last** in a new note, and `append_section` inserts before it.
* Everything outside section markers belongs to the user and is never modified.

## 5. Section markers (R11)
```
<!-- mm3:section:<id> -->
<content>
<!-- /mm3:section:<id> -->
```
* A marker is a whole line: optional spaces or tabs, the comment, optional spaces or tabs.
  Spaces inside the comment around `mm3:section:<id>` are allowed. Anything else on the line makes
  it **malformed**.
* `<id>` matches `[a-z0-9][a-z0-9-]*`, at most 64 characters (`invalid_id` otherwise).
* A line that looks like an attempt at a marker (`<!--` followed by `mm3:section`, any case) but
  does not match the grammar is reported as `malformed`.
* Markers are recognised everywhere, including inside fenced code blocks. Section content written
  by MM3 must never contain marker-like lines; MM3 refuses such content.
* **Content** is everything between the two marker lines. MM3 writes `## <Title>`, a blank line,
  the body (no leading or trailing blank lines) and a final newline. When reading, the first
  non-blank line is the title if it is an ATX heading of any level; the rest is the body.

### 5.1 Validity
A section is **valid** if its id has exactly one open and one close marker, the close marker is the
next marker line after the open one, and no error mentions the id. Errors (`MarkerError.kind`):

| Kind | Meaning |
|---|---|
| `malformed` | looks like a marker but breaks the grammar |
| `invalid_id` | well-formed marker with an invalid id |
| `duplicate` | the id is opened (or closed) more than once |
| `unclosed` | opened, never closed |
| `unexpected_close` | closed, never opened |
| `mismatched` | closes an id that is not open while another section is open |
| `misnested` | opened before the enclosing section was closed (charged to the **outer** section), closed out of order, or overlapping another section |
| `invalid_content` | markers are fine but the content cannot be represented (for example an empty heading followed by another heading) |

A nesting error is charged to the outer section only: an intact pair of markers inside a damaged
section stays valid, because its bytes are unambiguous. This keeps the R11 recovery path working.
An operation on a section that is not valid is **refused** (`section_markers_invalid`, HTTP 409)
with the errors and the R11 options: append a fresh section, or cancel. MM3 never guesses.

### 5.2 Operations (byte guarantees)
* `replace_section(doc, id, body)` rewrites only the bytes between the two marker lines. The
  existing heading line is kept byte-for-byte unless a new title is given.
* `append_section(doc, section)` is a pure insertion: at the end of the document, or immediately
  before a valid `ai-recommendations` section. If the id is already mentioned by any marker, it
  becomes `<id>-2`, `<id>-3`, ...
* Rendering a parsed note with `base=` reuses the original bytes of every unchanged section and of
  all text outside sections, so `render(parse(text), base=parse(text)) == text`.

## 6. Companion transcript body
```markdown
# Transcript: Product Sync

**[00:00:00] Alice Chen:** Okay, let's get started. I think we can ship it on the twentieth.

**[00:00:08] Bob Okafor:** Only if the funnel events are in.

<!-- mm3:transcript-data v1
{"language":"en","duration":2537.4,"model":"large-v3-turbo","diarized":true}
{"id":0,"start":0.84,"end":4.1,"label":"SPEAKER_00","text":" Okay, let's get started.","words":[[0.84,1.2,0.91,"Okay,"]]}
-->
```
* **Readable turns:** consecutive segments with the same label merge into one turn:
  `**[hh:mm:ss] Name:** text`, one blank line between turns. The time is the first segment's start,
  floored. Names come from `mm3-speakers`; unmapped labels are `Speaker N`, numbered by the
  label's natural order among all labels (so renaming one speaker never renumbers another);
  undiarized segments are `Speaker`. An empty transcript shows `_No speech was detected._`.
* **Data block (ADR-0010):** the last `<!-- mm3:transcript-data v1` ... `-->` block in the file.
  The first line is a JSON header (`language`, `duration`, `model`, `diarized`). Each further line
  is one segment: `id`, `start`, `end`, `label` (or `null`), `text` (verbatim, including leading
  spaces) and `words` as `[start, end, score, text]` arrays (`null` where WhisperX gave none).
  JSON is ASCII-only, with `<` and `>` escaped as `<` / `>`, so speech can never end the
  comment early. Floats use the shortest exact representation.
* **Untimed transcripts (R32, Phase 15k):** an imported AI conversation has no times. Its header
  carries `"timed":false` (the key is written **only** then, so timed files stay byte-identical;
  a header without it is timed), every segment has `start = end = 0`, and the readable turns are
  `**Name:** text` without a stamp. Nothing derived from it shows a clock: the readable transcript
  (one paragraph per segment), the text export, the review page (no time buttons, no `data-t`),
  Search passages (`start_s` null, no `#t=` links), the prompt (no `[mm:ss]`, no Length line, a
  "no timestamps" rule) and the generated sections (clock references are removed).
* The data block is the **source of truth** for segments, timings, labels and words. If the
  readable turns no longer match it, `ParsedTranscript.body_matches_data` is `false` and the
  user's text is left alone.
* **Renaming speakers** rewrites `mm3-speakers` and the name in each turn heading, matched to the
  data turn by position; the user's edits to turn text survive and the data block is untouched.
  If turns were added, removed or merged, renaming is refused (`transcript_turns_mismatch`) unless
  the caller asks to re-render from the data.

## 7. Writing to the vault (S4)
* The vault root must exist, be a folder and be writable (`vault_missing`,
  `vault_not_a_directory`, `vault_unwritable`, `vault_not_configured`).
* Every target path is resolved, symlinks included, and must be inside the vault root; absolute
  paths, `~`, NUL bytes, `..` escapes and symlinks that leave the vault are refused
  (`vault_path_escape`).
* Writes are atomic: a temporary `.<name>.<random>.mm3tmp` file in the same folder is written,
  fsynced and moved into place, and the folder is fsynced. Without an explicit `overwrite=True` an
  existing file is never replaced (`vault_file_exists`, HTTP 409); the no-overwrite move uses a hard
  link so a file created at the same moment is not clobbered (with a plain existence check on
  filesystems without hard links). The temporary file is removed on success and failure. New files
  get mode `0644`; overwritten files keep their mode.
* Reads use `read_text`, which never translates line endings.

## 8. Versioning
`mm3-version` (note and companion) and the data block's `v1` are independent format versions.
A reader that finds a higher `mm3-version` than it knows still reads the file and warns. Any
incompatible change to this page needs a new version number, an ADR and a migration note here.
