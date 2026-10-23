# Configuration

## Where settings come from
Lowest to highest priority: **built-in defaults < `config.yaml` < environment variables**.

Run `uv run mm3 config path` to print the locations, and `uv run mm3 config show` to print the
effective settings with secrets masked.

## File locations (XDG)
| What | Default | Override |
|---|---|---|
| Config file | `$XDG_CONFIG_HOME/meetingmaster3/config.yaml` (`~/.config/meetingmaster3/config.yaml`) | `MM3_CONFIG_DIR` (the directory) |
| App data (`mm3.db`, `search.db`, `jobs/`, `logs/`) | `$XDG_DATA_HOME/meetingmaster3/` (`~/.local/share/meetingmaster3/`) | `MM3_DATA_DIR` |
| Cache | `$XDG_CACHE_HOME/meetingmaster3/` (`~/.cache/meetingmaster3/`) | `MM3_CACHE_DIR` |
| Model cache | `<cache>/models` | `MM3_MODELS_DIR` |

Directories are created with mode `0700`. `config.yaml` is written with mode `0600` (it can contain
secrets) and atomically. In Docker these are the `/config`, `/data` and `/models` volumes, set by `MM3_CONFIG_DIR`, `MM3_DATA_DIR` and `MM3_MODELS_DIR` (see [install-docker.md](install-docker.md)).

## Environment variables
Prefix `MM3_`; nested settings use a double underscore: `server.port` is `MM3_SERVER__PORT`. List values
are JSON: `MM3_SERVER__ALLOWED_HOSTS='["mm3.lan"]'`. The app does not read a `.env` file itself; export the
variables in your shell or process manager (see `.env.example`); Docker Compose reads `.env` through `env_file`.

Docker-specific variables: `MM3_VAULT_PATH` (host vault folder, compose variable, required), `MM3_PORT`
(host port, default 8765), `MM3_UID`/`MM3_GID` (build/run user, default 1000), `MM3_OLLAMA_URL` (default
`http://host.docker.internal:11434`, or `http://127.0.0.1:11434` with the host-network override) and
`MM3_IN_DOCKER=1` (set by the image; hides "Open the config folder").

## Settings reference
Every setting below can also be changed on the **Settings** screen ([`settings.md`](settings.md)), except `server.*`, which is read-only there on purpose.

