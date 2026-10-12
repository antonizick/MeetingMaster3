"""The ``fb`` variable for ``web/templates/partials/feedback.html`` (the rating widget).

Pages that show a note or a section (the completion page, the review workspace) call
:func:`feedback_context` and ``{% include "partials/feedback.html" %}``.
"""

from __future__ import annotations

from typing import Any

from meetingmaster3.feedback.store import FeedbackStore


def feedback_context(
    store: FeedbackStore | None,
    mm3_id: str,
    *,
    template_id: str | None,
    backend: str | None,
    model: str | None,
    section_id: str | None = None,
    saved: bool = False,
) -> dict[str, Any]:
    """The ``fb`` variable for ``partials/feedback.html``. A note gets stars, a section thumbs."""
    current = store.latest(mm3_id, section_id) if store else None
    return {
        "mm3_id": mm3_id,
        "kind": "thumbs" if section_id else "stars",
        "template_id": template_id,
        "backend": backend,
        "model": model,
        "section_id": section_id or "",
        "current": current.to_dict() if current else None,
        "saved": saved,
    }
