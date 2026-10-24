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
The full baseline is in [`docs/MM3_SPECIFICATION.md`](docs/MM3_SPECIFICATION.md) section 15.3. The threat model
(assets, trust boundaries, STRIDE per boundary, mitigations mapped to code and tests, residual risks)
is [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md).

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
- **Untrusted text imports** (Phase 15k). Imported transcripts and AI conversations (`POST /api/imports`) are
  size-limited while streaming (`importing.max_mb`, 10 MB), stored under a server-chosen name, decoded as
  strict UTF-8 (binary refused) and parsed by pure-Python parsers before a job exists; the parsers raise
  only `MM3Error` (fuzzed with Hypothesis). See T-IMPORT in the threat model.
- **Grok share links** (Phase 15l). The only outbound request to a non-LLM website: one HTTPS `GET` to the fixed host
  `grok.com`, built from a share id validated before the job exists (no generic URL fetcher, so no SSRF), with no redirects,
  cookies or credentials, TLS verification, size and time limits. See T-SHARE-FETCH and T-SHARE-JSON in the threat model.
- **Secrets.** API keys and the Hugging Face token come from environment variables or a `0600`
  config file; they are never logged, never returned unmasked, never written to the vault. The HF
  token is only used to download the gated diarization model.
- **Cloud egress consent.** Cloud LLM backends are clearly badged and need explicit confirmation on
  first use per job (`llm.consent.enforce_consent` raises `E_CONSENT_REQUIRED` for any non-local backend unless the job has `cloud_consent` or the backend has `consent_remembered`). A backend counts as local only when its host is loopback or `host.docker.internal`; a LAN or remote Ollama is treated as cloud. LLM request and response bodies are never logged above DEBUG and are redacted even there; a provider's own reason for a 4xx error is shown to the user redacted and capped at 300 characters. API keys in `config.yaml` are `0600`, masked in every API response, and registered with the log redaction filter. No telemetry, ever.
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

Phase 10 tightened the CSP and settled the CSRF question (see below). Phase 11 added the review
workspace without loosening the CSP (no editor library, ADR-0024). Phase 15 reviewed the CSP and the
workspace's endpoints (threat model T-XSS, T-CSRF, T-PATH): unchanged, no findings.

### Implemented in Phase 10 (web UI, S2/S3)
| Control | Where | Behaviour |
|---|---|---|
| Strict CSP | `web/security.py` | `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self' blob:; connect-src 'self'; ...`. No inline script or style, no `eval`: Alpine.js is the CSP build (`@alpinejs/csp`), HTMX is configured with `allowEval: false`, `allowScriptTags: false`, `selfRequestsOnly: true` and no injected indicator styles (`<meta name="htmx-config">`). `blob:` is only for reading the duration of the chosen file in the browser. |
| CSRF in the UI | `base.html`, `app.js` | `<body hx-headers>` adds `X-CSRF-Token` to every HTMX request and the upload `XMLHttpRequest` reads it from a meta tag. There are no plain HTML forms that post, so the header-only check stands and no form-field fallback was added. |
| Sanitised rendering (S3) | `web/render.py` | The preview uses markdown-it with `html: False` (raw HTML is escaped), images disabled, links limited to `http`, `https`, `mailto` and in-page/relative ones (external links get `target=_blank`, `rel=noopener noreferrer`; links into the app open in place since Phase 15j); frontmatter and section-marker comments are hidden. Jinja autoescape is on for everything else, including transcript-derived text. |
| Preview confinement (S4) | `web/pages.py` | `/preview?path=` opens only an absolute `.md` file that resolves (symlinks included) inside the vault root. |
| No third-party requests | tests, e2e | The Playwright smoke test fails if the browser requests any host other than the app. |
| Errors | `errors.py` | HTMX requests get an escaped toast fragment; browsers get the error page; API clients get JSON. |

