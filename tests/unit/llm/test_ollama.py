from __future__ import annotations

import json

import httpx
import pytest
import respx

from meetingmaster3.errors import MM3Error
from meetingmaster3.llm import _http
from meetingmaster3.llm.base import GenerateRequest, Message
from meetingmaster3.llm.ollama import OllamaBackend

BASE = "http://127.0.0.1:11434"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr(_http.asyncio, "sleep", instant)
    monkeypatch.setattr(_http, "backoff_delay", lambda *a, **k: 0.0)


def backend(**kw: object) -> OllamaBackend:
    return OllamaBackend("ollama", BASE, **kw)  # type: ignore[arg-type]


REQ = GenerateRequest(model="qwen3:4b", prompt="hi", system="be brief", max_tokens=50, stop=("X",))


@respx.mock
async def test_generate_builds_payload_and_parses() -> None:
    route = respx.post(f"{BASE}/api/chat").respond(
        json={
            "model": "qwen3:4b",
            "message": {"role": "assistant", "content": "hello"},
            "done_reason": "stop",
            "prompt_eval_count": 7,
            "eval_count": 3,
        }
    )
    result = await backend().generate(REQ)
    assert (result.text, result.finish_reason) == ("hello", "stop")
    assert (result.usage.input_tokens, result.usage.output_tokens) == (7, 3)  # type: ignore[union-attr]
    body = json.loads(route.calls[0].request.content)
    assert body["messages"][0] == {"role": "system", "content": "be brief"}
    assert body["stream"] is False
    assert body["options"]["num_predict"] == 50 and body["options"]["stop"] == ["X"]
    assert body["options"]["num_ctx"] >= 4096


@respx.mock
async def test_num_ctx_grows_with_prompt_and_is_capped_by_model_window() -> None:
    route = respx.post(f"{BASE}/api/chat").respond(json={"message": {"content": "ok"}})
    b = backend()
    big = GenerateRequest(model="m", prompt="word " * 8000, max_tokens=100)  # ~10k tokens
    await b.generate(big)
    assert json.loads(route.calls[0].request.content)["options"]["num_ctx"] >= 10_000
    b._ctx["m"] = 8192
    await b.generate(big)
    assert json.loads(route.calls[1].request.content)["options"]["num_ctx"] == 8192


@respx.mock
async def test_json_mode_and_params() -> None:
    route = respx.post(f"{BASE}/api/chat").respond(json={"message": {"content": "{}"}})
    await backend(params={"top_p": 0.9}).generate(
        GenerateRequest(model="m", messages=(Message("user", "x"),), json_mode=True)
    )
    body = json.loads(route.calls[0].request.content)
    assert body["format"] == "json" and body["options"]["top_p"] == 0.9


@respx.mock
async def test_think_flag_is_sent_only_when_set() -> None:
    route = respx.post(f"{BASE}/api/chat").respond(json={"message": {"content": "ok"}})
    await backend().generate(GenerateRequest(model="m", prompt="x"))
    await backend().generate(GenerateRequest(model="m", prompt="x", think=False))
    first, second = (json.loads(c.request.content) for c in route.calls)
    assert "think" not in first and second["think"] is False


@respx.mock
async def test_stream_yields_pieces() -> None:
    ndjson = "\n".join(
        json.dumps(e)
        for e in [
            {"message": {"content": "Hel"}, "done": False},
            {"message": {"content": "lo"}, "done": False},
            {"message": {"content": ""}, "done": True},
        ]
    )
    respx.post(f"{BASE}/api/chat").respond(content=ndjson)
    pieces = [p async for p in backend().stream(REQ)]
    assert pieces == ["Hel", "lo"]


@respx.mock
async def test_stream_error_event_maps_context_error() -> None:
    respx.post(f"{BASE}/api/chat").respond(
        content=json.dumps({"error": "prompt exceeds the context length"})
    )
    with pytest.raises(MM3Error) as exc:
        [p async for p in backend().stream(REQ)]
    assert exc.value.code == "E_LLM_CONTEXT"


@respx.mock
async def test_list_models_and_context_window_from_show() -> None:
    respx.get(f"{BASE}/api/tags").respond(
        json={"models": [{"name": "qwen3:8b", "size": 5_200_000_000}]}
    )
    respx.post(f"{BASE}/api/show").respond(
        json={"model_info": {"general.architecture": "qwen3", "qwen3.context_length": 40960}}
    )
    b = backend()
    assert b.context_window("qwen3:8b") is None
    models = await b.list_models()
    assert [(m.id, m.size_bytes, m.context_window) for m in models] == [
        ("qwen3:8b", 5_200_000_000, 40960)
    ]
    assert b.context_window("qwen3:8b") == 40960
    assert models[0].can_generate is None  # this (older) Ollama does not report capabilities


