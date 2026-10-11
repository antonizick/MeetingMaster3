# Naming speakers and voice recognition

After diarization, a transcript knows *that* different people spoke (`SPEAKER_00`, `SPEAKER_01`, …)
but not *who* they are. Before the notes are written, MeetingMaster3 pauses and asks you to name each
speaker. If you turn on voice recognition, it can also suggest names for people it has heard before.
**You always confirm the names; nothing is filled in silently.**

## 1. Naming speakers (always available)
When a job reaches "Confirm speakers", the app shows each speaker with:
- a placeholder ("Speaker 1", "Speaker 2", … in label order), their **talk time**, and how much
  clean speech (no one talking over them) the meeting has for them;
- **two or three sample clips** (start and end times) you can play to hear who it is;
- with voice recognition on: a ranked list of known people with a similarity score, and a
  **suggested** name when the match is clear.

Type a name for each speaker, or leave one out to keep its placeholder ("Speaker 2"). If the
diarizer split one person into two speakers (common in long or noisy recordings), give both the same
name, or pick the same person for both: they are merged into one participant.

The names then appear everywhere at once: the transcript turns, the note's `participants` and
`mm3-speakers` properties, the companion transcript, and the text the AI model sees when it writes
the notes. Renaming later (in the review screen, Phase 11) updates all of these again. Placeholders
are never listed as participants.

A recording whose speakers could not be separated (no Hugging Face token, or diarization turned off)
has no speakers to name, so this step is skipped.

**Until the web UI arrives (Phase 10)** you can answer with the API:

```bash
curl -s http://127.0.0.1:8765/api/jobs/$JOB/speakers            # speakers, clips, suggestions
curl -s -X POST http://127.0.0.1:8765/api/jobs/$JOB/speakers \
  -H "X-CSRF-Token: $TOKEN" -b "mm3_csrf=$TOKEN" -H 'Content-Type: application/json' \
  -d '{"SPEAKER_00": {"name": "Alice", "enroll": true}, "SPEAKER_01": "Bob"}'
```

Play a sample clip with `GET /api/jobs/$JOB/audio` (it supports HTTP Range requests; seek to the
clip's `start`).

## 2. Voice recognition (opt-in)
Voice recognition remembers what a person's voice sounds like (a **voiceprint**) so the next meeting
can suggest their name. A voiceprint is **biometric data**, so the feature is **off by default**.

Turn it on in `config.yaml` (the Settings screen follows in Phase 12):

```yaml
privacy:
  voiceprints_enabled: true
```

Then, when you confirm a speaker, tick **remember this voice** (`"enroll": true` in the API) for the
people you want recognised. Only those speakers are stored. Confirming a suggestion and ticking it
again adds another sample to that person, which helps when you record in different places (a
headset one week, a laptop microphone the next). Each person keeps the 20 most recent samples.

When you type a name that exactly matches one stored person, the new sample is added to that person.
If you picked a suggested person and typed a different name, the stored name is updated.

### How suggestions work
For each speaker the app picks up to 45 seconds of clean speech (pieces of at least 2 seconds with
nobody talking over them), turns it into a 256-number voice signature with the speaker model that
comes with the diarization pipeline, and compares it with every stored person (cosine similarity, 1.0
= identical). A name is **suggested** when:
- the score is at least `speakers.match_threshold` (default **0.6**), and
- it beats the next-best person by at least `speakers.match_margin` (default **0.1**), and
- no other speaker in the same meeting is a better match for that person (each person is suggested
  for at most one speaker).

Otherwise the candidates are still listed, best first, but none is pre-selected. On the reference
recordings the same person scored 0.85-0.97 and different people at most 0.43 (ADR-0015 has the
numbers).

### Accuracy caveats
- **Short or noisy audio.** A speaker with under 10 seconds of clean speech is marked
  `low_confidence`; one with no piece of at least 2 seconds gets no voice signature and no
  suggestion. Crosstalk, music, speakerphones and heavy compression all lower the scores.
- **Similar voices** (relatives, people of similar age and accent) can score close to each other.
  The margin rule then withholds the suggestion; it is a hint, not an identification.
- **Diarization errors carry over.** If the diarizer mixes two people under one label, its voice
  signature is a blend and may match neither.
- **Model changes.** Voiceprints are tagged with the exact speaker model. If a future update ships a
  different model, old voiceprints are kept but not used until you confirm people again.

Tune the two settings if needed: raise the threshold if you see wrong suggestions, lower it (not
below about 0.5) if familiar voices are not recognised.

## 3. What is stored, and how to delete it
| What | Where | When |
|---|---|---|
| Speaker list, talk times, clip times, candidate names and scores | Job folder `speakers.json` | Every job; deleted with the job |
| Voice signatures of this meeting's speakers | Job folder `speaker_embeddings.json` | Only with voice recognition on; **deleted as soon as you confirm the names** |
| Confirmed names | Job folder `speaker_map.json`, `speakers.confirmed.json` | Every job |
| Voiceprints (name, created and last-seen dates, sample count, seconds of speech, and the voice signatures) | `mm3.db` (tables `voiceprints`, `voiceprint_embeddings`; file mode `0600`) | Only for speakers you chose to remember |

Voice signatures are **never** written to your vault, never logged, never returned by the API or the
CLI, and never sent anywhere. Deleting is physical: the database overwrites deleted records and
flushes its write-ahead log.

Manage them with the CLI (or the Settings screen in Phase 12):

```bash
uv run mm3 voiceprints list              # name, id, samples, minutes of speech, last seen
uv run mm3 voiceprints delete <id>       # forget one person
uv run mm3 voiceprints wipe              # forget everyone (asks first; --yes to skip)
```

or the API: `GET /api/voiceprints`, `DELETE /api/voiceprints/<id>`, and for everyone a two-step
`DELETE /api/voiceprints`: the first call deletes nothing and answers `428` with a
`details.confirm_token`; repeat it with `?confirm=<token>` within 5 minutes.

Turning voice recognition off stops new voiceprints from being stored and stops suggestions, but
keeps the stored ones until you delete them (listing and deleting still work).

## Settings
| Setting | Default | Meaning |
|---|---|---|
| `privacy.voiceprints_enabled` | `false` | Compute voice signatures, suggest names, and allow remembering voices. |
| `speakers.match_threshold` | `0.6` | Minimum similarity for a suggestion (0-1). |
| `speakers.match_margin` | `0.1` | How much the best person must beat the second best. |
| `speakers.max_embeddings_per_person` | `20` | Samples kept per person (newest first). |

See [configuration.md](configuration.md) for environment variables and [PRIVACY](../PRIVACY.md).
