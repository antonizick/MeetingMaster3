# Threat model

MeetingMaster3 turns meeting recordings into transcripts and notes on the user's own machine. This
document says what we protect, from whom, where the trust boundaries are, which controls exist (each
linked to its code and a test), and what risk remains. It was written in Phase 15 (2026-10-11)
together with a security review; the scan results and the control → test table are in
[`SECURITY.md`](../SECURITY.md). Update it when a boundary, an asset or a control changes.

## 1. System and assumptions
- **Single user, one machine.** `mm3 serve` (FastAPI) listens on `127.0.0.1:8765`. There is no login:
  anyone who can send HTTP requests to the port is the user. Network exposure is therefore the main
  control (S1), and browser-origin defences (S2) stop other websites from acting as the user.
- **Same-user local processes are trusted.** A process running as the same OS user can already read
  the vault, the config file and the database; defending against it is out of scope (SECURITY.md
  "Scope"). Other OS users are kept out by file modes (`0700` folders, `0600` secrets and uploads).
- **Inputs that are not trusted:** uploaded media, every file in the vault (notes, transcripts,
  templates; a vault may be synced or shared), text spoken in a meeting (it reaches an LLM), LLM
  output, responses from LLM providers and model hubs, and any website open in the user's browser.
- **Deployment variants:** native (`uv run mm3 serve`) and Docker Compose (GPU or CPU image,
  loopback-only port, optional host-network override; ADR-0026).

## 2. Assets
| Asset | Where | Why it matters |
|---|---|---|
| Meeting audio | Job folders (`<data>/jobs/<id>/`), optional vault copy | Raw, highly personal content |
| Transcripts and notes | Vault; working copies in job folders and `<data>/reviews/` | Same content in text form |
| Voiceprints | `mm3.db` (`voiceprints`, `voiceprint_embeddings`); per-job `speaker_embeddings.json` until confirmation | Biometric data (S7) |
| API keys, HF token, proxy credentials | `config.yaml` (`0600`) or environment | Billing and account access (S5) |
| Vault integrity | The user's Obsidian vault | The user's own notes must never be clobbered or escaped (S4) |
| Availability of the app | The local process | A hostile file should not hang or crash it |

## 3. Trust boundaries and data flows
```
 Browser tab(s) ──HTTP── [B1] ── mm3 server ──[B2]── filesystem: vault, app data, config
   (other sites too)                 │  │
                                     │  ├──[B3]── LLM providers (Ollama local; Bedrock/OpenRouter/... cloud)
                                     │  ├──[B4]── model hubs (Hugging Face, download.pytorch.org)
                                     │  └──[B5]── ffmpeg/ffprobe, ML libraries (parse untrusted media)
                                     └──[B6]── Docker: container ↔ host (volumes, port, GPU)
```

## 4. Threats and mitigations
Each row names the control, the code that implements it and a test that proves it. "Residual"
records what remains. STRIDE letters: **S**poofing, **T**ampering, **R**epudiation, **I**nformation
disclosure, **D**enial of service, **E**levation of privilege.

