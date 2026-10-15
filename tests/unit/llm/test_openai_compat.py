from __future__ import annotations

import json

import httpx
import pytest
import respx

from meetingmaster3.errors import MM3Error
from meetingmaster3.llm import _http
from meetingmaster3.llm.base import GenerateRequest
from meetingmaster3.llm.openai_compat import OpenAICompatBackend

BASE = "https://openrouter.ai/api/v1"
REQ = GenerateRequest(model="vendor/model", prompt="hi", system="sys", json_mode=True, max_tokens=9)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr(_http.asyncio, "sleep", instant)


def backend(**kw: object) -> OpenAICompatBackend:
    return OpenAICompatBackend("or", BASE, api_key="sk-secret-key-123456", kind="openrouter", **kw)  # type: ignore[arg-type]


@respx.mock
async def test_generate_sends_auth_and_parses() -> None:
    route = respx.post(f"{BASE}/chat/completions").respond(
        json={
            "model": "vendor/model",
            "choices": [{"message": {"content": "hey"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2},
        }
    )
    result = await backend(headers={"HTTP-Referer": "https://example.test"}).generate(REQ)
    assert result.text == "hey" and result.usage.output_tokens == 2  # type: ignore[union-attr]
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer sk-secret-key-123456"
    assert request.headers["http-referer"] == "https://example.test"
    body = json.loads(request.content)
    assert body["response_format"] == {"type": "json_object"} and body["max_tokens"] == 9
    assert body["messages"][0] == {"role": "system", "content": "sys"}


@respx.mock
async def test_stream_parses_sse() -> None:
    sse = (
        ": keep-alive\n\n"
        'data: {"choices":[{"delta":{"content":"A"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"B"}}]}\n\n'
        'data: {"choices":[{"delta":{}}]}\n\n'
        "data: [DONE]\n\n"
    )
    respx.post(f"{BASE}/chat/completions").respond(content=sse)
    assert [p async for p in backend().stream(REQ)] == ["A", "B"]


@respx.mock
async def test_list_models_records_context_length() -> None:
    respx.get(f"{BASE}/models").respond(
        json={"data": [{"id": "vendor/model", "name": "Model", "context_length": 128000}]}
    )
    b = backend()
    models = await b.list_models()
    assert models[0].context_window == 128000
    assert b.context_window("vendor/model") == 128000


@respx.mock
async def test_error_mapping_and_retry() -> None:
    route = respx.post(f"{BASE}/chat/completions")
    route.respond(401)
    with pytest.raises(MM3Error) as exc:
        await backend().generate(REQ)
    assert exc.value.code == "E_LLM_AUTH"

    route.mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]}),
        ]
    )
    assert (await backend().generate(REQ)).text == "ok"

    route.respond(400, json={"error": {"code": "context_length_exceeded", "message": "too long"}})
    with pytest.raises(MM3Error) as exc:
        await backend().generate(REQ)
    assert exc.value.code == "E_LLM_CONTEXT"


@respx.mock
async def test_connection_failure_does_not_leak_key() -> None:
    respx.get(f"{BASE}/models").respond(401, json={"error": "bad key sk-secret-key-123456"})
    status = await backend().test_connection()
    assert not status.ok and status.code == "E_LLM_AUTH"
    assert "sk-secret-key-123456" not in json.dumps(status.to_dict())


def test_local_detection() -> None:
    assert OpenAICompatBackend("lm", "http://127.0.0.1:1234/v1").is_local
    assert not backend().is_local


@respx.mock
async def test_reasoning_that_uses_every_token_is_an_error() -> None:
    """15g: a reasoning model that spends max_tokens on reasoning returns content null."""
    respx.post(f"{BASE}/chat/completions").respond(
        json={
            "choices": [
                {"message": {"content": None, "reasoning": "…"}, "finish_reason": "length"}
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 9},
        }
    )
    with pytest.raises(MM3Error) as exc:
        await backend().generate(REQ)
    assert exc.value.code == "E_LLM_BAD_RESPONSE" and "output allowance" in exc.value.message


@respx.mock
async def test_cut_off_answer_with_text_is_kept() -> None:
    respx.post(f"{BASE}/chat/completions").respond(
        json={"choices": [{"message": {"content": "part"}, "finish_reason": "length"}]}
    )
    result = await backend().generate(REQ)
    assert (result.text, result.finish_reason) == ("part", "length")


@respx.mock
async def test_stream_empty_at_length_is_an_error() -> None:
    sse = (
        'data: {"choices":[{"delta":{"reasoning":"hmm"}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'
        "data: [DONE]\n\n"
    )
    respx.post(f"{BASE}/chat/completions").respond(content=sse)
    with pytest.raises(MM3Error):
        [p async for p in backend().stream(REQ)]
