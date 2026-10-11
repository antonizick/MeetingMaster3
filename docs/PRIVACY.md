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
| Model weights | `$XDG_CACHE_HOME/meetingmaster3/models` |

## What can leave your machine
- **Model downloads** from Hugging Face and Ollama (inbound). After the first download, offline mode
  (`HF_HUB_OFFLINE=1`) makes the app work with no network calls.
- **Transcript text sent to a cloud LLM**, only if you choose a cloud backend (AWS Bedrock, OpenRouter
  or another OpenAI-compatible endpoint). The UI badges the backend as "local" or "cloud: <provider>"
  and asks for confirmation on first use per job (which you can remember per backend). A remote Ollama on another machine counts as cloud. Only the transcript text and prompt are sent; audio never leaves the machine.
- **Your vault**, if you sync it (Obsidian Sync, cloud drives). That is outside this app's control.
  If you enable the optional "copy audio to vault" setting, the audio syncs too.

## What never leaves
No telemetry, analytics or crash reports are sent. Audio and voiceprints are never uploaded by the app.

## Your controls
Delete any meeting's audio, pin audio to keep it, list and delete voiceprints or wipe the store, and
set the audio retention period (forever / N days / delete after write).

Today (before the Settings UI in Phase 12): set `privacy.audio_retention` and
`privacy.audio_retention_days` in `config.yaml`; `uv run mm3 jobs list` shows each job's audio status;
`uv run mm3 jobs prune --dry-run` lists what is due for deletion and `uv run mm3 jobs prune` deletes it
(it also runs at startup and every 24 hours); `POST /api/jobs/<id>/pin` keeps a meeting's audio and
`DELETE /api/jobs/<id>` removes a job and all its files. Retention follows the current setting: switching
to *forever* also keeps audio that was due to expire.