### Implemented in Phase 11 (review workspace)
| Control | Where | Behaviour |
|---|---|---|
| Same CSP, no new script sources | `static/js/transcript.js`, `static/js/review.js` | Plain scripts from `'self'`; the editor is `<textarea>`s (ADR-0024). Page data is a `<script type="application/json">` block (Jinja `tojson`, not executed). Sizes and the splitter use CSSOM (`element.style`), which `style-src 'self'` allows; templates contain no `style` attributes. |
| CSRF | `web/review.py` | Every workspace action is a `POST`/`DELETE` with the `X-CSRF-Token` header (tested for each route). |
| Vault confinement (S4) | `web/review.py`, `review/workspace.py`, `vault/picker.py` | Every action names the note by its vault-relative path; it is re-resolved with `confine()` and must be a non-archived MM3 note whose `mm3-id` equals the workspace's. The picker lists folders inside the vault only (symlinks out are skipped; `..` and absolute paths are refused). "Link this transcript" accepts only a companion with the same `mm3-id` in the note's own folder. |
| Renaming a meeting across the vault (S2, S3, S4) | `review/retitle.py`, `vault/links.py`, `web/review.py` | "Title & date…" and `mm3 meetings rename` (Phase 15d, ADR-0040) confine every source and target path to the vault, refuse symlinks and existing target names, rewrite only link targets in other notes, re-check the SHA-256 of every file right before writing, and remove old names only if unchanged. A journal and copies of every changed file go to `<data>/rename-backups/` (`0700`, never the vault) first; an interrupted rename is rolled back or completed at the next start. Preview HTML is escaped; both routes need the CSRF token. Threat model T-RENAME. |
| Atomic writes and lost-update protection | `review/save.py` | Saves, appends, template switches and renames write atomically and only if the file's SHA-256 still equals the version the editor was opened from; otherwise the user sees a diff and decides (ADR-0025). A change to `mm3-id` is refused. |
| Marker protection (R11) | `markdown/editing.py` | Marker lines are re-inserted by the server and never taken from the browser; a marker typed into a section is refused; marker-like changes to user text need an explicit confirmation. |
| Sanitised rendering (S3) | `web/render.py` | The workspace preview and the diffs use the same renderer (raw HTML escaped); `[mm:ss]` links are generated from escaped text. Diffs and transcript text are Jinja-escaped. |
| Cloud consent (S6) | `templates/regenerate.py`, `review/switch.py` | Regeneration and template switches with a cloud backend need the per-request consent box (or remembered consent); without it nothing is sent. |
### Implemented in Phase 12 (settings, template library, feedback, export)
| Control | Where | Behaviour |
|---|---|---|
| Write-only secrets (S5) | `web/settings_fields.py`, `settings_ui.py` | No page, partial or API response contains a stored secret: password inputs have no `value`, a stored key shows "Saved", an empty field means unchanged and an explicit checkbox clears it. A test posts secrets and greps every rendered page. `config.yaml` is written atomically with mode `0600`. |
| All-or-nothing validation | `config/editing.py` | A settings form is validated as a whole against the pydantic models before anything is applied or written, so a bad value never leaves the app half-changed. Settings cannot be edited through any GET route. |
| Vault confinement (S4) | `settings_ui.py`, `templates/manage.py` | The templates and attachments folders are confined to the vault; template files are addressed by a strict file-name pattern (no separators, no `..`) and written atomically with `vault_root` confinement. Deleting or resetting a template archives the old copy first. |
| Voiceprint wipe | `settings_ui.py` | Deleting every voiceprint needs a second request carrying a single-use, five-minute token issued by the first (the same token store as the API). |
| Grok share download | `importing/fetch.py`, `importing/grok_share.py` | One `GET https://grok.com/rest/app-chat/share_links/<id>` per share-link import, only when the user starts it; the id is validated by an exact parser and the URL is built by the app; redirects refused; no cookies; streamed under `importing.max_mb`. |
| Hugging Face token test | `transcription/hf_check.py` | Two HTTPS requests to `huggingface.co`, only on pressing *Test*; the token goes in a header and never into the result, a log line or the page. Refused in offline mode. |
| Exports contain no secrets | `exporting.py` | "Export all app data" writes `settings.json` masked and omits the voiceprint tables and all audio; a test asserts no secret value, voiceprint name or audio is in the zip. Export paths are confined to the vault; feedback CSV neutralises spreadsheet formulas. |
| No telemetry | UI, `docs/PRIVACY.md` | Ratings are stored in the local SQLite database and leave only when you download the export. |
| Opening folders | `settings_ui.py` | "Open the config folder" runs `xdg-open` with our own path as a fixed argument list (no shell), and is unavailable in Docker. |

