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
- **Voiceprints are biometric data.** Opt-in (off by default), local only, never written to the
  vault, logs or API responses, listable and deletable, physically erased on delete.
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

Phase 10 tightened the CSP and settled the CSRF question (see below). Still for Phase 15: review the
CSP once more with the review workspace (Phase 11) in place.

### Implemented in Phase 10 (web UI, S2/S3)
| Control | Where | Behaviour |
|---|---|---|
| Strict CSP | `web/security.py` | `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self' blob:; connect-src 'self'; ...`. No inline script or style, no `eval`: Alpine.js is the CSP build (`@alpinejs/csp`), HTMX is configured with `allowEval: false`, `allowScriptTags: false`, `selfRequestsOnly: true` and no injected indicator styles (`<meta name="htmx-config">`). `blob:` is only for reading the duration of the chosen file in the browser. |
| CSRF in the UI | `base.html`, `app.js` | `<body hx-headers>` adds `X-CSRF-Token` to every HTMX request and the upload `XMLHttpRequest` reads it from a meta tag. There are no plain HTML forms that post, so the header-only check stands and no form-field fallback was added. |
| Sanitised rendering (S3) | `web/render.py` | The preview uses markdown-it with `html: False` (raw HTML is escaped), images disabled, links limited to `http`, `https`, `mailto` and in-page/relative ones (`target=_blank`, `rel=noopener noreferrer`); frontmatter and section-marker comments are hidden. Jinja autoescape is on for everything else, including transcript-derived text. |
| Preview confinement (S4) | `web/pages.py` | `/preview?path=` opens only an absolute `.md` file that resolves (symlinks included) inside the vault root. |
| No third-party requests | tests, e2e | The Playwright smoke test fails if the browser requests any host other than the app. |
| Errors | `errors.py` | HTMX requests get an escaped toast fragment; browsers get the error page; API clients get JSON. |

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
| Known dependency advisories | `ml` extra | torch 2.8.0, transformers 4.57.6 and nltk 3.10.3 have published advisories, mostly about loading malicious model or checkpoint files. They cannot be upgraded while WhisperX 3.8.6 pins torch 2.8 and huggingface-hub below 1.0 (ADR-0014). The app loads model files only from fixed, well-known sources. Do not point `transcription.model` at untrusted repositories or folders. Tracked for Phase 15. |
| Job options | `jobs/models.py` | `transcription_model` and `language` are pattern-checked; `compute_type`, `batch_size` and `on_non_english` are enumerated or bounded. A model name may be a local folder path (single-user app; Phase 15 threat model). |

### Implemented in Phase 07 (speakers and voiceprints, S7)
| Control | Where | Behaviour |
|---|---|---|
| Opt-in | `privacy.voiceprints_enabled` (default `false`) | Off: no embeddings are computed, `VoiceprintStore` refuses every write (`E_VOICEPRINTS_DISABLED`) and stored voiceprints are not used for matching. A test asserts that no voiceprint rows are written. |
| Explicit enrollment | `speakers/stages.py` | Only speakers confirmed with `enroll: true` are stored; the per-meeting `speaker_embeddings.json` (job folder, `0700`) is deleted after confirmation. |
| No vectors outside the store | `speakers/store.py`, `web/api/speakers.py`, `cli.py` | The API and CLI return names, ids, counts and dates only; vectors are never logged or written to the vault. Logs never contain names of stored people. |
| Physical deletion | `storage/db.py` | `PRAGMA secure_delete = ON` for the whole database, and a `wal_checkpoint(TRUNCATE)` after voiceprint deletes. A test scans the database and WAL files after a wipe for the deleted vectors and names. |
| Wipe confirmation | `DELETE /api/voiceprints` | Two steps: `428 E_CONFIRM_REQUIRED` with a single-use token (5 minutes), then `?confirm=<token>`. Normal CSRF and Origin checks apply. `mm3 voiceprints wipe` asks interactively unless `--yes`. |
| Input validation | `speakers/stages.py` `normalise_answer` | Labels match `[A-Za-z0-9_-]{1,64}`, names are 1-200 characters (whitespace collapsed), person ids are UUIDs, unknown fields are refused (422); the API also refuses labels not in the meeting and deleted people. |
| Model isolation | `voiceprint_embeddings.model_id` | Embeddings are tagged with the model and a hash of its weights; different models are never compared. |
| Offline model load | `speakers/embeddings.py` | The WeSpeaker model loads from the cached diarization snapshot folder (no network); telemetry is disabled before pyannote is imported (verified with `HF_HUB_OFFLINE=1` in the GPU test). |

