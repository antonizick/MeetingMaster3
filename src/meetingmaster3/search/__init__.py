"""Meeting index and hybrid search (Phase 15i, R30, ADR-0049, ADR-0050).

The API Phase 15j (Ask) builds on::

    service: SearchService = app.state.search          # or SearchService(...) in the CLI
    result = await service.query("costs over budget", limit=40,
                                 filters=SearchFilters(date_from="2026-01-01"))
    result.mode                                        # "hybrid", "words", "meaning" or "none"
    meetings = result.group_by_meeting()               # ranked MeetingHits, each with its hits
    facts = await service.meeting_facts([m.mm3_id for m in meetings], result.hits)

Modules: ``store`` (``search.db``), ``chunking`` (passages), ``embedder`` (which backend embeds,
consent, model prefixes), ``index`` (incremental updates, GPU gate), ``query`` (FTS5 + vectors +
fusion), ``service`` (the app-wide service).
"""

from meetingmaster3.search.query import (
    Hit,
    MeetingFacts,
    MeetingHits,
    SearchFilters,
    SearchResult,
    group_by_meeting,
)
from meetingmaster3.search.service import SearchService

__all__ = [
    "Hit",
    "MeetingFacts",
    "MeetingHits",
    "SearchFilters",
    "SearchResult",
    "SearchService",
    "group_by_meeting",
]
