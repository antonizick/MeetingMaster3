# Privacy

MeetingMaster3 is local-first. This page states what data exists, where it lives, and when it can
leave your machine. Final inventory as of Phase 15 (2026-10-12); the threat model is
[THREAT_MODEL.md](THREAT_MODEL.md).

## What data exists
| Data | Where it lives |
|---|---|
| Your audio recordings | `$XDG_DATA_HOME/meetingmaster3/jobs/<job-id>/`. While a job runs: your upload (`original.<ext>`) and a 16 kHz mono WAV. When the note is written, both are replaced by a compressed Opus copy (`audio.opus`, about 11 MB per hour), which is deleted 90 days later by default (configurable, pinnable). Audio of jobs that never finish is deleted after the same period. |
| Transcripts and notes | Your Obsidian vault (Markdown), plus working copies in job folders |
| Job state, feedback ratings | Local SQLite database `mm3.db`. Ratings (stars or thumbs, an optional comment, the template, backend and model used) are only stored here; the Settings > About tab exports them as CSV or JSON for your own analysis. They are never sent anywhere. |
| Voiceprints (opt-in, off by default) | Local SQLite only (`mm3.db`, tables `voiceprints` and `voiceprint_embeddings`): each remembered person's name, dates, sample count, seconds of speech and up to 20 voice signatures (256 numbers each). **Biometric data**: stored only for speakers you chose to remember, never written to the vault, logs or API responses. See [Naming speakers and voice recognition](user-guide/speakers.md). |
| Speaker naming artifacts | Job folder: `speakers.json` (labels, talk time, clip times, candidate names and scores), `speaker_map.json`, `speakers.confirmed.json`, `transcript.named.json`. With voice recognition on, `speaker_embeddings.json` holds this meeting's voice signatures until you confirm the names, then it is deleted; if the job never gets that far, the file is deleted with the audio (retention) or by "delete all voiceprints", and it is never included in exports. |
| Config, API keys, HF token | `config.yaml` (mode `0600`) or environment variables; never logged or put in the vault |
| Model weights | `$XDG_CACHE_HOME/meetingmaster3/models` (`MM3_MODELS_DIR`) |
| Transcription artifacts | Job folder: `transcript.json`, `aligned.json`, `diarization.json` (who spoke when, as time ranges; no voice embeddings), `transcript.final.json`. Deleted with the job. |
| Note drafts | Job folder: `notes.draft.md` (the generated note), `generation.json` (template, backend, model), `generate.partial.json` (finished sections while generating), `written.json` (vault paths). Deleted with the job. |
| Review workspace copies | `$XDG_DATA_HOME/meetingmaster3/reviews/<mm3-id>/` (folder `0700`): the last few versions of a note as you opened it (used to detect edits made elsewhere), your unsaved edits (`draft.json`, deleted when you save) and a template switch waiting for your confirmation. They contain meeting text; delete the folder to remove them. Archived versions of sections and notes go to an `Archive` folder in your vault. |
| Feedback ratings | `mm3.db` (`feedback` table) |
| Copy of the audio in the vault (optional, off by default) | Your vault's attachments folder, linked from the note (`mm3-audio`); never replaces an existing file |
| Logs | The terminal (stderr) of `mm3 serve`; secrets are redacted and transcript text is not logged at the default level. Nothing is written to a log file unless you redirect it |
| Templates | Your vault's templates folder (`MeetingMaster3/templates/`); `templates.installed.json` in the app data folder records only file hashes, to avoid overwriting your edits. |

## Exports
**Export all app data** (Settings > About) builds a zip on your computer: the database tables as JSON, your settings with every secret masked, and each meeting's working files. It contains no API keys or tokens, no audio and no voiceprints. A meeting's **Download** menu exports its note, transcript or a zip (with the audio while it is kept). Nothing is uploaded by the app.

## What can leave your machine
- **Model downloads** from Hugging Face, download.pytorch.org and Ollama (inbound; your IP address
  and the model names are visible to those services, and the gated diarization model is tied to your
  Hugging Face account through your token). These are the only network calls transcription makes:
  once a model is cached, it is loaded from disk without contacting Hugging Face (verified in Phase 06
  by recording every socket connection of a full diarized job: the only one was to a local Ollama).
  `transcription.offline: true` (or `HF_HUB_OFFLINE=1`) also forbids downloads.
- **A local Ollama** is asked to unload its models before transcription (a request to
  `127.0.0.1`; nothing leaves the machine).
- **Transcript text sent to a cloud LLM**, only if you choose a cloud backend (AWS Bedrock, OpenRouter
  or another OpenAI-compatible endpoint). The UI badges the backend as "local" or "cloud: <provider>"
  and asks for confirmation on first use per job (which you can remember per backend): the job
  pauses before anything is sent, and declining stops it with nothing sent. A remote Ollama on another machine counts as cloud. Only the transcript text and prompt are sent; audio never leaves the machine.
- **Your vault**, if you sync it (Obsidian Sync, cloud drives). That is outside this app's control.
  If you enable the optional "copy audio to vault" setting, the audio syncs too.

## What never leaves
No telemetry, analytics or crash reports are sent. Audio and voiceprints are never uploaded by the app.
Some libraries report usage by default, and MeetingMaster3 switches them off before they load:
pyannote.audio 4 would send model names, audio durations and speaker counts to `otel.pyannote.ai`
(`PYANNOTE_METRICS_ENABLED=false`), and Hugging Face Hub telemetry is disabled
(`HF_HUB_DISABLE_TELEMETRY=1`, `DO_NOT_TRACK=1`).

## Your controls
Delete any meeting's audio, pin audio to keep it, list and delete voiceprints or wipe the store, and
set the audio retention period (forever / N days / delete after write).

**Voiceprints.** Voice recognition is off unless you set `privacy.voiceprints_enabled: true`. While it
is off, no voice signatures are computed at all. When it is on, a voice is remembered only when you
tick "remember this voice" for that speaker. `uv run mm3 voiceprints list` shows who is stored (never
the signatures), `mm3 voiceprints delete <id>` forgets one person and `mm3 voiceprints wipe` forgets
everyone; the API equivalents are `GET /api/voiceprints`, `DELETE /api/voiceprints/<id>` and a two-step
`DELETE /api/voiceprints` (confirmation token). Deletion is physical: SQLite's `secure_delete`
overwrites the records and the write-ahead log is flushed and truncated. Turning the feature off keeps
stored voiceprints (unused) until you delete them.

Everything above is in **Settings**: *Privacy* (audio retention, preview and prune, voiceprints list,
delete and two-step "delete all"), *About & diagnostics* (export all app data, open the config folder),
and each meeting's *Download* menu. On the command line: `uv run mm3 jobs list` shows each job's audio
status, `uv run mm3 jobs prune --dry-run` lists what is due for deletion and `uv run mm3 jobs prune`
deletes it (it also runs at startup and every 24 hours); `POST /api/jobs/<id>/pin` keeps a meeting's
audio and `DELETE /api/jobs/<id>` removes a job and all its files. Retention follows the current
setting: switching to *forever* also keeps audio that was due to expire.
