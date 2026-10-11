# Security Policy

## Supported versions
No version has been released yet (pre-alpha). Once releases exist, the latest minor release will be
supported with security fixes.

## Reporting a vulnerability
Please report vulnerabilities **privately**; do not open a public issue.

- Preferred: GitHub private vulnerability reporting (Security tab → "Report a vulnerability") once the
  repository is published.
- Email fallback: _maintainer contact to be confirmed by the project owner before first publication
  (tracked for Phase 16)._

Please include what you found, steps to reproduce, and the version or commit. Do not attach private
audio or personal data.

## Scope
In scope: the MeetingMaster3 application and its Docker packaging, including the web server, file
handling, vault writes, secret handling and any data leaving the machine.
Out of scope: vulnerabilities in third-party models or dependencies (report upstream), and issues
that require an attacker who already has local shell access as the same user.

## Security model summary
The full baseline is in [`docs/SPECIFICATION.md`](docs/SPECIFICATION.md) section 15.3.

- **Local only by default.** The server binds `127.0.0.1`. Binding elsewhere needs an explicit
  setting and shows a warning. There is **no authentication in the MVP** (single user), so network
  exposure is the main control.
- **Browser-origin attacks.** Host-header allowlist (DNS rebinding), CSRF token and Origin check on
  state-changing requests, `SameSite=Strict` cookies, sanitised rendering and a strict CSP (all
  assets are vendored; no CDN).
- **Filesystem.** Vault writes are confined to the configured vault root (no `..` or symlink
  escapes) and are atomic. Uploads are streamed straight into a per-job folder under app data
  (`jobs/<uuid>/original.<ext>`, mode `0600`, folder `0700`) with a server-generated name; the client
  filename only contributes an allowlisted extension and a display name. Job ids are validated UUIDs
  and job folders must resolve inside the jobs folder.
- **Untrusted media.** Uploads are size-limited while streaming (`audio.max_upload_mb`), probed with
  `ffprobe` and rejected unless they contain audio. ffmpeg/ffprobe run without a shell, from an
  argument list with `--` before the path, `-nostdin` and a timeout. ffmpeg's parsers remain attack
  surface (Phase 15 threat model).
- **Secrets.** API keys and the Hugging Face token come from environment variables or a `0600`
  config file; they are never logged, never returned unmasked, never written to the vault. The HF
  token is only used to download the gated diarization model.
- **Cloud egress consent.** Cloud LLM backends are clearly badged and need explicit confirmation on
  first use per job (`llm.consent.enforce_consent` raises `E_CONSENT_REQUIRED` for any non-local backend unless the job has `cloud_consent` or the backend has `consent_remembered`). A backend counts as local only when its host is loopback or `host.docker.internal`; a LAN or remote Ollama is treated as cloud. LLM request and response bodies are never logged above DEBUG and are redacted even there. API keys in `config.yaml` are `0600`, masked in every API response, and registered with the log redaction filter. No telemetry, ever.
- **Voiceprints are biometric data.** Opt-in, local only, never written to the vault, listable and
  deletable.
- **Supply chain.** Locked dependencies, `pip-audit` in CI, Dependabot, licence inventory.

