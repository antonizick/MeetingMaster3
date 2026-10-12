"""Which models can write notes, and which one the UI suggests."""

from __future__ import annotations

import pytest

from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.base import ModelInfo
from meetingmaster3.llm.fake import FakeLLMBackend
from meetingmaster3.templates import model_check


def test_suggest_prefers_a_tested_model_then_the_first_usable() -> None:
    local = FakeLLMBackend()
    models = [
        ModelInfo("nomic-embed-text:latest", context_window=2048, can_generate=False),
        ModelInfo("gemma2:9b", context_window=8192, can_generate=True),
        ModelInfo("qwen3:8b", context_window=40960, can_generate=True),
    ]
    assert model_check.suggest(models, local, 16384) == "qwen3:8b"
    assert model_check.suggest(models[:2], local, 16384) == "gemma2:9b"
    assert model_check.suggest(models[:1], local, 16384) is None


def test_the_context_cap_applies_to_local_models_only() -> None:
    big = ModelInfo("m", context_window=131072)
    assert not model_check.usable(big, FakeLLMBackend(), 2048)
    assert model_check.usable(big, FakeLLMBackend(is_local=False), 2048)
    assert model_check.usable(ModelInfo("unknown"), FakeLLMBackend(), 16384)


async def test_model_problem_is_none_for_cloud_and_unknown() -> None:
    cloud = FakeLLMBackend(is_local=False, window=1024)
    assert await model_check.model_problem(cloud, "fake-model", 16384) is None
    assert await model_check.model_problem(FakeLLMBackend(window=None), "x", 16384) is None
    problem = await model_check.model_problem(FakeLLMBackend(window=2048), "x", 16384)
    assert isinstance(problem, MM3Error) and problem.code == "E_LLM_CONTEXT"


@pytest.mark.parametrize("window", [4096, 8192])
async def test_small_but_workable_windows_pass(window: int) -> None:
    assert await model_check.model_problem(FakeLLMBackend(window=window), "x", 16384) is None
