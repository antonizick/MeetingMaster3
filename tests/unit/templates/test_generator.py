"""Generation with the deterministic FakeLLMBackend: full mode, map-reduce (with JSON repair),
consent, checkpoints and regeneration."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import replace
from typing import Any

import pytest

from meetingmaster3.domain.meeting import MeetingMeta
from meetingmaster3.domain.transcript import Segment, SpeakerMap, Transcript
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.base import E_CONSENT_REQUIRED, GenerateRequest
from meetingmaster3.llm.budget import estimate_tokens, usable_tokens
from meetingmaster3.llm.fake import FakeLLMBackend
from meetingmaster3.markdown.note_parser import parse_note
from meetingmaster3.markdown.note_writer import build_note, render_note
from meetingmaster3.templates.generator import (
    CONTEXT_MARGIN,
    NoteGenerator,
    regenerate_section,
)
from meetingmaster3.templates.loader import load_library
from meetingmaster3.templates.mapreduce import (
    ChunkExtraction,
    ExtractionError,
    close_truncated,
    merge,
    parse_extraction,
    render_notes,
)
from tests.unit.templates.builtin_ids import BUILTIN_IDS

LINES = [
    ("SPEAKER_00", "Let's decide the launch date today."),
    ("SPEAKER_01", "I'll finish the billing migration by Friday."),
    ("SPEAKER_00", "Agreed, we launch on the twenty-first."),
    ("SPEAKER_01", "Do we have support staffing for launch week?"),
    ("SPEAKER_00", "We should update the status page template."),
]
NAMES = SpeakerMap(names={"SPEAKER_00": "Priya", "SPEAKER_01": "Marcus"})
TODAY = dt.date(2026, 10, 11)


def transcript(repeat: int = 1) -> Transcript:
    segs = []
    for r in range(repeat):
        for i, (label, text) in enumerate(LINES):
            n = r * len(LINES) + i
            segs.append(Segment(id=n, start=n * 10.0, end=n * 10.0 + 9, speaker_label=label,
                                text=f"{text} (round {r})" if repeat > 1 else text))  # fmt: skip
    return NAMES.apply(Transcript(segments=segs, language="en", diarized=True))


def meta() -> MeetingMeta:
    return MeetingMeta(
        title="Launch", date=dt.datetime(2026, 10, 6, 10), participants=["Priya", "Marcus"]
    )


def generator(backend: FakeLLMBackend, template: str = "executive-summary", **kw) -> NoteGenerator:  # type: ignore[no-untyped-def]
    return NoteGenerator(backend, "fake-model", load_library().get(template), today=TODAY, **kw)


async def test_full_mode_generates_every_section_in_order() -> None:
    backend = FakeLLMBackend()
    progress: list[tuple[float, str]] = []
    gen = generator(backend, progress=lambda f, m: progress.append((f, m)))
    result = await gen.generate(meta(), transcript())
    template = load_library().get("executive-summary")
    assert [s.id for s in result.sections] == [s.id for s in template.sections]
    assert result.mode == "full" and result.chunks == 0
    assert result.calls == len(template.sections) == len(backend.calls)
    actions = next(s for s in result.sections if s.id == "action-items").body_markdown
    assert "- [ ] **Marcus:** I'll finish the billing migration by Friday." in actions
    assert progress[-1] == (1.0, "Notes written")
    # Every call shares one system prompt and context size (prompt cache, no model reloads).
    assert len({c.system for c in backend.calls}) == 1
    assert len({c.num_ctx for c in backend.calls}) == 1
    assert all(c.think is False for c in backend.calls)
    # Temperatures follow R6: extraction 0.2, narrative 0.4.
    temps = {c.messages[-1].content.split('"')[1]: c.temperature for c in backend.calls}
    assert temps["Summary Succinct"] == 0.4 and temps["Summary Detailed"] == 0.4
    assert temps["Action Items"] == 0.2
    # The rendered note parses back with valid markers, AI Recommendations last.
    note = build_note(meta(), result.sections)
    parsed = parse_note(render_note(note))
    assert parsed.ok and parsed.note.sections[-1].id == "ai-recommendations"


async def test_prompt_contents() -> None:
    backend = FakeLLMBackend()
    await generator(backend, instructions="Focus on the launch.").generate(meta(), transcript())
    first = backend.calls[0]
    system = first.system or ""
    assert "never guess a real name" in system and 'Template "Executive Summary"' in system
    assert "- Speakers in the transcript: Priya, Marcus" in system
    assert "Today's date: Sunday 2026-10-11" in system
    user = first.messages[0].content
    assert user.startswith("Transcript:\n<transcript>\n[00:00] Priya: Let's decide")
    assert "Additional instructions from the user:\nFocus on the launch." in user
    assert user.rstrip().endswith("introduction or closing remark.")
    tasks = next(c for c in backend.calls if '"Action Items"' in c.messages[0].content)
    assert "<candidates>" in tasks.messages[0].content
    assert "Marcus (commits to it): I'll finish the billing migration" in tasks.messages[0].content
    assert "<candidates>" not in first.messages[0].content  # only task sections get cues


async def test_owner_guard_applies_to_model_output() -> None:
    def respond(req: GenerateRequest) -> str:
        if '"Action Items"' in req.messages[0].content:
            return "- [ ] **Priya:** Update the status page template (due: not stated)"
        return "Fine."

    result = await generator(FakeLLMBackend(responder=respond)).generate(meta(), transcript())
    actions = next(s for s in result.sections if s.id == "action-items").body_markdown
    assert actions == "- [ ] **Unassigned:** Update the status page template (due: not stated)"


async def test_empty_answer_is_retried_then_warned() -> None:
    answers = iter(["", "<think>only thinking</think>"] + ["ok"] * 20)
    warnings: list[str] = []
    gen = generator(FakeLLMBackend(responder=lambda r: next(answers)), warn=warnings.append)
    result = await gen.generate(meta(), transcript())
    assert result.sections[0].body_markdown == "_Nothing to report._"
    # one retry for the empty Summary Succinct, one for the one-paragraph Summary Detailed
    assert result.calls == len(result.sections) + 2
    assert warnings[0] == 'The model returned nothing for the "Summary Succinct" section.'
    assert "fewer than 2 paragraphs" in warnings[1] and len(warnings) == 2


async def test_consent_is_enforced_before_any_call() -> None:
    cloud = FakeLLMBackend(id="openrouter", is_local=False)
    with pytest.raises(MM3Error) as err:
        await generator(cloud).generate(meta(), transcript())
    assert err.value.code == E_CONSENT_REQUIRED and cloud.calls == []
    result = await generator(cloud, cloud_consent=True).generate(meta(), transcript())
    assert result.sections
    remembered = FakeLLMBackend(id="openrouter", is_local=False)
    await generator(remembered, consent_remembered=True).generate(meta(), transcript())
    assert remembered.calls


async def test_done_sections_are_reused_and_checkpointed() -> None:
    backend = FakeLLMBackend()
    seen: list[str] = []
    result = await generator(backend).generate(
        meta(),
        transcript(),
        done={"summary": "Kept from the first run."},
        on_section=lambda s: seen.append(s.id),
    )
    assert result.sections[0].body_markdown == "Kept from the first run."
    assert "summary" not in seen and len(seen) == len(result.sections) - 1
    assert not any('"Summary"' in c.messages[0].content for c in backend.calls)


async def test_cancellation_stops_between_calls() -> None:
    class Stop(Exception):
        pass

    backend = FakeLLMBackend()

    def check() -> None:
        if len(backend.calls) >= 2:
            raise Stop

    with pytest.raises(Stop):
        await generator(backend, check_cancelled=check).generate(meta(), transcript())
    assert len(backend.calls) == 2


async def test_map_reduce_for_long_transcripts() -> None:
    backend = FakeLLMBackend(window=4096)
    long = transcript(repeat=60)  # far beyond 70% of a 4k window
    progress: list[str] = []
    gen = generator(backend, progress=lambda f, m: progress.append(m))
    result = await gen.generate(meta(), long)
    assert result.mode == "map-reduce" and result.chunks >= 3
    json_calls = [c for c in backend.calls if c.json_mode]
    assert len(json_calls) == result.chunks
    assert all(c.temperature == 0.1 for c in json_calls)
    assert any(m.startswith("Reading part 1 of") for m in progress)
    section_calls = [c for c in backend.calls if not c.json_mode]
    assert all("<meeting_notes>" in c.messages[0].content for c in section_calls)
    assert all("<transcript>" not in c.messages[0].content for c in section_calls)
    # Deduplicated: the same commitment from 60 rounds appears once per distinct wording.
    notes = section_calls[0].messages[0].content
    tasks = [ln for ln in notes.split("\n") if "billing migration" in ln and "(due:" in ln]
    assert tasks == ["- [00:10] Marcus: I'll finish the billing migration by Friday. (round 0) "
                     "(due: not stated)"]  # fmt: skip


async def test_map_reduce_repairs_bad_json_and_skips_hopeless_chunks() -> None:
    attempts: dict[str, int] = {}
    warnings: list[str] = []

    def respond(req: GenerateRequest) -> str:
        if not req.json_mode:
            return "Section text."
        prompt = req.messages[0].content
        part = prompt.split("This is part ", 1)[1].split(" ", 1)[0]
        attempts[part] = attempts.get(part, 0) + 1
        if part == "1":  # wrapped in prose and a fence, with a trailing comma: repaired locally
            return 'Here you go:\n```json\n{"summary": "One.", "actions": [],}\n```'
        if part == "2" and attempts[part] == 1:  # broken, then fixed on the retry
            return "{not json"
        if part == "3":  # never valid
            return "I cannot do that."
        return json.dumps({"summary": f"Part {part}.", "decisions": [{"text": "Ship it"}]})

    backend = FakeLLMBackend(window=4096, responder=respond)
    gen = generator(backend, warn=warnings.append)
    result = await gen.generate(meta(), transcript(repeat=60))
    assert result.mode == "map-reduce"
    assert attempts["1"] == 1 and attempts["2"] == 2 and attempts["3"] == 2
    retry = next(c for c in backend.calls if c.json_mode and len(c.messages) == 3)
    assert (
        retry.messages[1].role == "assistant" and "could not be parsed" in retry.messages[2].content
    )
    assert any(w.startswith(f"Part 3 of {result.chunks}") for w in warnings)


async def test_map_reduce_fails_when_every_chunk_fails() -> None:
    backend = FakeLLMBackend(window=4096, responder=lambda r: "nope" if r.json_mode else "x")
    with pytest.raises(MM3Error) as err:
        await generator(backend).generate(meta(), transcript(repeat=60))
    assert err.value.code == "E_LLM_BAD_RESPONSE"


async def test_window_too_small_for_map_reduce() -> None:
    with pytest.raises(MM3Error) as err:
        await generator(FakeLLMBackend(window=1024)).generate(meta(), transcript(repeat=60))
    assert err.value.code == "E_LLM_CONTEXT"


async def test_window_errors_name_the_real_limit() -> None:
    with pytest.raises(MM3Error) as err:
        await generator(FakeLLMBackend(window=2048)).generate(meta(), transcript(repeat=60))
    assert "“fake-model” can only read 2,048 tokens" in err.value.message
    assert "larger context window" in err.value.hint
    # When the setting, not the model, is the limit, the hint points at the setting.
    with pytest.raises(MM3Error) as err:
        await generator(FakeLLMBackend(window=131072), max_context=2048).generate(
            meta(), transcript(repeat=60)
        )
    assert "Your settings limit local models to 2,048 tokens" in err.value.message
    assert "Settings → Notes" in err.value.hint


async def test_embedding_model_is_refused_before_any_call() -> None:
    backend = FakeLLMBackend(models=(), embedding_models=("fake-model",))
    with pytest.raises(MM3Error) as err:
        await generator(backend).generate(meta(), transcript())
    assert err.value.code == "E_LLM_MODEL_UNSUITABLE"
    assert "embedding model" in err.value.message
    assert backend.calls == []


async def test_max_context_caps_local_models_only() -> None:
    local = FakeLLMBackend(window=131072)
    result = await generator(local, max_context=4096).generate(meta(), transcript(repeat=60))
    assert result.mode == "map-reduce"
    cloud = FakeLLMBackend(window=131072, is_local=False)
    result = await generator(cloud, max_context=4096, cloud_consent=True).generate(
        meta(), transcript(repeat=60)
    )
    assert result.mode == "full"


async def test_regenerate_section_sends_previous_and_feedback() -> None:
    backend = FakeLLMBackend()
    result = await generator(backend).generate(meta(), transcript())
    note = build_note(meta().model_copy(update={"template_id": "executive-summary"}),
                      result.sections)  # fmt: skip
    regen = FakeLLMBackend(responder=lambda r: "## Summary\nShorter summary.")
    body = await regenerate_section(
        note,
        "summary",
        "Make it shorter.",
        transcript=transcript(),
        template=load_library().get("executive-summary"),
        backend=regen,
        model="fake-model",
    )
    assert body == "Shorter summary."
    prompt = regen.calls[0].messages[0].content
    assert "<previous_version>\nSimulated summary" in prompt
    assert "What the user wants changed:\nMake it shorter." in prompt
    assert len(regen.calls) == 1


async def test_regenerate_unknown_section_uses_generic_instructions() -> None:
    regen = FakeLLMBackend(responder=lambda r: "Custom.")
    gen = generator(regen)
    body = await gen.regenerate_section(meta(), transcript(), "my-notes", title="My Notes")
    assert body == "Custom."
    assert 'Write the "My Notes" section' in regen.calls[0].messages[0].content


# -- map-reduce helpers -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        '{"summary": "s"}',
        '```json\n{"summary": "s"}\n```',
        'Sure, here it is: {"summary": "s", "points": [],} Hope that helps!',
        '<think>reasoning {"x": 1}</think>{"summary": "s"}',
    ],
)
def test_parse_extraction_repairs(text: str) -> None:
    assert parse_extraction(text).summary == "s"


def test_parse_extraction_normalises_shapes() -> None:
    got = parse_extraction(
        json.dumps(
            {
                "summary": ["a", "b"],
                "points": ["plain string"],
                "decisions": {"text": "single object"},
                "actions": [{"text": "a task", "owner": None, "time": 75}],
                "questions": None,
            }
        )
    )
    assert got.summary == "a b"
    assert got.points[0].text == "plain string"
    assert got.decisions[0].text == "single object"
    assert (
        got.actions[0].task == "a task"
        and got.actions[0].owner == ""
        and got.actions[0].time == "75"
    )
    assert got.questions == []


@pytest.mark.parametrize("text", ["", "no json here", "[1, 2]", '{"points": [{"no": "text"}]}'])
def test_parse_extraction_errors(text: str) -> None:
    with pytest.raises(ExtractionError):
        parse_extraction(text)


def test_merge_dedupes_and_keeps_order() -> None:
    a = ChunkExtraction.model_validate(
        {
            "summary": "First part.",
            "decisions": [{"text": "Launch on October 21", "time": "03:12"}],
            "actions": [{"task": "Finish the billing migration", "owner": "Marcus"}],
        }
    )
    b = ChunkExtraction.model_validate(
        {
            "summary": "Second part.",
            "decisions": [{"text": "launch on October 21!"}],
            "actions": [
                {"task": "Finish the billing migration script by Friday", "owner": "Marcus"},
                {"task": "Finish the billing migration", "owner": "Elena"},
            ],
        }
    )
    merged = merge([a, None, b], ["00:00-05:00", "05:00-10:00", "10:00-15:00"])
    assert merged.skipped_chunks == [1]
    assert [s for _, s in merged.summaries] == ["First part.", "Second part."]
    assert len(merged.decisions) == 1 and merged.decisions[0].time == "03:12"
    owners = [(x.owner, x.task) for x in merged.actions]
    assert owners == [
        ("Marcus", "Finish the billing migration script by Friday"),  # longer version kept
        ("Elena", "Finish the billing migration"),  # different owner: not a duplicate
    ]


def test_render_notes_truncates_minor_material_first() -> None:
    chunk = ChunkExtraction.model_validate(
        {
            "summary": "S " * 50,
            "points": [{"text": f"point {i} " + "x" * 80} for i in range(200)],
            "decisions": [{"text": "Keep me"}],
            "actions": [{"task": "Do it", "owner": "Ann", "due": "Friday"}],
        }
    )
    full, cut = render_notes(merge([chunk]))
    assert not cut and "point 199" in full
    small, cut = render_notes(merge([chunk]), max_tokens=400)
    assert cut and "Keep me" in small and "- Ann: Do it (due: Friday)" in small
    assert len(small) < len(full)


def test_truncated_json_is_salvaged() -> None:
    cut = (
        '{"summary": "s", "decisions": [{"text": "Ship it"}], "actions": [{"task": "Do it",'
        ' "owner": "Ann"}], "questions": [], "points": [{"text": "one"}, {"text": "tw'
    )
    got = parse_extraction(cut)
    assert got.decisions[0].text == "Ship it" and got.actions[0].owner == "Ann"
    assert [p.text for p in got.points] == ["one"]
    assert close_truncated('{"a": "unterminated') is None
    assert close_truncated("no json") is None
    assert close_truncated('{"a": ["x\\"]", "y"], "b": "q') == '{"a": ["x\\"]", "y"]}'


async def test_cut_off_extraction_asks_for_a_shorter_answer() -> None:
    def respond(req: GenerateRequest) -> str:
        if not req.json_mode:
            return "ok"
        return "{nope" if len(req.messages) == 1 else '{"summary": "short"}'

    backend = FakeLLMBackend(window=4096, responder=respond)
    original = backend.generate

    async def cut_off(req: GenerateRequest) -> Any:
        result = await original(req)
        return replace(result, finish_reason="length") if req.json_mode else result

    backend.generate = cut_off  # type: ignore[method-assign]
    await generator(backend).generate(meta(), transcript(repeat=60))
    retry = next(c for c in backend.calls if c.json_mode and len(c.messages) == 3)
    assert "cut off because it was too long" in retry.messages[2].content


async def test_high_detail_template_keeps_more_points_with_topics() -> None:
    """ADR-0039: ``params.detail: high`` (Default Notes) asks the map step for up to 30 points
    with their specifics and a topic label, gives it more output room, and shows the topics to
    the reduce step. Too small a window falls back to standard notes."""
    point = {"topic": "Order database", "text": "Oracle 12c moves to PostgreSQL 16 by March",
             "speaker": "Priya", "time": "00:10"}  # fmt: skip

    exchange = {"asked_by": "Marcus", "question": "Who owns the cut-over?", "answered_by": "Priya",
                "answer": "Priya does, with two engineers", "time": "00:20"}  # fmt: skip

    def respond(req: GenerateRequest) -> str:
        if not req.json_mode:
            return "ok"
        return json.dumps({"summary": "Part.", "points": [point], "exchanges": [exchange]})

    backend = FakeLLMBackend(window=16384, responder=respond)
    result = await generator(backend, "default-notes").generate(meta(), transcript(repeat=400))
    assert result.mode == "map-reduce"
    json_calls = [c for c in backend.calls if c.json_mode]
    assert all(c.max_tokens == 3500 for c in json_calls)
    assert all("up to 30" in c.messages[0].content and '"topic"' in c.messages[0].content
               and '"exchanges"' in c.messages[0].content for c in json_calls)  # fmt: skip
    # ``task_candidates: relevant`` reaches the map step's candidate list too
    assert all("small talk and personal remarks are not" in c.messages[0].content
               for c in json_calls)  # fmt: skip
    notes = next(c for c in backend.calls if not c.json_mode).messages[0].content
    assert "- [00:10] (Order database) Priya: Oracle 12c moves to PostgreSQL 16 by March" in notes
    assert ("Questions and answers:\n- [00:20] Marcus asked: Who owns the cut-over? | Priya: "
            "Priya does, with two engineers") in notes  # fmt: skip

    small = FakeLLMBackend(window=4096, responder=respond)
    await generator(small, "default-notes").generate(meta(), transcript(repeat=60))
    assert all(c.max_tokens == 1500 and "most important" in c.messages[0].content
               and '"exchanges"' not in c.messages[0].content
               for c in small.calls if c.json_mode)  # fmt: skip
    # Standard templates are unchanged.
    plain = FakeLLMBackend(window=16384, responder=respond)
    await generator(plain).generate(meta(), transcript(repeat=400))
    assert all(c.max_tokens == 1500 and "each commitment is an action item" in c.messages[0].content
               for c in plain.calls if c.json_mode)  # fmt: skip
    plain_notes = next(c for c in plain.calls if not c.json_mode).messages[0].content
    assert "Questions and answers:" in plain_notes  # a model may volunteer them; still rendered


# -- context size (ADR-0017, ADR-0043) ---------------------------------------------------------


def call_size(req: GenerateRequest) -> int:
    """Estimated tokens of one call: everything sent plus its output room."""
    sent = "\n".join([req.system or "", *(m.content for m in req.messages)])
    return estimate_tokens(sent) + (req.max_tokens or 0)


def assert_every_call_fits(calls: list[GenerateRequest]) -> int:
    """One ``num_ctx`` per note, and every call fits inside it with the safety margin."""
    sizes = {c.num_ctx for c in calls}
    assert len(sizes) == 1
    num_ctx = sizes.pop()
    assert num_ctx is not None
    assert all(call_size(c) * (1 + CONTEXT_MARGIN) <= num_ctx for c in calls)
    return num_ctx


def point_responder(n_points: int, words: int = 12) -> Any:
    def respond(req: GenerateRequest) -> str:
        if not req.json_mode:
            return "ok"
        part = req.messages[0].content.split("This is part ", 1)[1].split(" ", 1)[0]
        points = [{"text": " ".join(f"p{part}w{i}x{j}" for j in range(words)), "time": "00:10",
                   "topic": "Topic"} for i in range(n_points)]  # fmt: skip
        return json.dumps({"summary": f"Part {part}.", "points": points})

    return respond


@pytest.mark.parametrize(
    ("template_id", "old", "new"),
    [("executive-summary", 13312, 13312), ("default-notes", 15360, 13312)],
)
async def test_map_reduce_num_ctx_fits_the_largest_call_once(
    template_id: str, old: int, new: int
) -> None:
    """The output reserve is no longer counted twice: map-reduce asks for the largest real call
    plus the margin, under ``usable + reserve`` (``old``, rounded, before 15f), and every call
    still fits. Executive Summary's small reserve rounds to the same size as before."""
    template = load_library().get(template_id)
    reserve = max(template.max_tokens(s) for s in template.sections)
    assert old == -(-(usable_tokens(16384) + reserve) // 1024) * 1024
    backend = FakeLLMBackend(window=16384, responder=point_responder(5))
    result = await generator(backend, template_id).generate(meta(), transcript(repeat=400))
    assert result.mode == "map-reduce"
    num_ctx = assert_every_call_fits(backend.calls)
    assert num_ctx == new
    largest = max(call_size(c) for c in backend.calls if c.json_mode)
    assert largest * (1 + CONTEXT_MARGIN) < usable_tokens(16384) + reserve
    assert largest <= usable_tokens(16384)  # map prompts keep to their budget, stamps included
    assert num_ctx - 1024 < largest * (1 + CONTEXT_MARGIN) + 400  # rounded up, not padded


async def test_full_mode_num_ctx_covers_its_largest_section_with_the_margin() -> None:
    backend = FakeLLMBackend(window=16384)
    result = await generator(backend, "default-notes").generate(meta(), transcript(repeat=20))
    assert result.mode == "full"
    num_ctx = assert_every_call_fits(backend.calls)
    assert num_ctx < 16384


async def test_over_long_reduce_notes_never_exceed_num_ctx() -> None:
    """Map replies far larger than the reduce room are cut to fit the chosen context."""
    warnings: list[str] = []
    backend = FakeLLMBackend(window=16384, responder=point_responder(25, words=40))
    gen = generator(backend, "default-notes", warn=warnings.append)
    result = await gen.generate(meta(), transcript(repeat=600))
    assert result.mode == "map-reduce" and result.chunks >= 4
    assert_every_call_fits(backend.calls)
    assert any("some minor points were left out" in w for w in warnings)


async def test_retries_repeat_only_what_fits_the_context() -> None:
    """A huge broken map reply and a one-paragraph Summary Detailed are repeated back only as far
    as the note's context allows."""

    def respond(req: GenerateRequest) -> str:
        if req.json_mode:
            return "{broken " + "x" * 30000 if len(req.messages) == 1 else '{"summary": "s"}'
        return "One paragraph only. " * 400

    backend = FakeLLMBackend(window=16384, responder=respond)
    await generator(backend, "default-notes").generate(meta(), transcript(repeat=400))
    assert_every_call_fits(backend.calls)
    repairs = [c for c in backend.calls if c.json_mode and len(c.messages) == 3]
    floors = [c for c in backend.calls if not c.json_mode and len(c.messages) == 3]
    assert repairs and floors
    assert all(250 * 4 <= len(c.messages[1].content) <= 4000 for c in repairs)
    assert all(c.messages[1].content for c in floors)


async def test_regeneration_context_includes_the_previous_body() -> None:
    backend = FakeLLMBackend(window=16384, responder=lambda r: "New text.")
    gen = generator(backend, "default-notes")
    previous = "An earlier, much longer version of this section. " * 300
    await gen.regenerate_section(
        meta(), transcript(repeat=20), "topics", previous=previous, feedback="More."
    )
    assert previous.strip() in backend.calls[0].messages[0].content
    assert_every_call_fits(backend.calls)


def test_render_notes_cuts_points_before_exchanges() -> None:
    chunk = ChunkExtraction.model_validate({
        "summary": "Part.",
        "points": [{"text": f"alpha{i} beta{i} gamma{i} delta{i} epsilon{i}", "time": "00:01"}
                   for i in range(40)],
        "exchanges": [{"asked_by": "A", "question": f"question {i}?", "answered_by": "B",
                       "answer": "an answer"} for i in range(4)],
        "actions": [{"task": "Send the plan", "owner": "B"}],
    })  # fmt: skip
    merged = merge([chunk, chunk])  # duplicates removed
    assert len(merged.exchanges) == 4
    full, cut = render_notes(merged)
    assert not cut and full.count(" asked: ") == 4
    small, cut = render_notes(merged, max_tokens=estimate_tokens(full) * 2 // 3)
    assert cut and small.count(" asked: ") == 4 and 0 < small.count("alpha") < 40
    assert "B: Send the plan" in small  # actions are always kept


@pytest.mark.parametrize("template_id", BUILTIN_IDS)
async def test_every_builtin_template_generates_a_valid_note(template_id: str) -> None:
    template = load_library().get(template_id)
    note_meta = meta().model_copy(update={"template_id": template_id, "model": "fake-model"})
    result = await generator(FakeLLMBackend(), template_id).generate(note_meta, transcript())
    text = render_note(build_note(note_meta, result.sections))
    parsed = parse_note(text)
    assert parsed.ok
    assert [s.id for s in parsed.note.sections] == [s.id for s in template.sections]
    assert text.startswith("---\n") and "# Launch" in text  # frontmatter and Appendix B header
    assert "**Participants:** Priya, Marcus" in text
    assert f"mm3-template: {template_id}" in text
    if template.params.ai_recommendations:
        assert parsed.note.sections[-1].id == "ai-recommendations"