### Implemented in Phase 02 (web middleware and config)
| Control | Where | Behaviour |
|---|---|---|
| Loopback bind | `mm3 serve`, `server.host` | Default `127.0.0.1`. A non-loopback host prints a loud warning; you must also list the hostnames you browse to in `server.allowed_hosts`. |
| Host allowlist | `TrustedHostMiddleware` (outermost) | Only `127.0.0.1`, `localhost` and `server.allowed_hosts`; anything else gets HTTP 400. |
| Security headers | `web/security.py` | CSP `default-src 'self'; frame-ancestors 'none'; ...`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Cross-Origin-Resource-Policy: same-origin`. |
| CSRF | `web/security.py` | Double-submit: `mm3_csrf` cookie (`SameSite=Strict`) must equal the `X-CSRF-Token` header on POST/PUT/PATCH/DELETE; a present `Origin` must be a trusted host. Failures return 403. HTMX pages send the token via `hx-headers` (Phase 10). |
| Secrets in config | `config/settings.py` | `SecretStr`, masked in `mm3 config show` and API dumps; `config.yaml` written atomically with mode `0600` in a `0700` directory. |
| Log redaction | `logging.py` | Registered secret values plus `hf_...`, `sk-...`, AWS key and bearer-token patterns are replaced with `[REDACTED]`. |
| Repo hygiene | pre-commit, CI | gitleaks, audio-file guard, large-file guard, `pip-audit`. |

Known limitations to revisit in Phase 15: the CSP will need adjusting for Alpine.js (Phase 10; its
standard build needs `'unsafe-eval'`, so the CSP-safe build is preferred), and CSRF currently accepts the
header only (no form-field fallback).

### Implemented in Phase 03 (vault filesystem, S4)
| Control | Where | Behaviour |
|---|---|---|
| Vault root check | `vault/paths.py` `resolve_vault_root` | Must exist, be a folder and be writable; otherwise a blocking error with remediation. |
| Path confinement | `vault/paths.py` `confine`, `ensure_folder` | Targets are resolved with symlinks followed and must stay inside the vault root. Absolute paths, `~`, NUL bytes, `..` escapes and symlinks leaving the vault are refused (`vault_path_escape`). |
| Atomic writes | `vault/io.py` `atomic_write_text` | Temp file in the same folder, fsync, atomic move, folder fsync; the temp file is removed on success and failure. The confinement check is repeated at write time. |
| No silent overwrite | `vault/io.py`, `vault/naming.py` | Existing files are replaced only with an explicit `overwrite=True`; new names get ` (2)`, ` (3)`; the no-overwrite move uses a hard link so a concurrently created file is not clobbered. |
| Filename safety | `vault/naming.py` `sanitize_title` | R13 characters, control characters and bidi-override/zero-width characters are removed; length is capped at 150 UTF-8 bytes. |
| Hostile upload names and paths | `audio/ingest.py`, `jobs/files.py` | Server-chosen file names, extension allowlist, UUID job ids, symlink-escape checks for job folders and artifacts. |
| Oversized or malformed media | `web/api/jobs.py`, `audio/ingest.py` | Streaming size limit (413), ffprobe validation (422), subprocess timeouts, partial files removed. |
| Hostile transcript text | `markdown/transcript_format.py` | The hidden data block is ASCII JSON with `<` and `>` escaped, so spoken text cannot close the HTML comment; section content containing marker-like lines is refused. |

### Implemented in Phase 06 (transcription)
| Control | Where | Behaviour |
|---|---|---|
| Hugging Face token (S5) | `transcription/models.py` `hf_token` | Read from `secrets.hf_token` / `MM3_SECRETS__HF_TOKEN` / `HF_TOKEN`, registered with the log redaction filter, passed explicitly to pyannote and Hugging Face, never logged or returned. Only needed to download the gated model; a cached model loads without it. |
| No telemetry (S6) | `transcription/models.py` `disable_telemetry` | pyannote.audio 4 sends OpenTelemetry traces to `otel.pyannote.ai` by default. `PYANNOTE_METRICS_ENABLED=false`, `HF_HUB_DISABLE_TELEMETRY=1` and `DO_NOT_TRACK=1` are forced before any ML library loads. |
| Minimal network use | `transcription/stages.py` | Cached whisper models load with `local_files_only`, and a cached diarization pipeline is loaded from its folder, so a job makes no network calls (verified with a socket audit hook). `transcription.offline` forbids downloads entirely. |
| ML library logs | `transcription/engine.py` | WhisperX's own stdout handler is suppressed so its records go through the app's redaction filter; library INFO chatter is silenced (transcript text is not logged at INFO). |
| Job options | `jobs/models.py` | `transcription_model` and `language` are pattern-checked; `compute_type`, `batch_size` and `on_non_english` are enumerated or bounded. A model name may be a local folder path (single-user app; Phase 15 threat model). |

## Data the app stores and where
_To be completed as phases land. Final version in Phase 15._

| Data | Location | Added in | Leaves the machine? |
|---|---|---|---|
| Notes and companion transcripts | Your Obsidian vault | Phase 03/09 | Only if your vault syncs |
| Job audio and stage artifacts | `$XDG_DATA_HOME/meetingmaster3/jobs/<job-id>/` (folders `0700`): upload and 16 kHz WAV while processing, then Opus only, pruned after `privacy.audio_retention_days` (90) unless pinned | Phase 04 (done) | No |
| Job state, feedback, voiceprints | `$XDG_DATA_HOME/meetingmaster3/mm3.db` (mode `0600`) | Phase 04 (done)/07 | No |
| Config and secrets | `$XDG_CONFIG_HOME/meetingmaster3/config.yaml` (mode `0600`, directory `0700`) | Phase 02 (done) | No |
| Model weights | `$XDG_CACHE_HOME/meetingmaster3/models` (`MM3_MODELS_DIR`, folder `0700`) | Phase 06 (done) | Downloaded in, never out |
| Transcript text sent to an LLM | Selected backend | Phase 08 | **Only for a cloud backend you confirmed** |
