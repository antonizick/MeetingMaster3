"""The template library screen (``/templates``): browse, favourite, preview, edit, duplicate,
create, delete and reset the templates in the vault.

Templates are plain files the user may also edit in Obsidian; the screen reads the vault on
every request, so changes made either way show up on the next refresh.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from meetingmaster3.errors import MM3Error
from meetingmaster3.templates.assembler import section_instructions
from meetingmaster3.templates.loader import MANIFEST_NAME, TemplateEntry
from meetingmaster3.templates.manage import TemplateManager
from meetingmaster3.templates.schema import parse_template
from meetingmaster3.vault.paths import resolve_vault_root
from meetingmaster3.web import views
from meetingmaster3.web.pages import render

router = APIRouter()


def manager_for(request: Request) -> TemplateManager:
    settings = request.app.state.settings
    if settings.vault.path is None:
        raise MM3Error(
            "E_VAULT_NOT_SET",
            "No vault is set.",
            "Choose your vault in Settings first.",
            status_code=409,
        )
    return TemplateManager(
        resolve_vault_root(settings.vault.path),
        settings.vault.templates_subfolder,
        request.app.state.paths.data_dir / MANIFEST_NAME,
    )


async def _form(request: Request) -> dict[str, str]:
    data = await request.form()
    return {k: v for k, v in data.items() if isinstance(v, str)}


def _card(entry: TemplateEntry, builtin_files: set[str], default_id: str) -> dict[str, Any]:
    info = entry.to_dict()
    info["is_builtin_file"] = entry.path.name in builtin_files
    info["is_default"] = entry.id == default_id
    info["obsidian_link"] = (
        views.obsidian_link(str(entry.path)) if entry.source == "vault" else None
    )
    return info


def _library_context(
    request: Request, manager: TemplateManager, tag: str = "", q: str = ""
) -> dict[str, Any]:
    settings = request.app.state.settings
    library = manager.library()
    builtin_files = manager.builtin_names()
    cards = [
        _card(e, builtin_files, settings.generation.default_template) for e in library.listing()
    ]
    tags = sorted({t for c in cards for t in c["tags"]})
    needle = q.strip().lower()
    if tag:
        cards = [c for c in cards if tag in c["tags"]]
    if needle:
        cards = [
            c
            for c in cards
            if needle in f"{c['name']} {c['description']} {' '.join(c['tags'])}".lower()
        ]
    return {"cards": cards, "tags": tags, "tag": tag, "q": q, "folder": manager.subfolder}


def _list_response(request: Request, manager: TemplateManager, **kw: str) -> HTMLResponse:
    ctx = _library_context(request, manager, **kw)
    return render(request, "templates/_library.html", ctx)


@router.get("/templates", response_class=HTMLResponse)
async def templates_page(request: Request, tag: str = "", q: str = "") -> HTMLResponse:
    manager = manager_for(request)
    ctx = await asyncio.to_thread(_library_context, request, manager, tag, q)
    return render(request, "templates/page.html", {"active": "templates", **ctx})


@router.get("/templates/list", response_class=HTMLResponse)
async def templates_list(request: Request, tag: str = "", q: str = "") -> HTMLResponse:
    manager = manager_for(request)
    return await asyncio.to_thread(_list_response, request, manager, tag=tag, q=q)


@router.post("/templates/new")
async def template_new(request: Request) -> Response:
    form = await _form(request)
    file = manager_for(request).create(form.get("name", ""))
    return Response(headers={"HX-Redirect": f"/templates/{file}/edit"})


@router.post("/templates/{file}/favorite", response_class=HTMLResponse)
async def template_favorite(request: Request, file: str) -> HTMLResponse:
    form = await _form(request)
    manager = manager_for(request)
    manager.set_favorite(file, form.get("favorite") == "1")
    return _list_response(request, manager, tag=form.get("tag", ""), q=form.get("q", ""))


@router.post("/templates/{file}/duplicate", response_class=HTMLResponse)
async def template_duplicate(request: Request, file: str) -> HTMLResponse:
    manager = manager_for(request)
    manager.duplicate(file)
    return _list_response(request, manager)  # the copy shows up in the list


@router.post("/templates/{file}/delete", response_class=HTMLResponse)
async def template_delete(request: Request, file: str) -> HTMLResponse:
    manager = manager_for(request)
    manager.delete(file)
    return _list_response(request, manager)


@router.post("/templates/{file}/reset", response_class=HTMLResponse)
async def template_reset(request: Request, file: str) -> HTMLResponse:
    manager = manager_for(request)
    manager.reset_builtin(file)
    return _list_response(request, manager)


@router.get("/templates/{file}/preview", response_class=HTMLResponse)
async def template_preview(request: Request, file: str) -> HTMLResponse:
    manager = manager_for(request)
    text = manager.read(file)
    report = parse_template(text, source=file)
    template = report.template
    sections: list[dict[str, Any]] = []
    if template is not None:
        for s in template.sections:
            sections.append(
                {
                    "id": s.id,
                    "title": s.title,
                    "kind": s.kind,
                    "format": s.format,
                    "temperature": template.temperature(s),
                    "max_tokens": template.max_tokens(s),
                    "prompt": section_instructions(template, s),
                }
            )
    return render(
        request,
        "templates/preview.html",
        {
            "active": "templates",
            "file": file,
            "template": template,
            "issues": report.issues,
            "sections": sections,
        },
    )


def _editor_ctx(
    manager: TemplateManager, file: str, text: str, issues: list[Any], saved: bool
) -> dict[str, Any]:
    entry = manager.entry(file)
    return {
        "active": "templates",
        "file": file,
        "text": text,
        "issues": issues,
        "saved": saved,
        "source": entry.source,
        "is_builtin_file": file in manager.builtin_names(),
        "obsidian_link": views.obsidian_link(str(entry.path)) if entry.source == "vault" else None,
    }


@router.get("/templates/{file}/edit", response_class=HTMLResponse)
async def template_edit(request: Request, file: str) -> HTMLResponse:
    manager = manager_for(request)
    text = manager.read(file)
    return render(request, "templates/edit.html", _editor_ctx(manager, file, text, [], False))


@router.post("/templates/{file}/edit", response_class=HTMLResponse)
async def template_save(request: Request, file: str) -> HTMLResponse:
    manager = manager_for(request)
    form = await _form(request)
    text = form.get("text", "").replace("\r\n", "\n")
    result = manager.save(file, text)
    ctx = _editor_ctx(manager, file, text, list(result.issues), result.ok)
    return render(request, "templates/_editor.html", ctx)
