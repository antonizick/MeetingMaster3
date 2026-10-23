"""The Ask-AI page (``/ask``) and answer views (``/ask/{id}``), Phase 15j, R31.

A question runs as a long task (``static/js/ask.js`` follows it with the shared progress widget)
and, when done, opens its answer. The answer view renders the saved vault note server-side with
the sanitising renderer (S3); its ``[[links]]`` to meetings become links to their review pages,
and links to MeetingMaster3 moments become relative links. A cloud backend needs the consent box
ticked for the question unless the backend's "Always allow Ask-AI" switch is on (S6); the
check is made before the task starts, so a refused question sends nothing.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from meetingmaster3.ask.service import AskService, Choice, base_url
from meetingmaster3.ask.store import AnswerRecord
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.pricing import cost_usd
from meetingmaster3.review.progress import TaskState
from meetingmaster3.search.query import SearchFilters
from meetingmaster3.vault.io import read_text
from meetingmaster3.web.pages import render
from meetingmaster3.web.paging import pager, paginate, parse_page
from meetingmaster3.web.render import render_markdown
from meetingmaster3.web.search_ui import meeting_link
from meetingmaster3.web.views import obsidian_link

log = logging.getLogger(__name__)
router = APIRouter()

HISTORY_PER_PAGE = 10
MAX_QUESTION = 2000
EST_PLAN = (1200, 250)
EST_READ = (3500, 350)
EST_ANSWER = (6000, 900)
"""Rough tokens (in, out) of the plan call, one read call and the answer call, for the cost
estimate (measured on the synthetic corpus and Nick's vault, ``docs/PERFORMANCE.md``)."""
_H1_RE = re.compile(r"^# .*\n", re.M)
"""The note's title line (the question), already the page's heading."""
_CALLOUT_RE = re.compile(r"^> \[!question\] Question\n(?:> .*\n)+", re.M)
"""Obsidian's callout with the full question, also the page's heading."""
_WIKI_RE = re.compile(r"(?<!!)\[\[([^\[\]|#\n]+)(#[^\[\]|\n]*)?(?:\\?\|([^\[\]\n]*))?\]\]")


def service(request: Request) -> AskService:
    ask: AskService | None = getattr(request.app.state, "ask", None)
    if ask is None:
        raise MM3Error(
            "E_ASK_UNAVAILABLE", "The Ask-AI agent is not running.", "Restart the app.", 503
        )
    return ask


def _backends(request: Request, ask: AskService) -> list[dict[str, Any]]:
    registry = request.app.state.llm_registry
    out = []
    for name in registry.names():
        try:
            d = registry.describe(name)
        except MM3Error as exc:
            out.append({"name": name, "badge": "unavailable", "error": exc.message})
            continue
        cfg = registry.config(name)
        model = cfg.default_model or ""
        if name == ask.default_backend() and ask.settings.ask.default_model:
            model = ask.settings.ask.default_model
        out.append(
            {
                "name": name,
                "badge": d["badge"],
                "is_local": d["is_local"],
                "needs_consent": not d["is_local"] and not cfg.ask_consent_remembered,
                "remembered": bool(cfg.ask_consent_remembered),
                "model": model,
            }
        )
    return out


def _history_view(records: list[AnswerRecord]) -> list[dict[str, Any]]:
    return [
        {
            "id": r.id,
            "question": r.question,
            "asked": r.asked_at.strftime("%Y-%m-%d %H:%M"),
            "asked_iso": r.asked_at.isoformat(),
            "model": r.model,
            "backend": r.backend,
            "relevant": r.relevant,
            "seconds": r.duration_s,
        }
        for r in records
    ]


@router.get("/ask", response_class=HTMLResponse)
async def ask_page(
    request: Request,
    history_page: str | None = None,
    again: str | None = None,
    follow: str | None = None,
    deleted: str | None = None,
) -> HTMLResponse:
    ask = service(request)
    settings = ask.settings
    store = ask.store
    total = await asyncio.to_thread(store.count)
    pg = paginate(total, parse_page(history_page), HISTORY_PER_PAGE)
    records = await asyncio.to_thread(store.recent, pg.size, pg.offset)
    backends = _backends(request, ask)
    default = ask.default_backend()
    prefill: dict[str, Any] = {"question": "", "backend": default, "model": None}
    previous = None
    for answer_id, kind in ((again, "again"), (follow, "follow")):
        if not answer_id:
            continue
        record = store.get(answer_id)
        if record is None:
            continue
        if kind == "again":
            prefill = {
                "question": record.question,
                "backend": record.backend,
                "model": record.model,
            }
        else:
            previous = {"id": record.id, "question": record.question}
    chosen = next((b for b in backends if b["name"] == prefill["backend"]), None)
    if chosen is None:
        fallback = backends[0] if backends else {}
        chosen = next((b for b in backends if b["name"] == default), fallback)
    model = prefill["model"] or chosen.get("model", "")
    search = getattr(request.app.state, "search", None)
    index = search.status() if search is not None else None
    running = ask.running()
    ctx = {
        "active": "ask",
        "deleted": bool(deleted),
        "backends": backends,
        "chosen": chosen,
        "model": model,
        "question": prefill["question"],
        "previous": previous,
        "max_meetings": settings.ask.max_meetings,
        "keep_history": settings.ask.keep_history,
        "answers_folder": settings.ask.answers_subfolder,
        "search_enabled": settings.search.enabled,
        "index": index,
        "history": _history_view(records),
        "history_total": total,
        "running": running.snapshot() if running else None,
        "pager": pager(
            pg,
            param="history_page",
            params={},
            href_base="/ask",
            hx_base="/ask/history",
            label="Answers",
        ),
    }
    return render(request, "ask.html", ctx)


@router.get("/ask/history", response_class=HTMLResponse)
async def ask_history(request: Request, history_page: str | None = None) -> HTMLResponse:
    store = service(request).store
    total = await asyncio.to_thread(store.count)
    pg = paginate(total, parse_page(history_page), HISTORY_PER_PAGE)
    records = await asyncio.to_thread(store.recent, pg.size, pg.offset)
    return render(
        request,
        "partials/ask_history.html",
        {
            "history": _history_view(records),
            "pager": pager(
                pg,
                param="history_page",
                params={},
                href_base="/ask",
                hx_base="/ask/history",
                label="Answers",
            ),
        },
    )


def _estimate_text(choice: Choice, models: list[Any], meetings: int) -> str | None:
    info = next((m for m in models if m.id == choice.model), None)
    if info is None:
        return None
    tokens_in = EST_PLAN[0] + meetings * EST_READ[0] + EST_ANSWER[0]
    tokens_out = EST_PLAN[1] + meetings * EST_READ[1] + EST_ANSWER[1]
    cost = cost_usd(info, tokens_in, tokens_out)
    if cost is None:
        return None
    shown = f"{cost:.2f}" if cost >= 0.01 else "0.01"
    prefix = "about" if cost >= 0.01 else "under"
    return f"{prefix} USD {shown} per question if all {meetings} meetings are read"


@router.get("/ask/consent", response_class=HTMLResponse)
async def ask_consent(request: Request, backend: str = "", model: str = "") -> HTMLResponse:
    """What will be sent where, for the chosen backend: nothing for a local one; for a cloud one
    the excerpt limit, the cost estimate where a price is known and the consent box (unless the
    backend's sticky switch is on)."""
    ask = service(request)
    try:
        choice = ask.choose(backend or None, model or None)
    except MM3Error as exc:
        return render(request, "partials/ask_consent.html", {"error": exc.message})
    estimate = None
    if not choice.is_local:
        try:
            models = await asyncio.wait_for(choice.backend.list_models(), 15)
            estimate = _estimate_text(choice, models, ask.settings.ask.max_meetings)
        except (MM3Error, TimeoutError, OSError):
            estimate = None
    return render(
        request,
        "partials/ask_consent.html",
        {
            "choice": choice,
            "provider": choice.config.kind if choice.config else choice.name,
            "max_meetings": ask.settings.ask.max_meetings,
            "estimate": estimate,
        },
    )


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION)
    backend: str | None = Field(default=None, max_length=64)
    model: str | None = Field(default=None, max_length=200)
    cloud_consent: bool = False
    date_from: str | None = None
    date_to: str | None = None
    person: str | None = Field(default=None, max_length=100)
    previous_id: str | None = Field(default=None, max_length=64)


