"""Speaker confirmation for a job, and the voiceprint privacy controls.

``GET/POST /api/jobs/{id}/speakers`` show the diarized speakers (talk time, sample snippets,
suggestions) and accept the confirmed names; ``/api/voiceprints`` lists and deletes stored voices
(never their vectors). Deleting everything is a two-step call: ``DELETE /api/voiceprints`` answers
``428`` with a single-use ``confirm_token`` (valid 5 minutes) that the client sends back as
``?confirm=<token>``. State-changing routes pass the CSRF middleware (S2).
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Request

from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.files import check_job_id, job_dir
from meetingmaster3.jobs.models import StageStatus
from meetingmaster3.jobs.runner import JobRunner
from meetingmaster3.speakers.stages import (
    CONFIRMED_FILE,
    SPEAKERS_FILE,
    normalise_answer,
)
from meetingmaster3.speakers.store import WIPE_TOKEN_SECONDS, VoiceprintStore, WipeTokens
from meetingmaster3.storage.db import Database
from meetingmaster3.web.api.jobs import _json_body, get_runner

speakers_router = APIRouter(prefix="/api/jobs")
voiceprints_router = APIRouter(prefix="/api/voiceprints")


def _stage_status(runner: JobRunner, job_id: str, stage: str) -> StageStatus | None:
    try:
        return runner.stages.get(job_id, stage).status
    except KeyError:
        return None


def _read(path: Any) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


@speakers_router.get("/{job_id}/speakers")
async def get_speakers(request: Request, job_id: str) -> dict[str, Any]:
    """The speakers to confirm (``speakers.json``) and, once confirmed, the answer."""
    runner = get_runner(request)
    job = runner.jobs.get(check_job_id(job_id))
    folder = job_dir(runner.jobs_root, job.id)
    done = _stage_status(runner, job.id, "speaker_suggest") is StageStatus.COMPLETED
    data = _read(folder / SPEAKERS_FILE) if done else None
    if data is None:
        raise MM3Error(
            "E_SPEAKERS_NOT_READY",
            "The speakers of this meeting are not known yet.",
            "Wait until the job is waiting for speaker confirmation.",
            status_code=409,
        )
    waiting = _stage_status(runner, job.id, "await_speaker_confirmation") is StageStatus.WAITING
    return {
        "job_id": job.id,
        "status": job.status.value,
        "waiting": waiting,
        **data,
        "confirmed": _read(folder / CONFIRMED_FILE),
    }


@speakers_router.post("/{job_id}/speakers")
async def confirm_speakers(request: Request, job_id: str) -> dict[str, Any]:
    """Confirm names: ``{"<label>": {"name": ..., "person_id": ... | null, "enroll": bool}}``
    (a plain string is the name; ``{"speakers": {...}}`` is accepted too). Labels left out keep
    their placeholder. Two labels with the same person or name are merged. Resumes the job."""
    runner = get_runner(request)
    job = runner.jobs.get(check_job_id(job_id))
    body = await _json_body(request)
    mapping = body["speakers"] if set(body) == {"speakers"} else body
    answer = normalise_answer({"speakers": mapping})
    payload = _read(job_dir(runner.jobs_root, job.id) / SPEAKERS_FILE) or {}
    known = {s.get("label") for s in payload.get("speakers", [])}
    unknown = sorted(set(answer["speakers"]) - known)
    if unknown:
        raise MM3Error(
            "E_INPUT_INVALID",
            f"Unknown speaker label(s): {', '.join(unknown)}.",
            "Use the labels returned by GET /api/jobs/{id}/speakers.",
            status_code=422,
        )
    store = VoiceprintStore(runner.db, enabled=runner.settings.privacy.voiceprints_enabled)
    for label, entry in answer["speakers"].items():
        if entry["person_id"] and store.find(entry["person_id"]) is None:
            raise MM3Error(
                "E_PERSON_NOT_FOUND",
                f"Speaker {label}: the selected person is no longer stored.",
                "Pick another suggestion or type a name.",
                status_code=422,
            )
    runner.submit_input(job.id, answer)
    return runner.describe(job.id)


# -- voiceprints -----------------------------------------------------------------------------------


def _store(request: Request) -> VoiceprintStore:
    db: Database | None = getattr(request.app.state, "db", None)
    if db is None:
        raise MM3Error(
            "E_RUNNER_DOWN",
            "The database is not open.",
            "Restart MeetingMaster3 with `mm3 serve`.",
            status_code=503,
        )
    settings = request.app.state.settings
    return VoiceprintStore(db, enabled=settings.privacy.voiceprints_enabled)


def _wipe_tokens(request: Request) -> WipeTokens:
    tokens: WipeTokens | None = getattr(request.app.state, "voiceprint_wipe_tokens", None)
    if tokens is None:
        tokens = request.app.state.voiceprint_wipe_tokens = WipeTokens()
    return tokens


@voiceprints_router.get("")
async def list_voiceprints(request: Request) -> dict[str, Any]:
    """Stored people with sample counts and when they were last seen (no vectors)."""
    store = _store(request)
    return {"enabled": store.enabled, "people": [p.to_dict() for p in store.list_people()]}


@voiceprints_router.delete("/{person_id}")
async def delete_voiceprint(request: Request, person_id: str) -> dict[str, Any]:
    return {"deleted": _store(request).delete_person(person_id).to_dict()}


@voiceprints_router.delete("")
async def wipe_voiceprints(request: Request, confirm: str | None = None) -> dict[str, Any]:
    """Delete every stored voice. Without ``?confirm=<token>`` nothing is deleted: the answer is
    ``428`` with a fresh token in ``details.confirm_token``."""
    store = _store(request)
    tokens = _wipe_tokens(request)
    if not tokens.consume(confirm, time.monotonic()):
        people = store.count_rows()["voiceprints"]
        raise MM3Error(
            "E_CONFIRM_REQUIRED",
            f"This deletes every stored voice ({people} people) and cannot be undone.",
            "Send the request again with ?confirm=<confirm_token> within 5 minutes.",
            status_code=428,
            details={
                "confirm_token": tokens.issue(time.monotonic()),
                "people": people,
                "expires_in": int(WIPE_TOKEN_SECONDS),
            },
        )
    return {"deleted": store.wipe()}