### B1 Browser ↔ local server
| ID | Threat (STRIDE) | Mitigation | Code | Test |
|---|---|---|---|---|
| T-NET | Another device on the LAN uses the app (I, T, E) | Bind `127.0.0.1` by default; any other host needs an explicit setting and prints a loud warning; Docker publishes `127.0.0.1:8765` only | `config/settings.py` `ServerSettings`, `cli.py` `serve`, `docker/compose.yaml` | `tests/unit/test_security_controls.py::test_s1_default_bind_is_loopback_and_other_hosts_warn` |
| T-REBIND | DNS rebinding: a website's own hostname resolves to 127.0.0.1 and reads the API (I) | Host-header allowlist (`127.0.0.1`, `localhost`, `server.allowed_hosts`), outermost middleware | `app.py` (`TrustedHostMiddleware`) | `tests/unit/test_web.py::test_foreign_host_rejected`, `::test_configured_host_allowed` |
| T-CSRF | A website makes the browser POST to the app (T) | Double-submit token (`mm3_csrf` cookie `SameSite=Strict` = `X-CSRF-Token` header) on every non-GET; a present `Origin` must be a trusted host; no CORS headers, so a cross-origin request cannot even set the header without a failed preflight | `web/security.py` `CSRFMiddleware` | `tests/unit/test_web.py::test_post_without_token_rejected`, `::test_post_with_wrong_token_rejected`, `::test_post_with_foreign_origin_rejected`, `::test_csrf_cookie_is_samesite_strict`; per-router: `tests/unit/web/test_review.py::test_every_action_needs_csrf`, `tests/unit/web/test_pages.py::test_mutating_routes_need_csrf`, `tests/unit/jobs/test_jobs_api.py::test_state_changing_routes_need_csrf`, `tests/unit/web/test_settings_ui.py::test_save_without_csrf_header_is_refused` |
| T-READ | A website reads data cross-origin (I) | Same-origin policy plus `Cross-Origin-Resource-Policy: same-origin`, `X-Content-Type-Options: nosniff`, no JSONP, no CORS | `web/security.py` | `tests/unit/test_web.py::test_security_headers` |
| T-XSS | Transcript text, model output or a vault note injects script into the UI (T, I, E) | markdown-it with `html: False`, images off, links limited to http(s)/mailto/relative; Jinja autoescape everywhere else; CSP `script-src 'self'` with no inline script, no `eval` (Alpine CSP build, HTMX `allowEval: false`); `[mm:ss]` buttons built from escaped text | `web/render.py`, `web/security.py` (CSP), `templates/*.html` | `tests/unit/test_fuzz.py::test_rendered_markdown_never_contains_live_markup` (Hypothesis), `tests/unit/web/test_pages.py::test_preview_is_sanitised_and_confined_to_the_vault`, `::test_panel_escapes_untrusted_text`, `::test_vendored_assets_and_csp` |
| T-CLICK | Clickjacking (T) | `frame-ancestors 'none'`, `X-Frame-Options: DENY` | `web/security.py` | `tests/unit/test_web.py::test_security_headers` |
| T-GETSIDE | A cross-site GET changes state (T) | State changes are POST/DELETE only. Residual: `GET /open/note?path=` adds an existing MM3 note to the Meetings list (harmless) | routers in `web/` | `tests/unit/web/test_settings_ui.py` (settings cannot be edited by GET) |
| T-DLNAME | A crafted `name` on the recording download injects a header or picks a file (T, E) | `name` is only a suggested file name: `sanitize_title` strips separators and control characters, the suffix comes from the stored file, the header is RFC 5987-encoded by Starlette; the file always comes from the validated job id (Phase 15c) | `web/views.py` `audio_download_name`, `web/api/jobs.py` | `tests/unit/web/test_review.py::test_recording_size_and_download` |
| T-TASK | Another page or site reads or cancels a running switch/regenerate task (I, T) | Task ids are random (64 bits) and bound to the note's id; reads need the localhost Host/Origin checks; cancel is a POST with the CSRF token; results hold only note text the page already shows (Phase 15c) | `web/review.py` `_task_of`, `review/progress.py` | `tests/unit/web/test_review.py::test_switch_task_lifecycle` |

