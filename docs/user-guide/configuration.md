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
| `llm.default_backend` | `MM3_LLM__DEFAULT_BACKEND` | `ollama` | Placeholder until Phase 08. |
| `llm.backends` | `MM3_LLM__BACKENDS` | `{}` | Per-backend options; filled in by Phase 08. |
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
server:
  port: 8765
vault:
  path: /home/you/Documents/Vault
privacy:
  audio_retention: days
  audio_retention_days: 90
```
