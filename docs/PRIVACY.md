# Privacy

MeetingMaster3 is local-first. This page states what data exists, where it lives, and when it can
leave your machine. It is completed as phases land and finalised in Phase 15.

## What data exists
| Data | Where it lives |
|---|---|
| Your audio recordings | `$XDG_DATA_HOME/meetingmaster3/jobs/`. The pipeline uses a normalised WAV, then keeps Opus audio for 90 days by default (configurable, pinnable) |
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