### B2 Server ↔ filesystem (vault, app data, config)
| ID | Threat | Mitigation | Code | Test |
|---|---|---|---|---|
| T-PATH | Path traversal or a symlink makes the app read or write outside the vault (T, I) | `confine()` resolves symlinks and refuses absolute paths, `~`, NUL, `..` escapes; repeated at write time; pickers skip symlinks out; job ids are UUIDs, job folders must resolve inside the jobs folder | `vault/paths.py`, `vault/io.py`, `vault/picker.py`, `jobs/files.py`, `exporting.py` `locate` | `tests/unit/test_vault.py::test_path_escape_rejected`, `::test_symlink_escape_rejected`, `tests/unit/test_fuzz.py::test_confined_paths_never_leave_the_vault` (Hypothesis), `tests/unit/test_review_logic.py::test_browse_cannot_escape_the_vault`, `tests/unit/test_exporting.py::test_locate_refuses_escapes_and_non_notes`, `tests/unit/jobs/test_ingest.py::test_job_paths_are_confined` |
| T-CLOBBER | A write replaces or truncates the user's file (T) | Atomic temp-file-and-rename writes; no overwrite without `overwrite=True`; hard-link "create if absent"; ` (2)` suffixes; SHA-256 check before saving an edited note (ADR-0025); the optional audio copy never replaces a file (Phase 15 fix); the readable transcript replaces only its own file (same `mm3-id` and `mm3-kind`), otherwise takes `(Transcript 2)`…; "Update older notes" archives each note and re-checks `mm3-id` + SHA-256 right before writing (Phase 15a) | `vault/io.py`, `vault/naming.py`, `review/save.py`, `jobs/vault_audio.py`, `vault/readable.py`, `review/upgrade.py` | `tests/unit/test_vault.py::test_atomic_write_never_overwrites_by_default`, `::test_atomic_write_cleans_up_on_failure`, `tests/unit/web/test_review.py::test_save_detects_external_modification`, `tests/unit/jobs/test_vault_audio.py::test_an_existing_file_is_never_replaced_and_reruns_are_idempotent`, `tests/unit/test_readable_transcript.py::test_writer_refreshes_its_own_file_and_never_replaces_others`, `tests/unit/test_upgrade.py::test_edit_during_the_run_is_never_overwritten` |
| T-VAULT | A hostile vault file (note, transcript, template) hangs or crashes the parsers, or forges structure (D, T) | Strict section-marker parser (R11); YAML loaded with `SafeLoader`, alias expansion capped at 10 000 nodes and construction errors turned into frontmatter errors (Phase 15 fixes: a 550-byte alias bomb used to hang `parse_note`/`parse_template`, `date: 2026-13-45` used to raise HTTP 500); templates capped at 256 KiB and strictly validated; template text only ever becomes prompt text | `markdown/frontmatter.py` (`load_untrusted`), `markdown/sections.py`, `templates/schema.py` | `tests/unit/test_fuzz.py` (all parsers, Hypothesis), `::test_yaml_alias_bomb_in_a_note_is_refused_fast`, `::test_yaml_alias_bomb_in_a_template_is_reported_fast`, `::test_unbuildable_values_are_frontmatter_errors`, `::test_python_tags_are_never_constructed`, `tests/unit/templates/test_schema.py::test_size_limit_and_unreadable` |
| T-MARKER | Spoken text or model output forges section markers or closes the hidden data comment (T) | Data block is ASCII JSON with `<`/`>` escaped; model output has marker lines stripped; editor refuses markers typed into sections; the readable transcript (Phase 15a) turns `& < > "` into entities and backslash-escapes Markdown/Obsidian syntax, so spoken words cannot become HTML, links, embeds, tags, comments or markers, and the file is never parsed back | `markdown/transcript_format.py`, `templates/postprocess.py`, `markdown/editing.py`, `markdown/readable_transcript.py` | `tests/unit/test_editing.py::test_marker_in_a_section_is_refused`, `tests/unit/test_sections.py::test_marker_failure_modes`, `tests/unit/templates/test_postprocess.py::test_clean_section`, `tests/unit/test_readable_transcript.py::test_spoken_text_can_never_become_markup` |
| T-PERM | Other OS users read meetings or secrets (I) | Data, config and model folders `0700`; uploads `0600`; `config.yaml` `0600`; `mm3.db` `0600`. Artifacts inside job folders are `0644` but unreachable through the `0700` folder | `config/paths.py`, `config/settings.py` `save`, `audio/ingest.py` `save_stream` | `tests/unit/test_settings.py::test_save_is_0600_and_roundtrips`, `::test_paths_xdg_and_overrides`, `tests/unit/jobs/test_ingest.py::test_job_paths_are_confined`, `::test_save_stream_enforces_limit_and_cleans_up` |
| T-RENAME | Renaming a meeting (Phase 15d) writes across the whole vault: a crafted note, symlink or race makes it overwrite or delete a file that is not the meeting's, write outside the vault, lose the user's edits to a linking note, or leave a half-renamed meeting (T, D) | Every source and target path goes through `confine()`; symlinked notes and folders are skipped and a symlinked source is refused; new names are created with the hard-link "create if absent" write and an existing target is refused; the SHA-256 of every file read is checked again right before writing and old names are removed only if their SHA-256 is unchanged; only link targets are rewritten (code spans skipped); a copy of every changed text file and a journal go to `<data>/rename-backups/` (`0700`, outside the vault) before the first write; one DB commit point, with roll-back before it and roll-forward after it, at once on an error and at start-up after a crash; the backlink scan is bounded (20 000 notes, 2 MB each) and runs off the event loop; the preview is escaped (S3) and both routes need CSRF (S2) | `review/retitle.py`, `vault/links.py`, `web/review.py` `retitle_*` | `tests/unit/test_retitle.py::test_a_collision_is_refused`, `::test_a_change_after_the_preview_stops_the_rename`, `::test_recovery_after_a_crash_at_every_step`, `::test_an_error_while_writing_is_rolled_back_at_once`, `tests/unit/test_links.py::test_symlinked_notes_are_ignored`, `::test_links_in_code_are_not_links`, `::test_the_scan_is_bounded`, `tests/unit/web/test_retitle_web.py::test_retitle_routes_need_csrf`, `::test_preview_escapes_the_title` |
| T-DISK | Disk full or a vault unmounted mid-job corrupts files (D, T) | Atomic writes (a failed write leaves the old file and no temp file); the write stage is idempotent and resumable; a missing vault fails the job with a remediation hint and resumes later | `vault/io.py`, `templates/stages.py` `WriteStage` | `tests/unit/test_vault.py::test_atomic_write_cleans_up_on_failure`, `tests/unit/templates/test_stages.py::test_missing_vault_fails_then_resumes`, `::test_write_is_idempotent_after_a_crash` |