### Implemented in Phase 14 (container posture, S1/S5)
| Control | Where | Behaviour |
|---|---|---|
| Loopback-only publication | `docker/compose.yaml` | The app listens on `0.0.0.0` *inside* the container (Docker's bridge needs that; the CLI prints its no-auth warning) but the port is published as `127.0.0.1:8765:8765`, so only the host can connect. Verified with `ss -ltnp`. Do not change it to `0.0.0.0:8765`; use an SSH tunnel for remote access. |
| Host network override | `docker/compose.host-network.yaml` | Lets the app reach an Ollama on `127.0.0.1`. The app then binds `127.0.0.1` itself (`MM3_SERVER__HOST`), but Docker's port isolation is gone: never combine it with a non-loopback bind. |
| Least privilege | `Dockerfile`, compose | Non-root uid/gid 1000, read-only root filesystem with a `tmpfs` /tmp, `cap_drop: ALL`, `no-new-privileges`, tini as PID 1. The vault is the only host folder mounted. |
| No secrets or models in images | `.dockerignore`, CI | `.env`, audio, tests and docs are excluded from the build context; CI fails if weights or `.env` files are in the image. Secrets arrive at run time (`.env` via compose `env_file`, or Settings, stored `0600` in the `/config` volume). |
| Ollama exposure | `docs/user-guide/install-docker.md` | The host-network option needs no change to Ollama. Making Ollama listen on `0.0.0.0` exposes an unauthenticated API to the LAN unless firewalled, so it is documented as the less safe choice. A bundled Ollama is published on `127.0.0.1` only. |
| GPU access | NVIDIA Container Toolkit | Grants the container the GPU only; no `--privileged`. |

### Phase 15: security review, scans and the control → test map
**Scans (2026-10-11/12).** Outputs were summarised here and in the Phase Log; raw outputs are not committed.

| Scanner | Scope | Result |
|---|---|---|
| `pip-audit` 2.10 | Locked base dependencies | No known vulnerabilities |
| `pip-audit` | `ml` + `bedrock` extras | 18 advisories in torch 2.8.0, transformers 4.57.6, nltk 3.10.3: all blocked by WhisperX 3.8.6's pins; accepted (ADR-0014, residual risk in the threat model), ignored by id in CI |
| `bandit` 1.8.6 | `src/` (17 131 lines) | 0 high; 4 medium, all false positives: 3 × B608 (SQL built from allowlisted column/table names, never user input), 1 × B704 (`Markup` around markdown-it output with HTML disabled); 10 low (subprocess with fixed argument lists, `random` for fixtures) |
| `gitleaks` 8.28 | Full git history (52 commits) and the working tree | 1 hit: an obviously fake key in a unit test (`sk-secret-key-123456`), now allowlisted in `.gitleaks.toml`. No real secrets |
| `trivy` 0.67 | `meetingmaster3:gpu` and `:cpu` images | Python: only the ADR-0014 packages above (system `pip` 25.0.1, 5 medium, removed from the image). OS (Debian 12): 8 critical / 253 high / 492 medium, none with a fixed package. Moving the base to Debian 13 (ADR-0027) cut this to 1 critical / about 215 high / about 297 medium, still none fixable; `curl` was removed too. No secrets in either image |
| Manual review + `/code-review high` | Whole codebase, focused on the HTTP surface, file writes, consent, voiceprints, exports | Findings below |

**Findings fixed (high and medium).**

| Severity | Finding | Fix | Test |
|---|---|---|---|
| High | **Cloud consent bypass (S6).** Choosing "use a local model" at the cloud question stored `{"consent": true}`, which a later retry with a cloud backend consumed, sending the transcript without asking | The consent check consumes every answer; resume clears answers of the stages it resets; reprocessed meetings do not inherit consent | `tests/unit/templates/test_stages.py::test_a_local_switch_never_leaves_consent_for_a_later_cloud_backend`, `::test_resume_from_a_stage_clears_its_stale_answers`, `tests/unit/web/test_review.py::test_reprocess_and_missing_audio` |
| Medium | **Voice embeddings in "Export all app data" (S7).** A job waiting for speaker confirmation (or cancelled there) kept `speaker_embeddings.json`, and the export zipped it although it promises no voiceprints | Excluded from exports; deleted by retention pruning and by "delete all voiceprints" | `tests/unit/test_exporting.py::test_export_all_has_no_secrets_audio_or_voiceprints`, `tests/unit/jobs/test_retention.py::test_stale_unfinished_jobs_are_pruned_too`, `tests/unit/speakers/test_speakers_api.py::test_delete_and_two_step_wipe` |
| Medium | **YAML alias bomb (DoS).** A 550-byte note or template frontmatter hung the parser for minutes; `date: 2026-13-45` raised HTTP 500 | Vault YAML has capped alias expansion (10 000 nodes); construction errors are frontmatter errors | `tests/unit/test_fuzz.py` (Hypothesis fuzzing of every parser) |
| Medium | **Proxy credentials in clear (S5).** Backend `headers` (e.g. `Authorization`) and passwords in `base_url` were not masked in exports, `mm3 config show` or the API, nor redacted from logs | Masked and registered for redaction (attribution headers excepted) | `tests/unit/test_settings.py::test_backend_headers_and_url_credentials_are_masked_and_redacted` |
| Medium | **Silent overwrite in the vault (S4).** The optional audio copy used `os.replace` onto `<attachments>/<note>.opus` | Non-clobbering hard-link placement with ` (2)` suffixes; idempotent on re-runs | `tests/unit/jobs/test_vault_audio.py::test_an_existing_file_is_never_replaced_and_reruns_are_idempotent` |
| Medium | **Reprocessed audio escaped retention (R8, privacy).** Stored as `upload.<ext>`, which retention did not know | Stored as `original.<ext>` | `tests/unit/web/test_review.py::test_reprocess_and_missing_audio` |
| Medium (hardening) | **Media parsing could be pointed elsewhere.** ffmpeg 5.1/9 already refuse HLS/concat tricks with our server-chosen names, but nothing in the app enforced it | `-protocol_whitelist file` on every ffmpeg/ffprobe input; playlist and list demuxers refused; errors no longer echo server paths | `tests/unit/jobs/test_ingest.py::test_probe_refuses_playlists_and_indirection`, `::test_media_commands_only_allow_local_files` |
| Medium (image) | `pip` and `curl` in the runtime image with known CVEs | Removed (healthcheck uses Python); base moved to Debian 13 | trivy rescan (above) |

**Low findings recorded, not changed.** IPv6 loopback bind (`::1`) is refused by the Host check (fails
closed; use `127.0.0.1`). `GET /open/note` adds an existing MM3 note to the Recent list (harmless
cross-site side effect). The CSRF `Origin` check compares host names, not ports (the token check is
the control; a cross-origin page cannot set the header). `JobRunner.describe()` rebuilds the pipeline
on every poll (efficiency, roadmap). A stage stuck in native code cannot be killed (threads).

**Control → test map (S1-S8, spec §15.3).** Each control has at least one automated test; the threat
model links every mitigation to its code.

| Control | What is verified | Tests |
|---|---|---|
| S1 Network exposure | Default bind `127.0.0.1`; any other host prints the no-auth warning; Docker publishes loopback only | `tests/unit/test_security_controls.py::test_s1_default_bind_is_loopback_and_other_hosts_warn`, `tests/unit/test_settings.py::test_defaults`, `tests/unit/web/test_settings_ui.py::test_privacy_save_and_bind_host_warning` |
| S2 Browser-origin attacks | Host allowlist (DNS rebinding), CSRF token and Origin on every state-changing route, `SameSite=Strict` | `tests/unit/test_web.py` (`test_foreign_host_rejected`, `test_post_without_token_rejected`, `test_post_with_wrong_token_rejected`, `test_post_with_foreign_origin_rejected`, `test_csrf_cookie_is_samesite_strict`), per-router CSRF tests in `tests/unit/web/test_review.py`, `test_pages.py`, `test_settings_ui.py`, `tests/unit/jobs/test_jobs_api.py` |
| S3 Output rendering | Sanitised Markdown and escaped transcript text; strict CSP; no third-party requests | `tests/unit/test_fuzz.py::test_rendered_markdown_never_contains_live_markup`, `tests/unit/web/test_pages.py::test_preview_is_sanitised_and_confined_to_the_vault`, `::test_panel_escapes_untrusted_text`, `::test_vendored_assets_and_csp`, `tests/unit/test_readable_transcript.py::test_spoken_text_can_never_become_markup` (vault output, Phase 15a); every e2e test fails on a request to another host |
| S4 Filesystem | Vault confinement (`..`, symlinks, absolute, `~`, NUL), atomic non-clobbering writes, hostile vault files | `tests/unit/test_vault.py`, `tests/unit/test_fuzz.py::test_confined_paths_never_leave_the_vault`, `tests/unit/test_review_logic.py::test_browse_cannot_escape_the_vault`, `tests/unit/jobs/test_vault_audio.py`, `tests/unit/jobs/test_ingest.py::test_job_paths_are_confined`, `tests/unit/test_readable_transcript.py::test_writer_refreshes_its_own_file_and_never_replaces_others`, `tests/unit/test_upgrade.py::test_edit_during_the_run_is_never_overwritten` (Phase 15a) |
| S5 Secrets | `0600` config; masked everywhere; write-only UI; redacted logs; no secret in vault, job folders, logs or exports after a whole job | `tests/unit/test_security_controls.py::test_s5_s6_a_whole_job_leaks_no_secret_and_contacts_no_host`, `tests/unit/test_settings.py::test_save_is_0600_and_roundtrips`, `::test_backend_headers_and_url_credentials_are_masked_and_redacted`, `tests/unit/web/test_settings_ui.py::test_no_secret_appears_in_any_rendered_page`, `tests/unit/test_logging.py` |
| S6 Cloud egress consent, no telemetry | Consent before any cloud request, per job, never reused; telemetry off; a whole job contacts only loopback | `tests/unit/templates/test_stages.py` (consent tests), `tests/unit/templates/test_generator.py::test_consent_is_enforced_before_any_call`, `tests/e2e/test_qa_flows.py::test_cloud_consent_dialog_can_switch_to_a_local_model`, `tests/unit/test_security_controls.py::test_s5_s6_a_whole_job_leaks_no_secret_and_contacts_no_host`, GPU: `tests/integration/test_transcription_gpu.py::test_cached_models_make_no_network_calls` |
| S7 Voiceprints | Opt-in, never in API/logs/vault/exports, physical deletion, two-step wipe, per-job embeddings removed | `tests/unit/speakers/test_store.py` (`test_wipe_removes_everything_from_the_database_file`, `test_public_view_never_contains_vectors`, `test_wipe_tokens_are_single_use_and_expire`), `tests/unit/speakers/test_speakers_api.py::test_delete_and_two_step_wipe`, `tests/unit/test_exporting.py::test_export_all_has_no_secrets_audio_or_voiceprints` |
| S8 Supply chain | Locked deps, `pip-audit` of base and `ml` extra, gitleaks, licence policy | CI `ci.yml` (`pip-audit`, `scripts/pip_audit_ml.sh`, gitleaks job), `scripts/gen_third_party.py --check`, `.pre-commit-config.yaml` |

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
| Known dependency advisories | `ml` extra | torch 2.8.0, transformers 4.57.6 and nltk 3.10.3 have published advisories, mostly about loading malicious model or checkpoint files. They cannot be upgraded while WhisperX 3.8.6 pins torch 2.8 and huggingface-hub below 1.0 (ADR-0014). The app loads model files only from fixed, well-known sources. Do not point `transcription.model` at untrusted repositories or folders. Phase 15: still blocked (WhisperX 3.8.6 is the latest release); CI now audits the `ml` extra with these advisories ignored by id (`scripts/pip_audit_ml.sh`), so a new one fails. |
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

### Implemented in Phase 15j (Ask-AI agent, S3, S4, S6)
| Control | Where | Behaviour |
|---|---|---|
| Ask-AI consent (S6) | `ask/pipeline.py` `enforce_ask_consent`, `ask/service.py` | A cloud backend answers only with this question's consent (the Ask-AI page's box, `mm3 ask --allow-cloud`) or the backend's own `ask_consent_remembered`; note writing's `consent_remembered` does not count. Checked before the task starts and before the first call: a refused question sends nothing. Threat model T-ASK-EGRESS. |
| Prompt injection contained | `ask/pipeline.py`, `ask/prompts.py` | The agent only reads the index and vault and writes one new answer note; meeting text is fenced as material, not instructions; counts, dates, links and attendees are computed from the files; unknown people, quotes and links are dropped; model tables are removed. Threat model T-ASK. |
| Answer notes (S3, S4) | `ask/notes.py`, `web/ask_ui.py` | Written atomically inside the vault (confined answers folder, never overwriting); HTML tags in model text and the question are defused for Obsidian; the app renders answers with the sanitising renderer. Delete removes a note only if its `mm3-answer-id` matches; Delete and Forget need the CSRF token. Threat model T-ANSWERS. |

## Data the app stores and where
Final inventory (Phase 15); the user-facing version is [`docs/PRIVACY.md`](docs/PRIVACY.md).

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
| Review workspace working copies | `$XDG_DATA_HOME/meetingmaster3/reviews/<mm3-id>/` (folder `0700`): the last 5 opened versions of the note (`base-<sha256>.md`), the unsaved draft (`draft.json`, removed on save) and a pending template switch | Phase 11 (done) | No |
| Per-meeting voice embeddings (voiceprints on) | Job folder `speaker_embeddings.json` until speaker confirmation; deleted then, with the audio by retention, or by "delete all voiceprints"; never exported | Phase 07, Phase 15 | No |
| Feedback ratings | `mm3.db` `feedback` table | Phase 12 | Only in an export you download |
| Optional audio copy | Vault attachments folder (`privacy.copy_audio_to_vault`, off by default) | Phase 12 | Only if your vault syncs |
| Logs | stderr of `mm3 serve` (secrets redacted, no transcript text at INFO) | Phase 02 | No |
