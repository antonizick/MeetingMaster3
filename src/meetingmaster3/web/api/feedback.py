"""Feedback API: ratings on notes and sections, stored locally, exportable. No telemetry."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from meetingmaster3.errors import MM3Error
from meetingmaster3.feedback.store import FeedbackStore, to_csv
from meetingmaster3.storage.db import Database
from meetingmaster3.web.api.templates import _body

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


def feedback_store(request: Request) -> FeedbackStore:
    db: Database | None = getattr(request.app.state, "db", None)
    if db is None:
        raise MM3Error(
            "E_RUNNER_DOWN",
            "The database is not open.",
            "Restart MeetingMaster3 with `mm3 serve`.",
            status_code=503,
        )
    return FeedbackStore(db)


class FeedbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mm3_id: str = Field(min_length=1, max_length=64)
    rating_kind: str
    value: int
    comment: str = Field(default="", max_length=4000)
    template_id: str | None = Field(default=None, max_length=64)
    backend: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=200)
    section_id: str | None = Field(default=None, max_length=64)


@router.post("", status_code=201)
async def add_feedback(request: Request) -> dict[str, Any]:
    body = await _body(request, FeedbackBody)
    return feedback_store(request).add(**body.model_dump()).to_dict()


@router.get("")
async def list_feedback(request: Request, mm3_id: str | None = None) -> dict[str, Any]:
    store = feedback_store(request)
    rows = store.for_meeting(mm3_id) if mm3_id else store.all()
    return {"feedback": [r.to_dict() for r in rows]}


@router.get("/export", response_model=None)
async def export_feedback(request: Request, format: str = "json") -> Response:
    """All ratings, for the user's own analysis: ``?format=json`` (default) or ``csv``."""
    rows = feedback_store(request).all()
    if format == "csv":
        return Response(
            to_csv(rows),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="mm3-feedback.csv"'},
        )
    if format != "json":
        raise MM3Error("E_BODY_INVALID", "Unknown export format.", "Use json or csv.", 422)
    return JSONResponse(
        {"feedback": [r.to_dict() for r in rows]},
        headers={"Content-Disposition": 'attachment; filename="mm3-feedback.json"'},
    )


@router.delete("/{feedback_id}")
async def delete_feedback(request: Request, feedback_id: int) -> dict[str, bool]:
    return {"deleted": feedback_store(request).delete(feedback_id)}