def _date(value: str | None, label: str) -> str | None:
    if not value or not value.strip():
        return None
    try:
        return dt.date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise MM3Error(
            "E_BAD_DATE", f"The {label} date is not a date.", "Use YYYY-MM-DD.", status_code=422
        ) from exc


async def _json_body(request: Request) -> AskBody:
    from meetingmaster3.web.api.templates import _body as parse_body

    return await parse_body(request, AskBody)


@router.post("/ask/start")
async def ask_start(request: Request) -> dict[str, Any]:
    body = await _json_body(request)
    ask = service(request)
    person = (body.person or "").strip()
    filters = SearchFilters(
        date_from=_date(body.date_from, "from"),
        date_to=_date(body.date_to, "to"),
        people=(person,) if person else (),
    )
    if not ask.settings.search.enabled:
        raise MM3Error(
            "E_SEARCH_OFF",
            "Search is switched off, so there is nothing to answer from.",
            "Turn it on in Settings → Search & Ask-AI (Update index).",
            status_code=409,
        )
    task = ask.start(
        body.question,
        backend=body.backend or None,
        model=body.model or None,
        cloud_consent=body.cloud_consent,
        filters=filters,
        previous_id=body.previous_id or None,
    )
    return {"task": task.snapshot()}


@router.get("/ask/task")
async def ask_current(request: Request) -> dict[str, Any]:
    running = service(request).running()
    return {"task": running.snapshot() if running else None}


@router.get("/ask/task/{task_id}")
async def ask_task(request: Request, task_id: str) -> dict[str, Any]:
    return {"task": service(request).task(task_id).snapshot()}


