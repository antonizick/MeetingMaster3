"""The Search page (``/search``, Phase 15i, R30): meetings found by meaning and by words.

A plain GET form, so a search is a bookmarkable URL that works without JavaScript; with HTMX
only the results are swapped. Results are grouped by meeting (10 meetings per page) and every
passage is shown as a snippet whose text is escaped by the template (S3), with the matched
words highlighted. A note passage opens the meeting; a transcript passage opens it at that
moment (``#t=<seconds>``, read by ``static/js/transcript.js``).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from meetingmaster3.errors import MM3Error
from meetingmaster3.search.query import Hit, MeetingHits, SearchFilters
from meetingmaster3.web.pages import render
from meetingmaster3.web.paging import pager, paginate, parse_page

log = logging.getLogger(__name__)
router = APIRouter()

MEETINGS_PER_PAGE = 10
RESULT_PASSAGES = 100
"""Passages fetched per search; they are grouped into meetings, then paged."""
PASSAGES_SHOWN = 4
"""Passages listed under each meeting (the rest are counted)."""
MAX_QUERY = 500
MODE_LABELS = {
    "hybrid": "meaning + words",
    "meaning": "meaning only",
    "words": "words only",
    "none": "",
}


def _date(raw: str, label: str, errors: list[str]) -> str | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw).isoformat()
    except ValueError:
        errors.append(f"The {label} date is not a date (use YYYY-MM-DD); it was ignored.")
        return None


def meeting_link(mm3_id: str, note_path: str | None) -> str | None:
    """The meeting's review page (the note's path finds it even if it is not in Meetings)."""
    if not note_path:
        return None
    return f"/meetings/{quote(mm3_id, safe='')}?path={quote(note_path, safe='')}"


def hit_link(hit: Hit) -> str | None:
    """Where a passage opens: the meeting's review page, at the moment for a transcript."""
    url = meeting_link(hit.mm3_id, hit.note_path)
    if url and hit.kind == "transcript" and hit.start_s is not None:
        url += f"#t={int(hit.start_s)}"
    return url


def _meeting_view(m: MeetingHits) -> dict[str, Any]:
    return {
        "mm3_id": m.mm3_id,
        "title": m.title,
        "date": m.date,
        "count": len(m.hits),
        "link": meeting_link(m.mm3_id, m.note_path),
        "hits": [
            {"hit": h, "link": hit_link(h), "label": h.label()} for h in m.hits[:PASSAGES_SHOWN]
        ],
        "more": max(0, len(m.hits) - PASSAGES_SHOWN),
    }


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: str = "",
    date_from: str = Query("", alias="from"),
    date_to: str = Query("", alias="to"),
    person: str = "",
    results_page: str | None = None,
) -> HTMLResponse:
    q = q.strip()[:MAX_QUERY]
    person = person.strip()[:100]
    errors: list[str] = []
    filters = SearchFilters(
        date_from=_date(date_from, "from", errors),
        date_to=_date(date_to, "to", errors),
        people=(person,) if person else (),
    )
    params = {
        k: v
        for k, v in {
            "q": q,
            "from": date_from.strip(),
            "to": date_to.strip(),
            "person": person,
        }.items()
        if v
    }
    ctx: dict[str, Any] = {
        "active": "search",
        "q": q,
        "date_from": date_from.strip(),
        "date_to": date_to.strip(),
        "person": person,
        "errors": errors,
        "result": None,
        "meetings": [],
        "notice": None,
        "mode_label": "",
    }
    service = getattr(request.app.state, "search", None)
    if service is None:
        ctx["notice"] = "The search index is not running."
    elif not request.app.state.settings.search.enabled:
        ctx["notice"] = "Search is switched off."
    elif q:
        try:
            result = await service.query(q, limit=RESULT_PASSAGES, filters=filters)
        except MM3Error as exc:
            ctx["notice"] = f"{exc.message} {exc.hint}".strip()
        else:
            groups = result.group_by_meeting()
            pg = paginate(len(groups), parse_page(results_page), MEETINGS_PER_PAGE)
            ctx.update(
                result=result,
                mode_label=MODE_LABELS.get(result.mode, ""),
                total_meetings=len(groups),
                meetings=[_meeting_view(m) for m in groups[pg.offset : pg.offset + pg.size]],
                pager=pager(
                    pg,
                    param="results_page",
                    params=params,
                    href_base="/search",
                    hx_base="/search",
                    label="Results",
                ),
            )
    if service is not None:
        status = service.status()
        ctx["index"] = {
            "meetings": status["meetings"],
            "running": status["running"],
            "exists": status["exists"],
            "badge": status["embedder"].get("badge"),
        }
    return render(request, "search.html", ctx)
