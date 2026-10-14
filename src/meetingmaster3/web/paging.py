"""Server-side paging for the Meetings page (Phase 15c, R27).

Each section (Jobs, Notes in your vault, Browse the vault) pages on its own through a query
parameter, so a page is a bookmarkable URL that works without JavaScript; HTMX swaps just the
section. :func:`paginate` clamps the requested page so a page that emptied (its last row was
removed or deleted) shows the previous one, never nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

JOBS_PER_PAGE = 10
NOTES_PER_PAGE = 10
BROWSE_PER_PAGE = 25
MAX_PAGE = 100_000  # a guard against absurd ``?page=`` values, not a real limit


@dataclass(frozen=True)
class Page:
    number: int  # 1-based, already clamped to 1..pages
    pages: int  # at least 1, even for an empty list
    total: int
    size: int

    @property
    def offset(self) -> int:
        return (self.number - 1) * self.size

    @property
    def has_prev(self) -> bool:
        return self.number > 1

    @property
    def has_next(self) -> bool:
        return self.number < self.pages

    @property
    def first(self) -> int:
        """1-based index of the first row shown (0 for an empty list)."""
        return self.offset + 1 if self.total else 0

    @property
    def last(self) -> int:
        return min(self.offset + self.size, self.total)


def parse_page(raw: str | None) -> int:
    """A ``?x_page=`` value as an int >= 1; junk and out-of-range values mean the first page."""
    try:
        value = int(raw) if raw is not None else 1
    except ValueError:
        return 1
    return min(max(value, 1), MAX_PAGE)


def paginate(total: int, requested: int, size: int) -> Page:
    pages = max(1, -(-total // size))
    return Page(number=min(max(requested, 1), pages), pages=pages, total=total, size=size)


def page_window(page: Page, span: int = 2) -> list[int | None]:
    """Numbers to show as links: first, last and ``span`` either side of the current page
    (``None`` marks a gap, drawn as an ellipsis)."""
    wanted = {1, page.pages, *range(page.number - span, page.number + span + 1)}
    shown = sorted(n for n in wanted if 1 <= n <= page.pages)
    out: list[int | None] = []
    for n in shown:
        if out and isinstance(out[-1], int) and n - out[-1] > 1:
            out.append(None)
        out.append(n)
    return out


def with_params(base: str, params: dict[str, str], **changes: Any) -> str:
    """``base?…`` from ``params`` with ``changes`` applied; a value of ``None`` or ``1`` for a
    ``*_page`` key, or an empty string, drops the key so the first page has the clean URL."""
    merged = {**params, **{k: str(v) for k, v in changes.items() if v is not None}}
    for key, value in changes.items():
        if value is None:
            merged.pop(key, None)
    merged = {
        k: v for k, v in merged.items() if v not in ("", "1" if k.endswith("_page") else None)
    }
    return f"{base}?{urlencode(merged)}" if merged else base


def pager(
    page: Page,
    *,
    param: str,
    params: dict[str, str],
    href_base: str,
    hx_base: str,
    label: str,
) -> dict[str, Any]:
    """Everything ``partials/pager.html`` needs: plain ``href`` links (no-JS fallback) and the
    HTMX partial URL for each target page."""

    def link(n: int) -> dict[str, Any]:
        return {
            "n": n,
            "href": with_params(href_base, params, **{param: n}),
            "hx": with_params(hx_base, params, **{param: n}),
        }

    return {
        "label": label,
        "page": page,
        "prev": link(page.number - 1) if page.has_prev else None,
        "next": link(page.number + 1) if page.has_next else None,
        "numbers": [link(n) if n is not None else None for n in page_window(page)],
    }


PAGE_PARAMS = ("jobs_page", "notes_page", "browse_page", "dir")


def page_params(query: Any) -> dict[str, str]:
    """The Meetings-page query parameters present on a request (anything else is ignored)."""
    return {k: query[k] for k in PAGE_PARAMS if k in query and query[k] != ""}


def picker_context(listing: Any, params: dict[str, str]) -> dict[str, Any]:
    """Template context for ``partials/picker.html``: one page of the folder listing."""
    page = paginate(len(listing.entries), parse_page(params.get("browse_page")), BROWSE_PER_PAGE)
    own = {k: v for k, v in params.items() if k != "browse_page"}
    own["dir"] = listing.folder
    return {
        "listing": listing,
        "entries": listing.entries[page.offset : page.offset + page.size],
        "browse_pager": pager(
            page,
            param="browse_page",
            params=own,
            href_base="/meetings",
            hx_base="/ui/open/browse",
            label="Folder",
        ),
    }