@router.post("/ask/task/{task_id}/cancel")
async def ask_cancel(request: Request, task_id: str) -> dict[str, Any]:
    ask = service(request)
    task = ask.task(task_id)
    await ask.cancel(task)
    return {"task": task.snapshot()}


@router.get("/ask/task/{task_id}/result")
async def ask_result(request: Request, task_id: str) -> dict[str, Any]:
    ask = service(request)
    task = ask.task(task_id)
    if task.state is TaskState.RUNNING:
        raise MM3Error("E_TASK_RUNNING", "The answer is not ready yet.", "", status_code=409)
    if task.state is TaskState.CANCELLED:
        raise MM3Error("E_TASK_CANCELLED", "The question was cancelled.", "", status_code=409)
    if task.error is not None:
        raise task.error
    if isinstance(task.result, AnswerRecord):
        return {"answer_id": task.result.id, "url": f"/ask/{quote(task.result.id, safe='')}"}
    from meetingmaster3.ask.notes import render_answer_note

    text = render_answer_note(task.result, "not-saved", base_url(ask.settings))
    html = render_markdown(_internal_links(text, _links_for(request, ask, None), ask))
    return {"answer_id": None, "html": str(html)}


# -- answer view --------------------------------------------------------------------------


def _links_for(
    request: Request, ask: AskService, record: AnswerRecord | None
) -> dict[str, tuple[str, str | None]]:
    """Note stem (case-folded) → (mm3-id, note path): from the meeting index (current after
    renames), with the answer's own recorded sources as a fallback."""
    links: dict[str, tuple[str, str | None]] = {}
    if record is not None:
        for s in record.sources:
            if s.mm3_id:
                links[s.stem.casefold()] = (s.mm3_id, s.note_path)
    search = getattr(request.app.state, "search", None)
    store = getattr(search, "store", None)
    if store is not None:
        try:
            for doc in store.documents():
                if doc.kind == "note":
                    stem = PurePosixPath(doc.path).name.removesuffix(".md")
                    links[stem.casefold()] = (doc.mm3_id, doc.path)
        except Exception as exc:
            log.info("Meeting links not read from the index: %s", exc)
    return links


def _internal_links(text: str, links: dict[str, tuple[str, str | None]], ask: AskService) -> str:
    """Meeting ``[[links]]`` → review-page links; MeetingMaster3 URLs → relative links."""

    def sub(m: re.Match[str]) -> str:
        target, alias = m.group(1).strip(), (m.group(3) or "").strip()
        label = (alias or target).replace("[", "(").replace("]", ")")
        found = links.get(target.removesuffix(".md").casefold())
        if found is None:
            return label
        url = meeting_link(found[0], found[1]) or f"/meetings/{quote(found[0], safe='')}"
        return f"[{label}](<{url}>)"

    text = _WIKI_RE.sub(sub, text)
    return text.replace(base_url(ask.settings) + "/", "/")


@router.get("/ask/{answer_id}", response_class=HTMLResponse)
async def answer_page(request: Request, answer_id: str) -> HTMLResponse:
    ask = service(request)
    located = await asyncio.to_thread(ask.locate, answer_id)
    record = located.record
    rendered = None
    obsidian = None
    if located.path is not None:
        text = await asyncio.to_thread(read_text, located.path)
        text = _CALLOUT_RE.sub("", _H1_RE.sub("", text, count=1), count=1)
        links = await asyncio.to_thread(_links_for, request, ask, record)
        rendered = render_markdown(_internal_links(text, links, ask))
        obsidian = obsidian_link(str(located.path))
    return render(
        request,
        "ask_answer.html",
        {
            "active": "ask",
            "record": record,
            "asked": record.asked_at.strftime("%Y-%m-%d %H:%M"),
            "rendered": rendered,
            "missing": located.path is None,
            "moved": located.moved,
            "vault_path": record.vault_path,
            "obsidian_link": obsidian,
            "sources": [
                {"title": s.title, "date": s.date, "link": meeting_link(s.mm3_id, s.note_path)}
                for s in record.sources
            ],
        },
    )


def _hx_redirect(url: str) -> Response:
    return Response(status_code=204, headers={"HX-Redirect": url})


@router.post("/ask/{answer_id}/delete")
async def answer_delete(request: Request, answer_id: str) -> Response:
    await asyncio.to_thread(service(request).delete, answer_id)
    return _hx_redirect("/ask?deleted=1")


@router.post("/ask/{answer_id}/forget")
async def answer_forget(request: Request, answer_id: str) -> Response:
    await asyncio.to_thread(service(request).forget, answer_id)
    return _hx_redirect("/ask")


def answers_for_meeting(request: Request, mm3_id: str) -> list[dict[str, Any]]:
    """For the review page: answers that cite the meeting, newest first."""
    ask: AskService | None = getattr(request.app.state, "ask", None)
    if ask is None:
        return []
    return [
        {
            "id": r.id,
            "question": r.question,
            "asked": r.asked_at.strftime("%Y-%m-%d %H:%M"),
            "url": f"/ask/{quote(r.id, safe='')}",
        }
        for r in ask.citing(mm3_id)
    ]
