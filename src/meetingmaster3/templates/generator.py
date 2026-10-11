"""Note generation: transcript + template → sections, directly or through map-reduce (R6).

:class:`NoteGenerator` is async (the LLM backends are) and has no job or vault knowledge; the
job stage (:mod:`meetingmaster3.templates.stages`) and the API wrap it. Consent (S6) is enforced
here, before the first call, so no caller can forget it.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.note import Note, Section
from meetingmaster3.domain.transcript import Transcript
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.base import GenerateRequest, LLMBackend, Message
from meetingmaster3.llm.budget import (
    Chunk,
    chunk_transcript,
    estimate_tokens,
    fits_window,
    usable_tokens,
    window_for,
)
from meetingmaster3.llm.consent import enforce_consent
from meetingmaster3.templates import assembler
from meetingmaster3.templates.cues import Cue, guard_owners
from meetingmaster3.templates.mapreduce import (
    EXTRACTION_SYSTEM,
    ChunkExtraction,
    ExtractionError,
    extraction_prompt,
    merge,
    parse_extraction,
    render_notes,
    repair_prompt,
)
from meetingmaster3.templates.postprocess import EMPTY_BODY, clean_section
from meetingmaster3.templates.schema import Template, TemplateSection

log = logging.getLogger(__name__)

EXTRACTION_MAX_TOKENS = 1500
EXTRACTION_TEMPERATURE = 0.1
MIN_CHUNK_TOKENS = 512
MIN_NUM_CTX = 4096
REQUEST_TIMEOUT_S = 900.0
MAP_SHARE = 0.6
"""Share of the progress bar given to the map step in map-reduce mode."""

ProgressFn = Callable[[float, str], None]
CancelFn = Callable[[], None]
WarnFn = Callable[[str], None]
SectionFn = Callable[[Section], None]


def _noop_progress(fraction: float, message: str) -> None:
    pass


def _noop() -> None:
    pass


def _noop_warn(message: str) -> None:
    log.warning("%s", message)


@dataclass(frozen=True)
class PreparedContext:
    system: str
    context: str
    mode: Literal["full", "map-reduce"]
    window: int
    num_ctx: int
    chunks: int = 0
    meeting_day: dt.date | None = None
    cues: tuple[Cue, ...] = ()


@dataclass
class GenerationResult:
    sections: list[Section]
    mode: Literal["full", "map-reduce"]
    chunks: int = 0
    calls: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class NoteGenerator:
    backend: LLMBackend
    model: str
    template: Template
    cloud_consent: bool = False
    consent_remembered: bool = False
    max_context: int | None = None
    """Cap on the context window to plan for (local GPUs cannot hold a model's full window)."""
    instructions: str | None = None
    think: bool = False
    """Reasoning mode for models that support it (see ``generation.think``)."""
    today: dt.date | None = None
    progress: ProgressFn = _noop_progress
    check_cancelled: CancelFn = _noop
    warn: WarnFn = _noop_warn
    calls: int = 0
    warnings: list[str] = field(default_factory=list)

    # -- helpers -----------------------------------------------------------------------

    def _warn(self, message: str) -> None:
        self.warnings.append(message)
        self.warn(message)

    async def _window(self) -> int:
        window = await window_for(self.backend, self.model)
        if self.max_context and self.backend.is_local:
            window = min(window, self.max_context)
        return window

    async def _call(
        self,
        system: str,
        messages: list[Message],
        *,
        temperature: float,
        max_tokens: int,
        num_ctx: int,
        json_mode: bool = False,
    ) -> tuple[str, str | None]:
        self.check_cancelled()
        self.calls += 1
        result = await self.backend.generate(
            GenerateRequest(
                model=self.model,
                system=system,
                messages=tuple(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
                num_ctx=num_ctx,
                timeout=REQUEST_TIMEOUT_S,
                think=self.think,
            )
        )
        return result.text, result.finish_reason

    def _sections_overhead(
        self, sections: list[TemplateSection], cues: tuple[Cue, ...] = ()
    ) -> tuple[int, int]:
        """(tokens of the longest section tail, largest output reserve)."""
        tail = max(
            estimate_tokens(
                assembler.section_prompt(
                    self.template, s, "", instructions=self.instructions, cues=cues
                )
            )
            for s in sections
        )
        reserve = max(self.template.max_tokens(s) for s in sections)
        return tail, reserve

    @staticmethod
    def _num_ctx(window: int, need: int) -> int:
        """One context size for every call of a note, so a local Ollama never reloads the model
        between sections."""
        return min(window, max(MIN_NUM_CTX, math.ceil(need / 1024) * 1024))

    # -- context -----------------------------------------------------------------------

    async def prepare(
        self,
        meta: MeetingMeta,
        transcript: Transcript,
        sections: list[TemplateSection],
        *,
        map_progress: tuple[float, float] = (0.0, MAP_SHARE),
    ) -> PreparedContext:
        """Decide full vs map-reduce and build the shared system message and context."""
        enforce_consent(
            self.backend, cloud_consent=self.cloud_consent, remembered=self.consent_remembered
        )
        today = self.today or dt.date.today()
        day = meta.date.date() if meta.date else None
        facts = assembler.MeetingFacts.from_meta(meta, transcript)
        system = assembler.system_prompt(self.template, facts, today)
        turns = assembler.transcript_turns(transcript)
        hours = any((t.start or 0.0) >= 3600 for t in turns)
        cues = tuple(assembler.task_cues(turns, hours=hours))
        context = assembler.context_block(assembler.format_turns(turns, hours=hours))
        window = await self._window()
        tail, reserve = self._sections_overhead(sections, cues)
        prompt_tokens = estimate_tokens(system + "\n" + context) + tail
        if fits_window(window, system + "\n" + context, reserve + tail):
            return PreparedContext(
                system,
                context,
                "full",
                window,
                self._num_ctx(window, prompt_tokens + reserve),
                meeting_day=day,
                cues=cues,
            )

        # Map: chunk on speaker turns so each extraction call fits the budget.
        overhead = estimate_tokens(EXTRACTION_SYSTEM + extraction_prompt(99, 99, ""))
        budget = usable_tokens(window) - overhead - EXTRACTION_MAX_TOKENS
        if budget < MIN_CHUNK_TOKENS:
            raise MM3Error(
                "E_LLM_CONTEXT",
                f"The model's context window ({window} tokens) is too small to summarise this "
                "meeting.",
                "Choose a model with a larger context window, or raise generation.max_context.",
                status_code=422,
            )
        chunks = chunk_transcript(turns, budget)
        num_ctx = self._num_ctx(window, usable_tokens(window) + reserve)
        start, end = map_progress
        extractions: list[ChunkExtraction | None] = []
        ranges: list[str] = []
        for chunk in chunks:
            self.progress(
                start + (end - start) * chunk.index / len(chunks),
                f"Reading part {chunk.index + 1} of {len(chunks)}",
            )
            extractions.append(await self._extract(chunk, len(chunks), hours, num_ctx))
            ranges.append(_range(chunk, hours))
        merged = merge(extractions, ranges)
        for i in merged.skipped_chunks:
            self._warn(
                f"Part {i + 1} of {len(chunks)} ({ranges[i]}) could not be summarised and is "
                "missing from the notes."
            )
        if len(merged.skipped_chunks) == len(chunks):
            raise MM3Error(
                "E_LLM_BAD_RESPONSE",
                "The model did not return usable notes for any part of the meeting.",
                "Try a larger or more capable model.",
                status_code=502,
            )
        room = usable_tokens(window) - estimate_tokens(system) - tail - reserve
        notes_text, truncated = render_notes(merged, max(room, MIN_CHUNK_TOKENS))
        if truncated:
            self._warn(
                "The meeting is very long: some minor points were left out so the notes fit the "
                "model's context window."
            )
        self.progress(end, "Writing sections")
        return PreparedContext(
            system,
            assembler.context_block(notes_text=notes_text),
            "map-reduce",
            window,
            num_ctx,
            len(chunks),
            meeting_day=day,
            cues=cues,
        )

    async def _extract(
        self, chunk: Chunk, parts: int, hours: bool, num_ctx: int
    ) -> ChunkExtraction | None:
        prompt = extraction_prompt(
            chunk.index + 1, parts, assembler.format_turns(chunk.turns, hours=hours)
        )
        messages = [Message("user", prompt)]
        text, _ = await self._call(
            EXTRACTION_SYSTEM,
            messages,
            temperature=EXTRACTION_TEMPERATURE,
            max_tokens=EXTRACTION_MAX_TOKENS,
            num_ctx=num_ctx,
            json_mode=True,
        )
        try:
            return parse_extraction(text)
        except ExtractionError as exc:
            log.info("Chunk %d: unusable extraction (%s); asking again", chunk.index, exc)
            messages += [
                Message("assistant", text[:4000]),
                Message("user", repair_prompt(str(exc))),
            ]
        text, _ = await self._call(
            EXTRACTION_SYSTEM,
            messages,
            temperature=EXTRACTION_TEMPERATURE,
            max_tokens=EXTRACTION_MAX_TOKENS,
            num_ctx=num_ctx,
            json_mode=True,
        )
        try:
            return parse_extraction(text)
        except ExtractionError as exc:
            log.warning("Chunk %d: extraction failed twice (%s)", chunk.index, exc)
            return None

    # -- sections ----------------------------------------------------------------------

    async def _section(
        self,
        prepared: PreparedContext,
        section: TemplateSection,
        *,
        previous: str | None = None,
        feedback: str | None = None,
    ) -> str:
        prompt = assembler.section_prompt(
            self.template,
            section,
            prepared.context,
            instructions=self.instructions,
            previous=previous,
            feedback=feedback,
            cues=prepared.cues,
        )
        temperature = self.template.temperature(section)
        max_tokens = self.template.max_tokens(section)
        body = EMPTY_BODY
        for attempt in range(2):
            text, finish = await self._call(
                prepared.system,
                [Message("user", prompt)],
                temperature=min(2.0, temperature + 0.1 * attempt),
                max_tokens=max_tokens,
                num_ctx=prepared.num_ctx,
            )
            body = clean_section(
                text, title=section.title, fmt=section.format, meeting_day=prepared.meeting_day
            )
            if section.format == "tasks" and prepared.cues:
                body, unassigned = guard_owners(body, prepared.cues)
                for line in unassigned:
                    log.info("Owner guard: unassigned a task its owner only suggested: %s", line)
            if body != EMPTY_BODY:
                if finish == "length":
                    self._warn(
                        f'The "{section.title}" section reached its length limit and may be '
                        "cut off."
                    )
                return body
        self._warn(f'The model returned nothing for the "{section.title}" section.')
        return body

    async def generate(
        self,
        meta: MeetingMeta,
        transcript: Transcript,
        *,
        done: Mapping[str, str] | None = None,
        on_section: SectionFn | None = None,
    ) -> GenerationResult:
        """Generate every template section, in order. ``transcript`` must be named
        (``speaker_name`` set). ``done`` holds bodies from an interrupted earlier run, which are
        reused; ``on_section`` is called after each new section (for checkpointing)."""
        sections = list(self.template.sections)
        done = dict(done or {})
        todo = [s for s in sections if s.id not in done]
        prepared: PreparedContext | None = None
        if todo:
            prepared = await self.prepare(meta, transcript, todo)
        else:
            enforce_consent(
                self.backend, cloud_consent=self.cloud_consent, remembered=self.consent_remembered
            )
        base = MAP_SHARE if prepared and prepared.mode == "map-reduce" else 0.0
        out: list[Section] = []
        for i, s in enumerate(sections):
            if s.id in done:
                out.append(Section(id=s.id, title=s.title, body_markdown=done[s.id]))
                continue
            if prepared is None:  # pragma: no cover - todo is non-empty here
                raise RuntimeError("context was not prepared")
            self.progress(base + (1 - base) * i / len(sections), f"Writing {s.title}")
            body = await self._section(prepared, s)
            section = Section(id=s.id, title=s.title, body_markdown=body)
            out.append(section)
            if on_section is not None:
                on_section(section)
        self.progress(1.0, "Notes written")
        return GenerationResult(
            sections=out,
            mode=prepared.mode if prepared else "full",
            chunks=prepared.chunks if prepared else 0,
            calls=self.calls,
            warnings=list(self.warnings),
        )

    async def regenerate_section(
        self,
        meta: MeetingMeta,
        transcript: Transcript,
        section_id: str,
        *,
        title: str | None = None,
        previous: str | None = None,
        feedback: str | None = None,
    ) -> str:
        """A new body for one section (the caller diffs, applies and archives)."""
        section = self.template.section(section_id) or assembler.adhoc_section(
            section_id, title or section_id
        )
        if title and title != section.title:
            section = section.model_copy(update={"title": title})
        prepared = await self.prepare(meta, transcript, [section], map_progress=(0.0, 0.8))
        return await self._section(prepared, section, previous=previous, feedback=feedback)


def _range(chunk: Chunk, hours: bool) -> str:
    starts = [t.start for t in chunk.new_turns if t.start is not None]
    if not starts:
        return f"part {chunk.index + 1}"
    return f"{assembler.clock(starts[0], hours=hours)}-{assembler.clock(starts[-1], hours=hours)}"


async def regenerate_section(
    note: Note,
    section_id: str,
    instructions: str | None = None,
    *,
    transcript: Transcript,
    template: Template,
    backend: LLMBackend,
    model: str,
    cloud_consent: bool = False,
    consent_remembered: bool = False,
    max_context: int | None = None,
    think: bool = False,
) -> str:
    """Regenerate ``section_id`` of ``note`` and return the new body only. ``transcript`` is
    the named transcript (from the companion file). Compare old and new bodies with
    :func:`meetingmaster3.markdown.diff.unified_diff`."""
    current = note.section(section_id)
    generator = NoteGenerator(
        backend,
        model,
        template,
        cloud_consent=cloud_consent,
        consent_remembered=consent_remembered,
        max_context=max_context,
        think=think,
    )
    return await generator.regenerate_section(
        note.meta,
        transcript,
        section_id,
        title=current.title if current else None,
        previous=current.body_markdown if current else None,
        feedback=instructions,
    )
