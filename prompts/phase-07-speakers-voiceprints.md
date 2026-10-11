# Phase 07: Speaker Mapping & Voiceprint Store

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 06 · **Branch:** `phase-07-speakers-voiceprints`

## Read first
`CLAUDE.md`, `prompts/_shared-instructions.md`, and `docs/SPECIFICATION.md` §3 (flow step 5), §7 (speaker persistence), §13 (voiceprint risk), §15.3 (S7, biometric data). Phase Log entries for 04 and 06.

**Phase 03 interfaces:** `domain.transcript.SpeakerMap` (labels to confirmed names; `display_name` gives stable `Speaker N` placeholders; `apply(transcript)` returns a named copy), `CompanionTranscript`, and `markdown.transcript_format.rename_speakers(text, speaker_map)`, which rewrites the companion's frontmatter and turn-heading names in place and refuses (`transcript_turns_mismatch`) when the readable turns were restructured. `MeetingMeta.speakers` and `participants` feed the note frontmatter. Labels must match `[A-Za-z0-9_-]{1,64}`.

## Goal
After diarization, the app suggests a real name for each `SPEAKER_xx` from a local, opt-in voiceprint store. The user always confirms. Once confirmed, the mapping cascades into the transcript, the generation context and the note frontmatter.

## Tasks
1. **Embeddings (`speakers/embeddings.py`):** for each diarized speaker, pick the best segments: long enough (≥ 2–3 s), little overlap with other speakers, and up to N segments totalling about 30–60 s. Extract embeddings with the pyannote embedding model the pinned stack uses (lazy import; GPU if available, otherwise CPU). Average them and L2-normalise to get one centroid per speaker, plus a quality score (total clean speech duration, number of segments). Speakers with too little clean audio get `low_confidence`.
2. **Store (`speakers/store.py`):** a SQLite migration adding `voiceprints` (person_id, display_name, created_at, updated_at, n_samples, total_seconds) and `voiceprint_embeddings` (person_id, embedding BLOB float32, model_id, source_job_id, created_at). Keep several embeddings per person (capped, e.g. the 20 most recent or best). Model-id awareness: never compare embeddings from different models. Disabled unless `privacy.voiceprints_enabled` is true; when disabled nothing is persisted, but in-session naming still works.
3. **Matching (`speakers/match.py`):** cosine similarity of each meeting speaker's centroid against each person's embeddings (max or mean, chosen and justified with a small experiment). The threshold is configurable (default chosen by experiment, likely 0.6–0.75), with a margin over the second-best match. Use Hungarian assignment so two speakers never get the same person. Output a ranked candidate list per speaker with scores and a `suggested` flag.
4. **`SpeakerSuggestStage`** (from Phase 04's pipeline): computes embeddings and suggestions, writes `speakers.json` (labels, stats, sample snippet times for the UI to play, candidates), then moves the job to `waiting_for_input`.
5. **Confirmation API:** `GET /api/jobs/{id}/speakers` returns labels, talk time, 2–3 sample snippet timestamps each, and suggestions. `POST /api/jobs/{id}/speakers` takes `{label: {name, person_id?, enroll: bool}}`, merges labels (two labels can map to the same person, since diarizers over-split) and resumes the job. On confirm with `enroll=true` and voiceprints enabled, the embeddings are added to that person (new or existing).
6. **Cascade:** a single `SpeakerMap` is stored with the job and applied to the transcript (`transcript.final.json` → named view), the generation context (Phase 09), the note frontmatter (`participants`, `mm3-speakers`) and the companion transcript. Renaming later (Phase 11) re-applies it everywhere through the same function.
7. **Privacy controls:** `GET /api/voiceprints` (list people, sample counts, last seen; never the raw vectors), `DELETE /api/voiceprints/{person_id}`, `DELETE /api/voiceprints` (wipe all; needs a confirmation token), `mm3 voiceprints list|delete|wipe`. Voiceprints are **never** written to the vault or logs.

## Tests
Synthetic-vector tests for matching (threshold, margin, Hungarian uniqueness, model-id isolation); store CRUD and wipe; the merge-labels cascade; the disabled-store path persists nothing; API validation. `gpu`/`models` test: enroll speakers from the fixture clip and re-run on the same clip, and expect the correct suggestions.

## Acceptance criteria
- Second run on the same voices: correct suggestions, above threshold, on the reference fixture.
- With voiceprints disabled (the default), no rows are written to the voiceprint tables (asserted by a test).
- Wipe removes everything, verified at the DB level.

## Phase-specific docs
`docs/user-guide/speakers.md` (how naming and suggestions work, accuracy caveats for short or noisy audio); PRIVACY and SECURITY (the biometric data section: what is stored, where, how to delete, opt-in default); configuration doc (threshold, enable flag); ADR (embedding model and threshold choice, with the experiment numbers). Then the standard close-out checklist.
