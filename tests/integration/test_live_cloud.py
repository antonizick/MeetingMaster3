"""Live checks against real cloud backends (Phase 15g). They cost a few cents and send only the
synthetic eval meeting and short test prompts.

    MM3_LIVE_BEDROCK=1 uv run pytest -m network tests/integration/test_live_cloud.py
    MM3_LIVE_OPENROUTER=1 uv run pytest -m network tests/integration/test_live_cloud.py

The backends come from your ``config.yaml`` (and ``MM3_*`` environment): by default the backends
named ``bedrock`` and ``openrouter`` with their ``default_model``. Override with
``MM3_LIVE_BEDROCK_BACKEND`` / ``MM3_LIVE_BEDROCK_MODEL`` (and the ``OPENROUTER`` equivalents).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

from meetingmaster3.config.settings import load_settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.base import E_CONSENT_REQUIRED, GenerateRequest, LLMBackend
from meetingmaster3.llm.budget import window_for
from meetingmaster3.llm.registry import BackendRegistry
from meetingmaster3.templates.generator import NoteGenerator
from meetingmaster3.templates.loader import load_library
from tests.eval.checker import load_meetings, score_note
from tests.eval.run_eval import TODAY, Meter

pytestmark = [pytest.mark.network, pytest.mark.slow]


@dataclass(frozen=True)
class Live:
    name: str
    backend: LLMBackend
    model: str


def _live(kind: str) -> Live:
    flag = f"MM3_LIVE_{kind.upper()}"
    if os.environ.get(flag) != "1":
        pytest.skip(f"set {flag}=1 to run the live {kind} checks (they cost a few cents)")
    name = os.environ.get(f"{flag}_BACKEND", kind)
    registry = BackendRegistry(load_settings())
    if name not in registry.names():
        pytest.fail(f"no backend named {name!r} in config.yaml ({flag}_BACKEND to choose one)")
    backend = registry.get(name)
    model = os.environ.get(f"{flag}_MODEL") or registry.config(name).default_model
    if not model:
        pytest.fail(f"backend {name!r} has no default_model ({flag}_MODEL to choose one)")
    return Live(name, backend, model)


@pytest.fixture(params=["bedrock", "openrouter"])
def live(request: pytest.FixtureRequest) -> Live:
    return _live(str(request.param))


async def test_connection_and_model_list(live: Live) -> None:
    status = await live.backend.test_connection()
    assert status.ok, status.message
    assert status.default_model_present in (True, None), status.message
    models = await live.backend.list_models()
    assert models and live.model in {m.id for m in models}


async def test_context_window_is_known(live: Live) -> None:
    window = await window_for(live.backend, live.model)
    assert window > 8192, f"{live.model} would be planned for the 8192 fallback"


async def test_generate_reports_finish_and_usage(live: Live) -> None:
    result = await live.backend.generate(
        GenerateRequest(
            model=live.model, prompt="Reply with the single word: ready", max_tokens=200
        )
    )
    assert "ready" in result.text.lower()
    assert result.finish_reason == "stop"
    assert result.usage and result.usage.input_tokens and result.usage.output_tokens


async def test_stream_yields_text(live: Live) -> None:
    req = GenerateRequest(
        model=live.model, prompt="Count from 1 to 5, digits only.", max_tokens=200
    )
    pieces = [p async for p in live.backend.stream(req)]
    assert "5" in "".join(pieces)


async def test_truncated_answer_has_text_and_length(live: Live) -> None:
    """A short ``max_tokens`` gives a cut-off answer (finish ``length``) or, for a model that
    reasons first, the clear empty-answer error; never an empty success."""
    req = GenerateRequest(
        model=live.model, prompt="Write a 300-word story about a lighthouse.", max_tokens=16
    )
    try:
        result = await live.backend.generate(req)
    except MM3Error as exc:
        assert exc.code == "E_LLM_BAD_RESPONSE" and "output allowance" in exc.message
        return
    assert result.text.strip() and result.finish_reason == "length"


async def test_declined_consent_sends_nothing(live: Live) -> None:
    meter = Meter(live.backend)
    template = load_library().get("executive-summary")
    meeting = next(m for m in load_meetings() if m.templates is None)
    gen = NoteGenerator(meter, live.model, template, cloud_consent=False, today=TODAY)
    with pytest.raises(MM3Error) as exc:
        await gen.generate(meeting.meta(), meeting.named())
    assert exc.value.code == E_CONSENT_REQUIRED
    assert (meter.input_tokens, meter.unreported) == (0, 0)


async def test_whole_note_on_a_synthetic_meeting(live: Live) -> None:
    meter = Meter(live.backend)
    template = load_library().get("executive-summary")
    meeting = next(m for m in load_meetings() if m.name == "launch-sync")
    gen = NoteGenerator(meter, live.model, template, cloud_consent=True, today=TODAY)
    meta = meeting.meta().model_copy(update={"template_id": template.id, "model": live.model})
    result = await gen.generate(meta, meeting.named())
    from meetingmaster3.markdown.note_writer import build_note, render_note

    score = score_note(render_note(build_note(meta, result.sections)), meeting, template)
    assert result.mode == "full" and not result.warnings, result.warnings
    assert score.checks.get("no_empty_sections") and score.checks.get("sections_present")
    assert meter.input_tokens > 1000 and meter.unreported == 0


async def test_bad_model_id_is_a_clear_error(live: Live) -> None:
    with pytest.raises(MM3Error) as exc:
        await live.backend.generate(
            GenerateRequest(model="no-such-vendor.no-such-model-v9", prompt="hi", max_tokens=5)
        )
    assert exc.value.code in {"E_LLM_CONFIG", "E_LLM_BAD_RESPONSE"}
    assert "model" in (exc.value.message + exc.value.hint).lower()


async def test_wrong_bedrock_keys_are_an_auth_error() -> None:
    _live("bedrock")
    from meetingmaster3.llm.bedrock import BedrockBackend

    bogus = BedrockBackend(
        "bogus", access_key_id="AKIAAAAAAAAAAAAAAAAA", secret_access_key="x" * 40
    )
    status = await bogus.test_connection()
    assert not status.ok and status.code == "E_LLM_AUTH"


async def test_wrong_openrouter_key_is_an_auth_error() -> None:
    _live("openrouter")
    from meetingmaster3.llm.openai_compat import PRESET_BASE_URLS, OpenAICompatBackend

    bogus = OpenAICompatBackend(
        "bogus", PRESET_BASE_URLS["openrouter"], api_key="sk-or-v1-" + "0" * 64, kind="openrouter"
    )
    with pytest.raises(MM3Error) as exc:
        await bogus.generate(GenerateRequest(model="openai/gpt-oss-20b", prompt="hi", max_tokens=5))
    assert exc.value.code == "E_LLM_AUTH"
