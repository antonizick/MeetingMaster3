# Privacy

MeetingMaster3 is local-first. This page states what data exists, where it lives, and when it can
leave your machine. It is completed as phases land and finalised in Phase 15.

## What data exists
| Data | Where it lives |
|---|---|
| Your audio recordings | `$XDG_DATA_HOME/meetingmaster3/jobs/<job-id>/`. While a job runs: your upload (`original.<ext>`) and a 16 kHz mono WAV. When the note is written, both are replaced by a compressed Opus copy (`audio.opus`, about 11 MB per hour), which is deleted 90 days later by default (configurable, pinnable). Audio of jobs that never finish is deleted after the same period. |
| Transcripts and notes | Your Obsidian vault (Markdown), plus working copies in job folders |
| Job state, feedback ratings | Local SQLite database `mm3.db` |
| Voiceprints (opt-in) | Local SQLite only; **biometric data**, never written to the vault |
| Config, API keys, HF token | `config.yaml` (mode `0600`) or environment variables; never logged or put in the vault |
| Model weights | `$XDG_CACHE_HOME/meetingmaster3/models` (`MM3_MODELS_DIR`) |
| Transcription artifacts | Job folder: `transcript.json`, `aligned.json`, `diarization.json` (who spoke when, as time ranges; no voice embeddings), `transcript.final.json`. Deleted with the job. |

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
  and asks for confirmation on first use per job (which you can remember per backend). A remote Ollama on another machine counts as cloud. Only the transcript text and prompt are sent; audio never leaves the machine.
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

Today (before the Settings UI in Phase 12): set `privacy.audio_retention` and
`privacy.audio_retention_days` in `config.yaml`; `uv run mm3 jobs list` shows each job's audio status;
`uv run mm3 jobs prune --dry-run` lists what is due for deletion and `uv run mm3 jobs prune` deletes it
(it also runs at startup and every 24 hours); `POST /api/jobs/<id>/pin` keeps a meeting's audio and
`DELETE /api/jobs/<id>` removes a job and all its files. Retention follows the current setting: switching
to *forever* also keeps audio that was due to expire.