### B3 Server ↔ LLM providers
| ID | Threat | Mitigation | Code | Test |
|---|---|---|---|---|
| T-EGRESS | Transcript text reaches a cloud provider without consent (I) | A backend is local only on loopback/`host.docker.internal`; a cloud backend pauses the job for consent before the first request (per job, rememberable per backend); declining sends nothing. **Phase 15 fixes:** a consent answer is consumed by the run that reads it and resume clears stale answers, so a "yes" given while switching to a local model cannot approve a later cloud backend; a reprocessed meeting does not inherit consent | `llm/consent.py`, `templates/stages.py` `_check_consent`, `jobs/runner.py` `resume`, `web/review.py` `reprocess` | `tests/unit/templates/test_stages.py::test_cloud_backend_pauses_for_consent`, `::test_declined_consent_fails_without_sending`, `::test_a_local_switch_never_leaves_consent_for_a_later_cloud_backend`, `::test_resume_from_a_stage_clears_its_stale_answers`, `tests/unit/templates/test_generator.py::test_consent_is_enforced_before_any_call`, `tests/unit/web/test_review.py::test_reprocess_and_missing_audio`; live (Phase 15g, real Bedrock): `tests/integration/test_live_cloud.py::test_declined_consent_sends_nothing` |
| T-PROMPT | Prompt injection: someone in the meeting says "ignore previous instructions…", or a template carries hostile prompt text (T) | The LLM has **no tools and no actions**: its output only becomes section text, which is post-processed (markers stripped, headings demoted), rendered sanitised (T-XSS) and reviewed by the user before saving. No file path, URL, command or setting is ever derived from model output. Worst case: wrong or rude text in the user's own note. The owner guard only un-assigns task owners | `templates/generator.py`, `templates/postprocess.py`, `templates/cues.py` | `tests/unit/templates/test_postprocess.py::test_clean_section`, `tests/unit/test_fuzz.py::test_rendered_markdown_never_contains_live_markup`; review: no tool/function-calling parameters exist in `llm/` (Phase 15 grep) |
| T-KEYLEAK | API keys leak via logs, errors, pages, exports (I) | `SecretStr`; masked in every dump (keys, the `secrets` section and, since Phase 15, non-attribution header values and passwords in base URLs); write-only in the UI; log redaction filter (registered values plus `hf_`/`sk-`/AWS/bearer patterns, also in tracebacks); provider errors are mapped to MM3 errors without request bodies | `config/settings.py` `dump_masked`/`register_secrets`, `logging.py`, `web/settings_fields.py`, `llm/_http.py` | `tests/unit/test_settings.py::test_backend_headers_and_url_credentials_are_masked_and_redacted`, `tests/unit/web/test_settings_ui.py::test_no_secret_appears_in_any_rendered_page`, `tests/unit/llm/test_registry_api.py::test_key_is_redacted_from_logs`, `tests/unit/test_logging.py`, `tests/unit/test_security_controls.py::test_s5_s6_a_whole_job_leaks_no_secret_and_contacts_no_host` |
| T-PROVIDER | A malicious or compromised endpoint returns huge or hostile output (D, T) | Timeouts and retry caps; output is treated like any model output (T-PROMPT, T-XSS) | `llm/_http.py`, `llm/*.py` | `tests/unit/llm/` |