### Implemented in Phase 09 (templates and note generation)
| Control | Where | Behaviour |
|---|---|---|
| Cloud consent before any call (S6) | `templates/stages.py`, `templates/generator.py` | A cloud backend without consent pauses the job (`cloud_consent` question) before a single request; declining fails the job with nothing sent. `NoteGenerator` also calls `enforce_consent` before its first request, and `POST /api/notes/regenerate-section` returns 403 `E_CONSENT_REQUIRED` without `cloud_consent`. Consent is per backend: switching the job to another cloud backend asks again. |
| Vault confinement (S4) | `templates/loader.py`, `templates/regenerate.py`, `templates/stages.py` | The templates folder and the note path of a regeneration resolve inside the vault (`vault.paths.confine`); template files that are symlinks out of the vault are ignored. Notes and companions are written with `atomic_write_text(..., vault_root=)`, never overwriting. |
| Template files are untrusted input | `templates/schema.py` | Parsed with `yaml.safe_load`/`compose`, size-limited (256 KiB), strictly validated; an invalid template is reported, never executed. Template text only becomes prompt text. |
| Model output is untrusted | `templates/postprocess.py` | Marker-like lines and `mm3` HTML comments are stripped before a section is built (a model cannot forge section markers), headings demoted; the note is otherwise plain Markdown. Rendering it in the browser must sanitise it (S3, Phases 10/11). A transcript could contain instructions aimed at the model (prompt injection); the worst outcome is wrong note text in your own vault, which you review. Phase 15 threat model. |
| No transcript text in logs | `templates/generator.py` | Prompts and answers are not logged; the owner guard logs only the changed task line at INFO. |

## Data the app stores and where
_To be completed as phases land. Final version in Phase 15._

| Data | Location | Added in | Leaves the machine? |
|---|---|---|---|
| Notes and companion transcripts | Your Obsidian vault | Phase 03/09 | Only if your vault syncs |
| Job audio and stage artifacts | `$XDG_DATA_HOME/meetingmaster3/jobs/<job-id>/` (folders `0700`): upload and 16 kHz WAV while processing, then Opus only, pruned after `privacy.audio_retention_days` (90) unless pinned | Phase 04 (done) | No |
| Job state, feedback, voiceprints | `$XDG_DATA_HOME/meetingmaster3/mm3.db` (mode `0600`, `secure_delete` on) | Phase 04 (done)/07 (done) | No |
| Config and secrets | `$XDG_CONFIG_HOME/meetingmaster3/config.yaml` (mode `0600`, directory `0700`) | Phase 02 (done) | No |
| Model weights | `$XDG_CACHE_HOME/meetingmaster3/models` (`MM3_MODELS_DIR`, folder `0700`) | Phase 06 (done) | Downloaded in, never out |
| Transcript text sent to an LLM | Selected backend | Phase 08/09 (done) | **Only for a cloud backend you confirmed** |
| Generation checkpoints and drafts | Job folder: `notes.draft.md`, `generation.json`, `generate.partial.json`, `written.json` | Phase 09 (done) | No |
| Template install record | `$XDG_DATA_HOME/meetingmaster3/templates.installed.json` (file hashes only) | Phase 09 (done) | No |