| Setting (YAML path) | Env var | Default | Notes |
|---|---|---|---|
| `server.host` | `MM3_SERVER__HOST` | `127.0.0.1` | Non-loopback values print a warning; also list the hostnames you will browse to in `allowed_hosts`. |
| `server.port` | `MM3_SERVER__PORT` | `8765` | 1-65535. |
| `server.allowed_hosts` | `MM3_SERVER__ALLOWED_HOSTS` | `[]` | Extra `Host` header values accepted; `127.0.0.1` and `localhost` are always allowed. Anything else gets HTTP 400 (DNS-rebinding defence). |
| `vault.path` | `MM3_VAULT__PATH` | unset | Your Obsidian vault root. |
| `vault.output_subfolder` | `MM3_VAULT__OUTPUT_SUBFOLDER` | `Meetings/{yyyy}/` | Where notes are written inside the vault. Placeholders `{yyyy}`, `{mm}` and `{dd}` come from the meeting date; other `{...}` placeholders are an error. It must stay inside the vault (no `..`, absolute paths or symlinks leading out). Archives go to its `Archive/` subfolder. |
| `vault.templates_subfolder` | `MM3_VAULT__TEMPLATES_SUBFOLDER` | `MeetingMaster3/templates/` | Templates folder inside the vault. The built-in templates are copied here on first use; your copies override built-ins with the same `id`. See [`templates.md`](templates.md). |
| `transcription.model` | `MM3_TRANSCRIPTION__MODEL` | `auto` | faster-whisper model (`large-v3-turbo`, `large-v3`, `medium`, `small`, a Hugging Face repo id or a local folder). `auto` uses the hardware recommendation. See [`transcription.md`](transcription.md). |
| `transcription.compute_type` | `MM3_TRANSCRIPTION__COMPUTE_TYPE` | `auto` | `float16`, `int8_float16`, `int8` or `float32`; `auto` = recommendation. GPU-only types become `int8` on the CPU. |
| `transcription.batch_size` | `MM3_TRANSCRIPTION__BATCH_SIZE` | unset | 1-64; unset = recommendation (8 on 8 GB). Halved automatically after an out-of-memory error. |
| `transcription.device` | `MM3_TRANSCRIPTION__DEVICE` | `auto` | `auto` (CUDA if usable), `cuda` or `cpu`. |
| `transcription.language` | `MM3_TRANSCRIPTION__LANGUAGE` | unset | Force a language code (`en`, `de`, ...) and skip detection. |
| `transcription.on_non_english` | `MM3_TRANSCRIPTION__ON_NON_ENGLISH` | `ask` | `ask` pauses the job, `proceed` transcribes in the detected language with a warning, `abort` fails the job (`E_NOT_ENGLISH`). |
| `transcription.diarize` | `MM3_TRANSCRIPTION__DIARIZE` | `true` | Speaker diarization. Off, or without the model, transcripts have no speaker labels. |
| `transcription.diarization_model` | `MM3_TRANSCRIPTION__DIARIZATION_MODEL` | `pyannote/speaker-diarization-community-1` | The pyannote pipeline (gated; see [`transcription.md`](transcription.md)). |
| `transcription.offline` | `MM3_TRANSCRIPTION__OFFLINE` | `false` | Never download models (sets `HF_HUB_OFFLINE=1`). Cached models are always loaded without network access anyway. |
| `transcription.unload_ollama` | `MM3_TRANSCRIPTION__UNLOAD_OLLAMA` | `true` | Before GPU transcription, ask the job's LLM backend to unload its models if it is an Ollama on this machine (spec R5). |
| `hardware.profile` | `MM3_HARDWARE__PROFILE` | `auto` | `auto`, `cpu`, `vram8`, `vram16` or `vram24plus`. Declares the hardware profile instead of detecting it; see [`hardware.md`](hardware.md). |
| `llm.default_backend` | `MM3_LLM__DEFAULT_BACKEND` | `ollama` | Name of the backend used for notes. If no backend is configured under that name and it is `ollama`, a local Ollama at `http://127.0.0.1:11434` is used. |
| `llm.backends.<name>` | `MM3_LLM__BACKENDS__<NAME>__<FIELD>` | none | One entry per backend; fields below. See [`llm-backends.md`](llm-backends.md). |
| `llm.backends.<name>.kind` | | required | `ollama`, `openai_compat`, `openrouter`, `openai` or `bedrock`. |
| `llm.backends.<name>.base_url` | | per kind | Ollama: `http://127.0.0.1:11434`. OpenRouter and OpenAI have presets. Required for `openai_compat`, include the `/v1`. |
| `llm.backends.<name>.api_key` | | unset | Secret. For `openrouter` and `openai` it falls back to `secrets.openrouter_api_key` / `secrets.openai_api_key`. |
| `llm.backends.<name>.region` / `.profile` | | `us-east-1` / unset | Bedrock only. Credentials come from `secrets.aws_*` when both are set, otherwise the AWS chain (profile, `AWS_*` env). |
| `llm.backends.<name>.default_model` | | unset | Model id used when a job does not pick one. |
| `llm.backends.<name>.params` | | `{}` | Extra options: Ollama `options` (e.g. `top_p`, `num_ctx`), OpenAI-style body fields, or Bedrock `additionalModelRequestFields`. |
| `llm.backends.<name>.headers` | | `{}` | Extra HTTP headers, e.g. OpenRouter `HTTP-Referer` and `X-Title` (off by default; nothing identifying is sent unless you add it). |
| `llm.backends.<name>.context_window` | | auto | Override when the server cannot report the model's context size. Bedrock reads it from `llm/bedrock_models.yaml` by model family (inference profile ids included); set this only for a model that table does not know. Unknown windows are treated as 8192 tokens. |
| `llm.backends.<name>.consent_remembered` | | `false` | Remember cloud-egress consent for this backend (skips the per-job prompt). |
| `llm.backends.<name>.cloud_embedding_consent` | | `false` | Allow this (cloud) backend to embed meetings for search when it is `search.embedding_backend`. **Indexing sends the full text of every indexed meeting to the provider, and each search sends the query.** Separate from `consent_remembered`, which covers one meeting's notes. Without it a cloud embedder is refused (`E_CONSENT_REQUIRED`), nothing is sent and search uses words only. Ignored for local backends (ADR-0049). |
| `llm.backends.<name>.ask_consent_remembered` | | `false` | Always allow the **Ask-AI agent** to send meeting excerpts (the matching passages of up to `ask.max_meetings` meetings, with names and dates) and the question to this (cloud) backend, without the per-question tick (Phase 15j, S6). Separate from `consent_remembered` and `cloud_embedding_consent`; neither covers Ask-AI. Without it (and without the tick or `mm3 ask --allow-cloud`) a cloud question is refused with `E_CONSENT_REQUIRED` and nothing is sent. Ignored for local backends. |
| `vault.attachments_subfolder` | `MM3_VAULT__ATTACHMENTS_SUBFOLDER` | `Meetings/attachments/` | Where the optional audio copy goes (inside the vault). Used only when `privacy.copy_audio_to_vault` is on. |
| `generation.default_template` | `MM3_GENERATION__DEFAULT_TEMPLATE` | `default-notes` | Template used when a job does not choose one, and pre-selected on the New meeting page. Starting a meeting from that page with another template saves it here, so the choice sticks (R29). Was `executive-summary` before Phase 15e; a value already in your `config.yaml` is kept. |
| `generation.write_companion` | `MM3_GENERATION__WRITE_COMPANION` | `true` | Write the companion `.transcript.md` next to each note. Turning it off saves space but the note can no longer be re-opened to regenerate sections or rename speakers (a warning says so on every job). |
| `generation.readable_transcript` | `MM3_GENERATION__READABLE_TRANSCRIPT` | `true` | Also write a readable copy of the transcript, `<note> (Transcript).md`, next to each note: the time, the speaker's name highlighted in their colour, then the text (R25). It is made from the companion transcript (so it needs `write_companion`) and rewritten whenever the companion changes, for example after renaming a speaker. When off, no new readable transcripts are made; existing ones are still kept up to date. |
| `generation.max_context` | `MM3_GENERATION__MAX_CONTEXT` | `16384` | The largest context window (tokens) planned for a **local** model. Models advertise windows (e.g. 40k) that an 8 GB GPU cannot hold next to the weights; longer meetings are summarised in parts (map-reduce). Raise it on bigger GPUs (e.g. 32768 on 16 GB). Cloud models use their own window. Each note asks Ollama for only what its largest call needs plus 10 % (about 13k for a long meeting at 16384); Ollama's own memory settings for small GPUs are in [hardware.md](hardware.md#ollama-settings-for-small-gpus-recommended-on-8-gb). |
| `generation.think` | `MM3_GENERATION__THINK` | `false` | Let reasoning models (qwen3, deepseek-r1, ...) "think" before answering. Off by default: it is several times slower and can use up a section's length limit. |
| `generation.install_templates` | `MM3_GENERATION__INSTALL_TEMPLATES` | `true` | Copy the built-in templates into the vault's templates folder the first time a vault is used. Edited copies are never overwritten. |
| `search.enabled` | `MM3_SEARCH__ENABLED` | `true` | Keep the meeting index (`<data>/search.db`) for the **Search** page, `mm3 search` and Ask-AI (R30). Off: nothing is indexed and searches are refused; *Delete index* in Settings turns it off. See [search-and-ask.md](search-and-ask.md). |
| `search.embedding_backend` | `MM3_SEARCH__EMBEDDING_BACKEND` | unset | The backend that embeds passages and queries. Unset (`auto` in Settings): the local `ollama`, else the first local backend that can embed. A cloud backend also needs its `cloud_embedding_consent`. |
| `search.embedding_model` | `MM3_SEARCH__EMBEDDING_MODEL` | `nomic-embed-text` | The embedding model (Ollama: run `ollama pull nomic-embed-text` once; Bedrock: `amazon.titan-embed-text-v2:0`; OpenRouter: e.g. `openai/text-embedding-3-small`). Changing it (or the backend kind) re-embeds every passage at the next update; vectors of two models are never mixed. |
| `search.chunk_tokens` | `MM3_SEARCH__CHUNK_TOKENS` | `350` | About how many tokens one passage holds (64-2000). Applies to all meetings after *Rebuild index*. |
| `search.chunk_overlap` | `MM3_SEARCH__CHUNK_OVERLAP` | `50` | Tokens repeated between neighbouring passages of a long section or transcript (0-500). |
| `search.index_transcripts` | `MM3_SEARCH__INDEX_TRANSCRIPTS` | `true` | Index companion transcripts as well as notes. Off: transcripts already indexed are dropped at the next update. |
| `search.rescan_minutes` | `MM3_SEARCH__RESCAN_MINUTES` | `10` | How often the vault is checked for notes changed outside MeetingMaster3 (Obsidian). Changes MeetingMaster3 makes are indexed within seconds, and a search also checks the vault when the last check is more than a minute old. |
| `ask.default_backend` | `MM3_ASK__DEFAULT_BACKEND` | unset | The backend the **Ask-AI** page and `mm3 ask` use. Unset (`auto` in Settings): `llm.default_backend`. A cloud backend asks for consent on every question unless its `ask_consent_remembered` is on. See [search-and-ask.md](search-and-ask.md#ask). |
| `ask.default_model` | `MM3_ASK__DEFAULT_MODEL` | unset | The model that answers on the default Ask-AI backend. Unset: that backend's `default_model`. |
| `ask.max_meetings` | `MM3_ASK__MAX_MEETINGS` | `25` | Most meetings read for one question (1-200); each is one model call. Also the most meetings whose excerpts a cloud backend receives. |
| `ask.answers_subfolder` | `MM3_ASK__ANSWERS_SUBFOLDER` | `MM3 Answers/` | Vault folder for answer notes (must be inside the vault). Changing it does not move existing answers; they are still found by their `mm3-answer-id`. |
| `ask.keep_history` | `MM3_ASK__KEEP_HISTORY` | `true` | Save every answer as a vault note and list it on the Ask-AI page. Off: answers are shown once and kept nowhere. |
| `audio.max_upload_mb` | `MM3_AUDIO__MAX_UPLOAD_MB` | `2048` | Largest accepted upload, in MiB (R7). Larger uploads get HTTP 413 `E_UPLOAD_TOO_LARGE`. |
| `audio.opus_bitrate_kbps` | `MM3_AUDIO__OPUS_BITRATE_KBPS` | `24` | Bitrate of the Opus copy kept after a note is written (6-128). |
| `jobs.max_concurrent` | `MM3_JOBS__MAX_CONCURRENT` | `2` | Jobs processed at once (1-8). GPU stages never overlap regardless (R5); this lets one job's CPU work run beside another's GPU work. |
| `jobs.prune_interval_hours` | `MM3_JOBS__PRUNE_INTERVAL_HOURS` | `24` | How often the audio retention pruner runs (it also runs at startup). |
| `privacy.audio_retention` | `MM3_PRIVACY__AUDIO_RETENTION` | `days` | `forever`, `days` or `delete_after_write` (ADR-0006, ADR-0013). Applied by the pruner to every job using the **current** value. `delete_after_write` deletes the audio as soon as the note is written. |
| `privacy.copy_audio_to_vault` | `MM3_PRIVACY__COPY_AUDIO_TO_VAULT` | `false` | Copy the retained Opus audio into `vault.attachments_subfolder` when the note is written, and link it from the note (`mm3-audio`). Makes the vault larger and a synced vault uploads the audio. |
| `privacy.audio_retention_days` | `MM3_PRIVACY__AUDIO_RETENTION_DAYS` | `90` | With `days`: audio is deleted this many days after the note was written. With `days` or `delete_after_write`: audio of unfinished jobs (failed, cancelled, interrupted, waiting) is deleted this many days after the job last changed. Pinned meetings ("Keep forever" on the review screen) are never pruned. The days-left line on the review screen uses the same rule as the pruner, with the current value of these settings. |
| `privacy.voiceprints_enabled` | `MM3_PRIVACY__VOICEPRINTS_ENABLED` | `false` | Opt-in voice recognition (biometric data, S7): compute voice signatures, suggest speaker names and allow remembering voices. Off: no signatures are computed and nothing is stored; stored voiceprints can still be listed and deleted. See [speakers.md](speakers.md). |
| `speakers.match_threshold` | `MM3_SPEAKERS__MATCH_THRESHOLD` | `0.6` | Minimum cosine similarity (0-1) for a name suggestion (ADR-0015). |
| `speakers.match_margin` | `MM3_SPEAKERS__MATCH_MARGIN` | `0.1` | How much the best person must beat the second best for a suggestion. |
| `speakers.max_embeddings_per_person` | `MM3_SPEAKERS__MAX_EMBEDDINGS_PER_PERSON` | `20` | Voice samples kept per person and speaker model (newest first, 1-200). |
| `secrets.hf_token` | `MM3_SECRETS__HF_TOKEN` (or `HF_TOKEN`) | unset | Hugging Face read token, needed once to download the gated diarization model (`pyannote/speaker-diarization-community-1`). |
| `secrets.openrouter_api_key` | `MM3_SECRETS__OPENROUTER_API_KEY` | unset | |
| `secrets.openai_api_key` | `MM3_SECRETS__OPENAI_API_KEY` | unset | |
| `secrets.aws_access_key_id` / `secrets.aws_secret_access_key` | `MM3_SECRETS__AWS_ACCESS_KEY_ID` / `MM3_SECRETS__AWS_SECRET_ACCESS_KEY` | unset | Access key pair of the IAM user for Bedrock, used by every `bedrock` backend; set both or neither. Editable in Settings → Language models → *AWS keys for Bedrock*. Unset: the standard AWS chain (profile, `AWS_*` variables, session tokens). Guide: [llm-backends.md](llm-backends.md#setting-up-aws-bedrock-step-by-step). |

Secrets are never printed or returned by the API unmasked, and are redacted from logs.

## Development-only environment variables
| Variable | Effect |
|---|---|
| `MM3_FAKE_PIPELINE=1` | Replace transcription, diarization, speaker suggestion and the LLM with fakes that simulate progress and write sample results (no ML models or LLM needed). Notes are generated by the real generation stage from an offline fake model and written to the vault when one is configured (otherwise nothing is written). For UI development and demos. |
| `MM3_FAKE_STAGE_SECONDS` | Seconds each fake stage takes (default `2`). |
| `MM3_MODELS_DIR` | Model cache folder (default `$XDG_CACHE_HOME/meetingmaster3/models`); `HF_HOME` and `TORCH_HOME` point here while the app runs. |
| `HF_HUB_OFFLINE=1` | Same as `transcription.offline: true`. |
| `MM3_PRIVATE_TEST_AUDIO` | A file or folder of real recordings for the `slow` GPU test (never committed). |

## Per-job options
The upload's `options` JSON (and `POST /api/jobs/{id}/resume` `overrides`) accept:
* transcription: `transcription_model`, `compute_type`, `batch_size`, `language`,
  `on_non_english`, `diarize`, `min_speakers` and `max_speakers`; they win over the settings above;
* the note: `title`, `meeting_date` (`YYYY-MM-DD`), `meeting_time` (`HH:MM`), `participants` and
  `tags` (lists), `location`, `template`, `backend`, `model` (the **LLM** model), `instructions`
  (extra instructions for every section, up to 4000 characters) and `cloud_consent` (true = the
  user already agreed to send this job's transcript to the chosen cloud backend, S6);
* `remember_template` (upload only, not stored): `true` saves a valid `template` as
  `generation.default_template`. The New meeting page always sends it, so the template you start
  a meeting with is pre-selected next time (R29).

`POST /api/jobs/{id}/generate` changes `template`, `backend`, `model`, `instructions` and
`cloud_consent` of a job that has not finished (see [`templates.md`](templates.md)).

## Example `config.yaml`
```yaml
llm:
  default_backend: ollama
  backends:
    ollama:
      kind: ollama
      default_model: qwen3:8b
    openrouter:
      kind: openrouter
      api_key: sk-or-...   # or set MM3_SECRETS__OPENROUTER_API_KEY
      default_model: vendor/model
server:
  port: 8765
vault:
  path: /home/you/Documents/Vault
generation:
  default_template: default-notes
  max_context: 16384      # local models; raise on bigger GPUs
privacy:
  audio_retention: days
  audio_retention_days: 90
  voiceprints_enabled: false   # opt-in voice recognition (speakers.md)
speakers:
  match_threshold: 0.6
audio:
  max_upload_mb: 2048
transcription:
  model: auto             # or large-v3-turbo, medium, ...
  on_non_english: ask
secrets:
  hf_token: hf_...        # once, for the gated diarization model
```
