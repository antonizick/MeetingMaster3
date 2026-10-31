# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-10-31

First release. MeetingMaster3 turns meeting audio, or an existing transcript, into a speaker-attributed
transcript and a structured Obsidian note, on your own machine. The phase-by-phase history of how it was built
is in [`docs/MM3_CHANGELOG_DETAILED.md`](docs/MM3_CHANGELOG_DETAILED.md).

### Added
- **From audio to a note.** Upload a recording (or run `mm3 process`): ffmpeg normalisation, WhisperX
  transcription with word alignment and pyannote speaker diarization, a pause to name the speakers, notes written
  by a language model from a template, and a note plus its transcripts saved in your Obsidian vault. Jobs are
  queued one at a time on the GPU, checkpointed and resumable, with live progress and an ETA, cancel, and one
  automatic retry after a GPU out-of-memory error.
- **Speakers.** Name each speaker once, with sample clips to listen to. Optional, off-by-default local
  voiceprints suggest names in later meetings; they are biometric data, stored only for people you choose and
  erased for real when deleted (`mm3 voiceprints`).
- **24 built-in templates** (Default Notes, Executive Summary, Decision Log, Action-Focused, Job Interview Notes,
  Board Minutes, Stand-up, Retrospective, Create Project Plan and more), each opening with a **Summary Succinct**
  and a **Summary Detailed**. Templates are plain files in your vault: edit, duplicate or add your own. Action
  items are Obsidian checkboxes with an owner only when someone took the task on; long meetings are summarised in
  parts (map-reduce) so nothing is skipped.
- **Vault output.** Notes with frontmatter, wikilinks and section markers; a full-fidelity companion transcript and
  a readable, colour-coded transcript next to each note; atomic, non-clobbering writes confined to the vault;
  archives of every replaced version.
- **Review workspace.** Synced audio and transcript, the note in Preview or an editor, per-section regeneration
  with diffs, template switching with a live progress bar and ETA, speaker renaming, re-opening and re-linking
  notes from the vault, the recording's size and download, and a Keep forever control with a days-left line for the
  audio (Opus, deleted after 90 days by default).
- **Meetings page** listing every meeting in paged sections, with Update older notes, and **Title & date**:
  rename or re-date a meeting everywhere (files, folder, links in your other notes, database), previewed,
  journaled and backed up first (`mm3 meetings rename`).
- **Search** by meaning and by words (local `nomic-embed-text` embeddings plus an FTS5 index, kept in step with
  the vault; `mm3 search`) and **Ask-AI**: broad questions answered from your meetings with cited, table-backed
  answers saved as linked notes in `MM3 Answers/` (`mm3 ask`).
- **Import** a transcript or an AI conversation instead of audio: Markdown chats (even unlabelled Grok voice-mode
  exports), `[hh:mm:ss] Name:` transcripts, MM3 companions, VTT and SRT, or a **Grok share link**
  (`mm3 import`), with a one-click check of who said each turn. Untimed transcripts invent no times.
- **Language models.** Local Ollama by default; optional bring-your-own-key AWS Bedrock and OpenAI-compatible
  backends including OpenRouter, verified live, with a model picker showing prices, estimated cost per meeting
  and Best value / Best quality picks, and explicit consent before anything leaves your machine.
- **Settings screen** for everything in `config.yaml` (write-only API keys, connection tests, retention,
  voiceprints, hardware profile), template library management, local feedback ratings and a full data export.
- **Hardware awareness.** GPU and VRAM detection, per-profile recommendations (8 GB measured, others estimated),
  and `mm3 doctor`.
- **Docker.** GPU and CPU images (Debian 13, non-root, read-only filesystem), a compose file with volumes and an
  optional bundled Ollama pinned to `0.40.7`, and host-Ollama connectivity options.
- **Quality and safety net.** Strict typing, a large unit, integration, fuzz and browser test suite, a generation
  eval with a saved quality baseline, accessibility checks (axe-core), a threat model, a documented security
  review, a dependency and licence audit, and measured performance (`docs/PERFORMANCE.md`).
- `scripts/check_config_docs.py` (run in CI) fails when `docs/user-guide/configuration.md` and the `Settings`
  model disagree.

### Security
- Binds to `127.0.0.1` only, with Host, Origin and CSRF checks, a strict content security policy, sanitised
  Markdown rendering, vault path confinement, masked secrets, no telemetry (pyannote's is switched off) and
  cloud consent that is single-use per answer. See [`SECURITY.md`](SECURITY.md) and
  [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).
- Importing a Grok share link is the only request to a non-LLM website: one HTTPS `GET` to a fixed host, no
  redirects, size and time limits ([`docs/PRIVACY.md`](docs/PRIVACY.md)).

### Known limitations
See the README's "Known limitations" and [`docs/ROADMAP.md`](docs/ROADMAP.md). In short: single user and no
login; English-first; measured on one 8 GB laptop GPU; tested in Chromium only; the `ml` extra carries known
upstream advisories that WhisperX's pins block (ADR-0014).

[Unreleased]: https://github.com/antonizick/MeetingMaster3/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/antonizick/MeetingMaster3/releases/tag/v0.1.0