@respx.mock
async def test_list_models_flags_embedding_models() -> None:
    respx.get(f"{BASE}/api/tags").respond(
        json={"models": [{"name": "nomic-embed-text:latest"}, {"name": "qwen3:8b"}]}
    )

    def show(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content)["model"].startswith("nomic"):
            info = {"nomic-bert.context_length": 2048}
            return httpx.Response(200, json={"capabilities": ["embedding"], "model_info": info})
        info = {"qwen3.context_length": 40960}
        caps = ["completion", "tools", "thinking"]
        return httpx.Response(200, json={"capabilities": caps, "model_info": info})

    respx.post(f"{BASE}/api/show").mock(side_effect=show)
    b = backend()
    models = {m.id: m for m in await b.list_models()}
    assert models["nomic-embed-text:latest"].can_generate is False
    assert models["nomic-embed-text:latest"].context_window == 2048
    assert models["qwen3:8b"].can_generate is True
    assert b.can_generate("unknown:1") is None


@respx.mock
async def test_connection_ok_reports_missing_default_model() -> None:
    respx.get(f"{BASE}/api/tags").respond(json={"models": [{"name": "a:1"}]})
    status = await backend(default_model="b:2").test_connection()
    assert status.ok and status.default_model_present is False
    assert "ollama pull b:2" in status.hint


@respx.mock
async def test_connection_unreachable_is_reported_not_raised() -> None:
    respx.get(f"{BASE}/api/tags").mock(side_effect=httpx.ConnectError("refused"))
    status = await backend().test_connection()
    assert not status.ok and status.code == "E_LLM_UNREACHABLE"


@respx.mock
async def test_429_is_retried_then_succeeds() -> None:
    route = respx.post(f"{BASE}/api/chat").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(503),
            httpx.Response(200, json={"message": {"content": "ok"}}),
        ]
    )
    assert (await backend().generate(REQ)).text == "ok"
    assert route.call_count == 3


@respx.mock
async def test_persistent_429_maps_to_rate_limit() -> None:
    respx.post(f"{BASE}/api/chat").respond(429)
    with pytest.raises(MM3Error) as exc:
        await backend().generate(REQ)
    assert exc.value.code == "E_LLM_RATE_LIMIT"


@respx.mock
async def test_auth_and_context_and_timeout_mapping() -> None:
    route = respx.post(f"{BASE}/api/chat")
    route.respond(401)
    with pytest.raises(MM3Error) as exc:
        await backend().generate(REQ)
    assert exc.value.code == "E_LLM_AUTH" and route.call_count == 1  # no retry on auth

    route.respond(400, json={"error": "input is too long for the context window"})
    with pytest.raises(MM3Error) as exc:
        await backend().generate(REQ)
    assert exc.value.code == "E_LLM_CONTEXT"

    route.mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(MM3Error) as exc:
        await backend().generate(REQ)
    assert exc.value.code == "E_LLM_TIMEOUT" and route.call_count == 3  # timeouts not retried


@respx.mock
async def test_unload_all_evicts_running_models() -> None:
    respx.get(f"{BASE}/api/ps").mock(
        side_effect=[
            httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]}),
            httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]}),  # still unloading
            httpx.Response(200, json={"models": []}),
        ]
    )
    gen = respx.post(f"{BASE}/api/generate").respond(json={})
    assert await backend().unload_all() == ["qwen3:8b"]
    assert json.loads(gen.calls[0].request.content) == {"model": "qwen3:8b", "keep_alive": 0}


def test_is_local_rules() -> None:
    assert OllamaBackend("a", "http://127.0.0.1:11434").is_local
    assert OllamaBackend("a", "http://localhost:11434").is_local
    assert OllamaBackend("a", "http://host.docker.internal:11434").is_local
    assert not OllamaBackend("a", "http://192.168.1.20:11434").is_local
    assert not OllamaBackend("a", "https://ollama.example.com").is_local


def test_request_needs_content() -> None:
    with pytest.raises(MM3Error):
        GenerateRequest(model="m").chat()
