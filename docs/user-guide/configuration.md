# Configuration

## Where settings come from
Lowest to highest priority: **built-in defaults < `config.yaml` < environment variables**.

Run `uv run mm3 config path` to print the locations, and `uv run mm3 config show` to print the
effective settings with secrets masked.

## File locations (XDG)
| What | Default | Override |
|---|---|---|
| Config file | `$XDG_CONFIG_HOME/meetingmaster3/config.yaml` (`~/.config/meetingmaster3/config.yaml`) | `MM3_CONFIG_DIR` (the directory) |
| App data (`mm3.db`, `jobs/`, `logs/`) | `$XDG_DATA_HOME/meetingmaster3/` (`~/.local/share/meetingmaster3/`) | `MM3_DATA_DIR` |
| Cache | `$XDG_CACHE_HOME/meetingmaster3/` (`~/.cache/meetingmaster3/`) | `MM3_CACHE_DIR` |
| Model cache | `<cache>/models` | `MM3_MODELS_DIR` |

Directories are created with mode `0700`. `config.yaml` is written with mode `0600` (it can contain
secrets) and atomically. In Docker these become the `/config`, `/data` and `/models` volumes (Phase 14).

## Environment variables
Prefix `MM3_`; nested settings use a double underscore: `server.port` is `MM3_SERVER__PORT`. List values
are JSON: `MM3_SERVER__ALLOWED_HOSTS='["mm3.lan"]'`. The app does not read a `.env` file itself; export the
variables in your shell or process manager (see `.env.example`).

## Settings reference
| Setting (YAML path) | Env var | Default | Notes |
|---|---|---|---|
| `server.host` | `MM3_SERVER__HOST` | `127.0.0.1` | Non-loopback values print a warning; also list the hostnames you will browse to in `allowed_hosts`. |
| `server.port` | `MM3_SERVER__PORT` | `8765` | 1-65535. |
| `server.allowed_hosts` | `MM3_SERVER__ALLOWED_HOSTS` | `[]` | Extra `Host` header values accepted; `127.0.0.1` and `localhost` are always allowed. Anything else gets HTTP 400 (DNS-rebinding defence). |
| `vault.path` | `MM3_VAULT__PATH` | unset | Your Obsidian vault root. |
| `vault.output_subfolder` | `MM3_VAULT__OUTPUT_SUBFOLDER` | `Meetings/{yyyy}/` | Where notes are written inside the vault. |
| `vault.templates_subfolder` | `MM3_VAULT__TEMPLATES_SUBFOLDER` | `MeetingMaster3/templates/` | User templates inside the vault. |
| `transcription.model` | `MM3_TRANSCRIPTION__MODEL` | `auto` | `auto` uses the hardware recommendation (Phase 05); wired into the pipeline in Phase 06. |
| `transcription.diarize` | `MM3_TRANSCRIPTION__DIARIZE` | `true` | Placeholder until Phase 06. |
| `hardware.profile` | `MM3_HARDWARE__PROFILE` | `auto` | `auto`, `cpu`, `vram8`, `vram16` or `vram24plus`. Declares the hardware profile instead of detecting it; see [`hardware.md`](hardware.md). |
| `llm.default_backend` | `MM3_LLM__DEFAULT_BACKEND` | `ollama` | Name of the backend used for notes. If no backend is configured under that name and it is `ollama`, a local Ollama at `http://127.0.0.1:11434` is used. |
| `llm.backends.<name>` | `MM3_LLM__BACKENDS__<NAME>__<FIELD>` | none | One entry per backend; fields below. See [`llm-backends.md`](llm-backends.md). |
| `llm.backends.<name>.kind` | | required | `ollama`, `openai_compat`, `openrouter`, `openai` or `bedrock`. |
| `llm.backends.<name>.base_url` | | per kind | Ollama: `http://127.0.0.1:11434`. OpenRouter and OpenAI have presets. Required for `openai_compat`, include the `/v1`. |
| `llm.backends.<name>.api_key` | | unset | Secret. For `openrouter` and `openai` it falls back to `secrets.openrouter_api_key` / `secrets.openai_api_key`. |
| `llm.backends.<name>.region` / `.profile` | | `us-east-1` / unset | Bedrock only. Credentials come from the AWS chain (profile, `AWS_*` env) or `secrets.aws_*`. |
| `llm.backends.<name>.default_model` | | unset | Model id used when a job does not pick one. |
| `llm.backends.<name>.params` | | `{}` | Extra options: Ollama `options` (e.g. `top_p`, `num_ctx`), OpenAI-style body fields, or Bedrock `additionalModelRequestFields`. |
| `llm.backends.<name>.headers` | | `{}` | Extra HTTP headers, e.g. OpenRouter `HTTP-Referer` and `X-Title` (off by default; nothing identifying is sent unless you add it). |
| `llm.backends.<name>.context_window` | | auto | Override when the server cannot report the model's context size (Bedrock never does). Unknown windows are treated as 8192 tokens. |
| `llm.backends.<name>.consent_remembered` | | `false` | Remember cloud-egress consent for this backend (skips the per-job prompt). |
| `privacy.audio_retention` | `MM3_PRIVACY__AUDIO_RETENTION` | `days` | `forever`, `days` or `delete_after_write` (ADR-0006). Enforced from Phase 04. |
| `privacy.audio_retention_days` | `MM3_PRIVACY__AUDIO_RETENTION_DAYS` | `90` | Used when retention is `days`. |
| `privacy.voiceprints_enabled` | `MM3_PRIVACY__VOICEPRINTS_ENABLED` | `false` | Opt-in biometric store (Phase 07). |
| `secrets.hf_token` | `MM3_SECRETS__HF_TOKEN` | unset | Hugging Face token for gated pyannote models. |
| `secrets.openrouter_api_key` | `MM3_SECRETS__OPENROUTER_API_KEY` | unset | |
| `secrets.openai_api_key` | `MM3_SECRETS__OPENAI_API_KEY` | unset | |
| `secrets.aws_access_key_id` / `secrets.aws_secret_access_key` | `MM3_SECRETS__AWS_ACCESS_KEY_ID` / `MM3_SECRETS__AWS_SECRET_ACCESS_KEY` | unset | |

Secrets are never printed or returned by the API unmasked, and are redacted from logs.

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
privacy:
  audio_retention: days
  audio_retention_days: 90
```