### B4 Server ↔ model hubs
| ID | Threat | Mitigation | Code | Test |
|---|---|---|---|---|
| T-TELEMETRY | Libraries phone home (I) | pyannote metrics, HF Hub telemetry and `DO_NOT_TRACK` forced before ML imports; cached models load with `local_files_only`/from the snapshot folder; `transcription.offline` forbids downloads. Re-run the socket audit after any ML dependency upgrade | `transcription/models.py` `disable_telemetry`, `transcription/stages.py` | `tests/unit/transcription/test_models.py`, `tests/unit/test_security_controls.py::test_s5_s6_a_whole_job_leaks_no_secret_and_contacts_no_host`; GPU socket audit `tests/integration/test_transcription_gpu.py::test_cached_models_make_no_network_calls` (local, `gpu`+`models`) |
| T-MODEL | A malicious model file executes code when loaded (E) | Models come only from fixed, well-known repositories (faster-whisper CTranslate2 weights, `pyannote/speaker-diarization-community-1`, torchaudio wav2vec2). `transcription_model` is pattern-checked but may name another HF repo or a local folder (single-user choice). Residual: torch 2.8 / transformers 4.57 advisories about loading untrusted checkpoints (ADR-0014; blocked by WhisperX pins) | `transcription/models.py`, `jobs/models.py` `MODEL_NAME_PATTERN` | `tests/unit/transcription/test_models.py` |
| T-HFTOKEN | The HF token leaks (I) | Sent only to `huggingface.co` in a header, only for gated downloads and the explicit *Test* button; registered for redaction | `transcription/models.py`, `transcription/hf_check.py` | `tests/unit/transcription/test_models.py::test_hf_token_sources_and_redaction`, `tests/unit/web/test_settings_ui.py::test_hf_token_test_reports_without_leaking` |
| T-AWSKEY | The AWS access key pair for Bedrock leaks or is over-privileged (I, E) | **Phase 15g:** entered only in Settings → Language models (write-only `secret` fields, never echoed, "Remove" clears both halves, a half pair is refused so it cannot silently fall back to another credential source), CSRF-protected POST, stored in `config.yaml` (`0600`) and registered for log redaction (plus the `AKIA…`/`aws_secret_access_key` patterns); `MM3_SECRETS__AWS_*` outrank the file and the page says so. Used only to sign requests to Bedrock in the configured region. The guide prescribes a dedicated IAM user whose policy allows only invoking and listing models (and first-use Marketplace subscription), never root keys, and explains rotation and revocation | `web/settings_fields.py` `AWS_FIELDS`, `web/settings_ui.py` `save_aws_keys`, `llm/registry.py` `_bedrock`, `docs/user-guide/llm-backends.md` | `tests/unit/web/test_settings_ui.py::test_aws_keys_are_write_only_and_reach_bedrock`, `::test_aws_keys_need_both_halves_and_clear_removes_both`, `::test_aws_env_override_is_flagged`, `::test_aws_env_keys_outrank_the_file`, `::test_aws_keys_never_reach_the_log`; live: `tests/integration/test_live_cloud.py::test_wrong_bedrock_keys_are_an_auth_error` |

