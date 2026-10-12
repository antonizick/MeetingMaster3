"""The rating widget's HTMX route. Pages embed ``partials/feedback.html`` with the ``fb`` variable
from :func:`meetingmaster3.feedback.context.feedback_context`."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from meetingmaster3.errors import MM3Error
from meetingmaster3.feedback.context import feedback_context
from meetingmaster3.web.api.feedback import feedback_store
from meetingmaster3.web.pages import render

router = APIRouter()


@router.post("/ui/feedback", response_class=HTMLResponse)
async def submit_feedback(request: Request) -> HTMLResponse:
    data = await request.form()
    form = {k: v for k, v in data.items() if isinstance(v, str)}
    try:
        value = int(form.get("value", ""))
    except ValueError as exc:
        raise MM3Error("E_FEEDBACK_INVALID", "Choose a rating.", "", 422) from exc
    section = form.get("section_id") or None
    store = feedback_store(request)
    store.add(
        form.get("mm3_id", ""),
        rating_kind="thumbs" if section else form.get("kind", "stars"),
        value=value,
        comment=form.get("comment", ""),
        template_id=form.get("template_id") or None,
        backend=form.get("backend") or None,
        model=form.get("model") or None,
        section_id=section,
    )
    fb = feedback_context(
        store,
        form["mm3_id"],
        template_id=form.get("template_id") or None,
        backend=form.get("backend") or None,
        model=form.get("model") or None,
        section_id=section,
        saved=True,
    )
    return render(request, "partials/feedback_saved.html", {"fb": fb})
