# Storage: SQLite schema and migrations

App state lives in `<data>/mm3.db` (default `~/.local/share/meetingmaster3/mm3.db`, R3). The vault is
the source of truth for notes; the database holds job state, stage checkpoints, the recent-meetings
list and the opt-in voiceprints (Phase 07). Phase 12 adds feedback. Code: `src/meetingmaster3/storage/`.

## Connection
`storage.db.Database` wraps one stdlib `sqlite3` connection shared by the event loop and the stage
worker threads (`check_same_thread=False`, guarded by a re-entrant lock). Settings: WAL journal,
`synchronous=NORMAL`, `foreign_keys=ON`, a 30 s busy timeout, autocommit with explicit
`BEGIN IMMEDIATE … COMMIT` in `Database.transaction()`, and `secure_delete=ON` (deleted rows are
overwritten, Phase 07); `Database.checkpoint()` runs `wal_checkpoint(TRUNCATE)` after sensitive deletes.
The file is `chmod 0600` (its folder is `0700`). Another process (for example `mm3 jobs prune` while the server runs) can use the database at
the same time thanks to WAL. Why stdlib `sqlite3` and not SQLAlchemy: ADR-0013.

## Schema (version 2)
### `jobs`
| Column | Type | Notes |
|---|---|---|
| `id` | TEXT PK | UUIDv4; also the job folder name. |
| `created_at`, `updated_at` | TEXT | ISO-8601 UTC, seconds. |
| `job_type` | TEXT | `meeting` (the only pipeline in the MVP). |
| `status` | TEXT | `queued`, `running`, `waiting_for_input`, `interrupted`, `failed`, `cancelled`, `written`. |
| `title`, `meeting_date` | TEXT | From the options or the filename. |
| `source_filename` | TEXT | The client's base name, for display only (never used as a path). |
| `audio_path` | TEXT | **File name inside the job folder** of the current audio (`original.<ext>`, later `audio.opus`); NULL once pruned. |
| `duration_seconds` | REAL | From ffprobe. |
| `settings_json` | TEXT | `JobOptions` as JSON (extra keys allowed). |
| `error_code`, `error_message`, `error_hint` | TEXT | The last failure (`MM3Error` fields). |
| `current_stage` | TEXT | Stage running or last run; NULL after `written`. |
| `written_at` | TEXT | When the job reached `written`. |
| `audio_pinned` | INTEGER | 1 = keep the audio regardless of retention. |
| `audio_expires_at` | TEXT | When the pruner will delete the audio (NULL = never). |
| `audio_pruned_at` | TEXT | When the audio was deleted (drives `E_AUDIO_EXPIRED`). |

Indexes: `status`, `audio_expires_at`.

### `job_stages`
Primary key `(job_id, stage)`; `job_id` references `jobs(id) ON DELETE CASCADE`.

| Column | Notes |
|---|---|
| `position` | Order in the pipeline (0-based). |
| `status` | `pending`, `running`, `waiting`, `completed`, `failed`, `cancelled`, `interrupted`. |
| `started_at`, `finished_at` | ISO-8601 UTC. |
| `artifact_path` | File name of the stage's artifact inside the job folder. |
| `attempt` | Attempts in the current run (retry hooks increase it). |
| `detail_json` | `{"message": …}`, `{"error": {...}}` or `{"input": {...}}` (the question while waiting). |

### `recent_meetings`
| Column | Notes |
|---|---|
| `note_path` | TEXT PK; vault-relative path of the note. |
| `transcript_path` | Vault-relative path of the companion transcript. |
| `mm3_id` | The note's `mm3-id`. |
| `title`, `date` | For the list. |
| `last_opened` | Sort key (written or re-opened). |
| `job_id` | Migration 4 (Phase 11): the job that wrote the note, so the review workspace finds its audio. `NULL` for notes opened from the vault picker that no job wrote; the workspace then looks for a job whose `written.json` has the same `mm3_id`. |

`RecentMeetingsRepository.touch()` upserts (keeping known values when an argument is empty);
`recent(limit)` lists newest first; `for_meeting(mm3_id)` lists the entries of one meeting
(paths are absolute in practice: the write stage and the workspace store resolved paths).

### `voiceprints` (migration 2, Phase 07)
Opt-in biometric data (S7); written only when `privacy.voiceprints_enabled` is true. Access goes through
`speakers.store.VoiceprintStore` only.

| Column | Notes |
|---|---|
| `person_id` | TEXT PK; UUID hex. |
| `display_name` | Confirmed name (whitespace collapsed, 1-200 characters). |
| `created_at`, `updated_at` | ISO-8601 UTC; `updated_at` = last enrollment ("last seen"). |
| `n_samples`, `total_seconds` | Embeddings stored and their seconds of speech (kept in sync on every add). |

### `voiceprint_embeddings` (migration 2)
| Column | Notes |
|---|---|
| `id` | INTEGER PK AUTOINCREMENT (newer = larger). |
| `person_id` | References `voiceprints` `ON DELETE CASCADE`. |
| `embedding` | BLOB, little-endian float32, L2-normalised (256 values for WeSpeaker ResNet34). |
| `model_id` | `<pipeline>/embedding@<16 hex of the weights' SHA-256>`; only equal ids are compared. |
| `source_job_id` | The job it came from; unique per `(person_id, model_id, source_job_id)`, so re-enrolling from one job replaces its sample. |
| `seconds` | Speech behind this embedding. |
| `created_at` | ISO-8601 UTC. |

Indexes: `(model_id, person_id)`; the unique index above. At most `speakers.max_embeddings_per_person`
(20) rows per person and model are kept, newest first.

### `schema_version`
`(version, name, applied_at)`, one row per applied migration.

## Migrations
`storage/migrations.py` holds `MIGRATIONS`, a list of `Migration(version, name, sql="", func=None)`.
`Database.open()` applies every pending migration in order, each in its own transaction together
with its `schema_version` row, so a failing migration leaves the database at the previous version.

Rules:
- **Append only.** Add `Migration(N + 1, "…")`; never edit, renumber or remove a shipped one. Versions
  must be `1..N` without gaps (checked).
- SQL is split into statements with `sqlite3.complete_statement`; use `func=` for data moves that
  need Python.
- A database newer than the code raises `E_DB_TOO_NEW` instead of guessing.
- Test a new migration from the previous version (`migrate(conn, MIGRATIONS[:N])`, then
  `migrate(conn)`), as `tests/unit/jobs/test_storage.py` does.

Example (migration 2, Phase 07): `Migration(2, "voiceprints (opt-in speaker recognition)",
sql=_V2_VOICEPRINTS)` added to the `MIGRATIONS` list literal (edit the literal rather than appending
at import time, so the order is explicit).

## Repositories
`storage/repositories.py`: `JobRepository` (`create`, `get`/`find`, `list_jobs`, `set_status` which
enforces the state machine atomically, `update`, `delete`), `StageRepository`
(`for_job`, `get`, `update`, `reset_from`, `mark_running_interrupted`) and `RecentMeetingsRepository`.
They return frozen dataclasses (`JobRecord`, `StageRecord`, `RecentMeeting`) with `to_dict()` for
the API.

## Backups and reset
Stop the server, then copy `mm3.db` (and `mm3.db-wal` if present) or run
`sqlite3 mm3.db ".backup backup.db"`. Deleting `mm3.db` and `jobs/` resets the app's job history;
notes in the vault are unaffected.