### B5 Untrusted media parsing
| ID | Threat | Mitigation | Code | Test |
|---|---|---|---|---|
| T-MEDIA | A crafted upload exploits ffmpeg, or makes it read other files or the network (E, I) | Upload streamed to a server-named `0600` file with a size limit; ffprobe must find an audio stream; ffmpeg/ffprobe run without a shell, from an argument list with `--`, `-nostdin` and timeouts; **Phase 15:** `-protocol_whitelist file` on every input, playlist/list demuxers (`hls`, `concat`, `image2`, `tee`, ...) refused, errors no longer echo server paths. Verified that ffmpeg 9 (host) and 5.1 (Debian image) also refuse HLS/concat tricks themselves. Residual: ffmpeg memory-safety bugs (16 open Debian CVEs in 5.1 at the time of writing); in Docker the process runs non-root, `cap_drop: ALL`, read-only root | `audio/ingest.py`, `web/api/jobs.py` | `tests/unit/jobs/test_ingest.py::test_probe_refuses_playlists_and_indirection`, `::test_media_commands_only_allow_local_files`, `::test_probe_rejects_non_audio`, `tests/unit/jobs/test_jobs_api.py::test_upload_size_limit` |
| T-DOS | Very long or corrupt audio exhausts memory or never finishes (D) | Upload size limit (2 GB default), transcode timeout of real time plus 120 s, cooperative cancel between chunks, OOM retry with a smaller batch then model; measured 3-hour fake job memory in `docs/PERFORMANCE.md` | `audio/ingest.py`, `transcription/stages.py`, `jobs/runner.py` | `tests/unit/jobs/test_ingest.py::test_subprocess_timeout`, `tests/unit/transcription/test_stages.py` |

### Voiceprints (S7, crosses B2)
| ID | Threat | Mitigation | Code | Test |
|---|---|---|---|---|
| T-BIO | Voice signatures are stored, exported or kept without consent (I) | Off by default; computed only when on; stored only for speakers ticked "remember"; never in the vault, logs or API; physical deletion (`secure_delete`, WAL truncate); two-step wipe. **Phase 15 fixes:** "Export all app data" no longer includes a waiting job's `speaker_embeddings.json`; retention pruning and the wipe delete those files too | `speakers/store.py`, `speakers/stages.py`, `exporting.py`, `jobs/retention.py` | `tests/unit/speakers/test_store.py::test_wipe_removes_everything_from_the_database_file`, `::test_public_view_never_contains_vectors`, `tests/unit/speakers/test_speakers_api.py::test_delete_and_two_step_wipe`, `tests/unit/test_exporting.py::test_export_all_has_no_secrets_audio_or_voiceprints`, `tests/unit/jobs/test_retention.py::test_stale_unfinished_jobs_are_pruned_too` |

Matching quality (not a confidentiality issue, but a wrong suggestion attributes words to the wrong
person): threshold 0.6 and margin 0.1 were measured on two recordings in Phase 07 (same voice
0.85–0.97, different voices ≤ 0.43). Suggestions are only suggestions: the user confirms every name.

