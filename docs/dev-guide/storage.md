# Storage: SQLite schema and migrations

App state lives in `<data>/mm3.db` (default `~/.local/share/meetingmaster3/mm3.db`, R3). The vault is
the source of truth for notes; the database holds job state, stage checkpoints and the recent-meetings
list. Later phases add voiceprints (Phase 07) and feedback (Phase 12). Code: `src/meetingmaster3/storage/`.

## Connection
`storage.db.Database` wraps one stdlib `sqlite3` connection shared by the event loop and the stage
worker threads (`check_same_thread=False`, guarded by a re-entrant lock). Settings: WAL journal,
`synchronous=NORMAL`, `foreign_keys=ON`, a 30 s busy timeout, autocommit with explicit
`BEGIN IMMEDIATE … COMMIT` in `Database.transaction()`. The file is `chmod 0600` (its folder is
`0700`). Another process (for example `mm3 jobs prune` while the server runs) can use the database at
the same time thanks to WAL. Why stdlib `sqlite3` and not SQLAlchemy: ADR-0013.

## Schema (version 1)
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

`RecentMeetingsRepository.touch()` upserts (keeping known values when an argument is empty);
`recent(limit)` lists newest first.

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

Example for Phase 07:
```python
MIGRATIONS.append(
    Migration(
        2,
        "voiceprints",
        sql="""
CREATE TABLE voiceprints (...);
CREATE TABLE voiceprint_embeddings (...);
""",
    )
)
```
(edit the list literal in `migrations.py` rather than appending at import time, so the order is
explicit).

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