### B6 Container ↔ host
| ID | Threat | Mitigation | Code | Test |
|---|---|---|---|---|
| T-ESCAPE | A compromised app process escapes the container (E) | Non-root uid 1000, `cap_drop: ALL`, `no-new-privileges`, read-only root with tmpfs `/tmp`, tini as PID 1, only the vault bind-mounted, GPU via the NVIDIA toolkit (no `--privileged`); no curl or system pip in the runtime image (Phase 15) | `docker/Dockerfile`, `docker/compose*.yaml` | CI `docker.yml` (image builds, no weights or `.env` in the image, healthcheck); `trivy` scan (SECURITY.md) |
| T-HOSTNET | The host-network override removes port isolation (I) | The app then binds `127.0.0.1` itself (`MM3_SERVER__HOST`); docs warn never to combine it with a non-loopback bind | `docker/compose.host-network.yaml`, `docs/user-guide/install-docker.md` | Manual check with `ss -ltnp` (Phase 14) |
| T-OLLAMA | Users expose Ollama on `0.0.0.0` to let the container reach it (I) | Docs recommend the host-network override instead and explain the risk | `docs/user-guide/install-docker.md` | n/a (documentation) |

### Supply chain (S8)
| ID | Threat | Mitigation | Where | Check |
|---|---|---|---|---|
| T-SUPPLY | A vulnerable or malicious dependency (E, I) | `uv.lock` with hashes; `pip-audit` in CI for the base set **and** the `ml` extra with documented ignores (Phase 15); Dependabot; gitleaks pre-commit and CI; vendored JS with versions and licences recorded; Docker base images pinned by digest/tag | `.github/workflows/ci.yml`, `.github/dependabot.yml`, `.pre-commit-config.yaml`, `THIRD_PARTY_NOTICES.md` | CI jobs; Phase 15 scans in SECURITY.md |

## 5. Residual risks (accepted, with reasons)
| Risk | Why accepted | Revisit |
|---|---|---|
| No authentication | Single-user local app; loopback bind and Host/CSRF checks; remote use only through an SSH tunnel | If multi-user or LAN use is ever supported |
| torch 2.8.0, transformers 4.57.6 and nltk 3.10.3 advisories (`ml` extra) | Blocked by WhisperX 3.8.6 (`torch~=2.8.0`, `huggingface-hub<1.0`). The advisories concern loading untrusted checkpoints or using APIs the app does not call (`save_pretrained`, NLTK downloader); the app loads only fixed models. Ignored by id in CI | Every WhisperX release (ADR-0014) |
| ffmpeg memory-safety bugs | Parsing arbitrary media is the product. Mitigated by the protocol whitelist, demuxer refusal, timeouts and container hardening; Debian 12 had no fixed packages at the time of the scan | Debian security updates; rebuild the image regularly |
| Unfixed Debian 12 OS package CVEs in the image | No fixed versions exist; most affect binaries the app never runs (util-linux mount, curl was removed) | Rebuild on Debian point releases; consider a Debian 13 base (roadmap) |
| Model files from Hugging Face are trusted | The model ids are fixed and well known; weights are cached after first download | If users can add arbitrary models in the UI |
| Prompt injection changes note text | No tools or actions; user reviews every note | If agentic features (tool use) are ever added |
| A stage stuck in native code cannot be killed | Stages run in threads; cancel is cooperative. A hung job needs an app restart | If it is seen in practice |
| IPv6 loopback bind (`::1`) is unusable | Starlette's Host check cannot parse `[::1]`; requests are refused (fails closed). Use `127.0.0.1` | Low priority |
| GET side effect on `/open/note` (adds to Meetings) | Only for existing MM3 notes in the vault; no content is exposed cross-origin | Low priority |

## 6. How to keep this current
- New HTTP route: decide GET vs POST (state changes are never GET); add it to the CSRF test of its
  router; confine any path parameter with `vault.paths.confine`.
- New file written to the vault: `atomic_write_text(..., vault_root=)`, never overwrite by default.
- New secret-bearing setting: `SecretStr` or covered by `dump_masked`/`register_secrets`, plus a test.
- New network call: document it in `docs/PRIVACY.md`; cloud calls go through `enforce_consent`.
- After upgrading ML dependencies: re-run `pip-audit` for the `ml` extra and the GPU socket audit
  (`uv run pytest -m "gpu and models" tests/integration`).
