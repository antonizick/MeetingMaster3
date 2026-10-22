"""``embed()`` in every backend (Phase 15i): request bodies, answers and error mapping."""

from __future__ import annotations

import io
import json
import math
from typing import Any

import boto3
import httpx
import pytest
import respx
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

from meetingmaster3.errors import MM3Error
from meetingmaster3.llm import bedrock
from meetingmaster3.llm.base import (
    E_LLM_BAD_RESPONSE,
    E_LLM_CONFIG,
    E_LLM_EMBED_UNSUPPORTED,
    supports_embeddings,
)
from meetingmaster3.llm.bedrock import BedrockBackend
from meetingmaster3.llm.fake import FakeLLMBackend, fake_embedding
from meetingmaster3.llm.ollama import OllamaBackend
from meetingmaster3.llm.openai_compat import OpenAICompatBackend

OLLAMA = "http://127.0.0.1:11434"
ROUTER = "https://openrouter.ai/api/v1"


# -- Ollama ----------------------------------------------------------------------------------


@respx.mock
async def test_ollama_embed_batches_and_keeps_order(monkeypatch: pytest.MonkeyPatch) -> None:
    from meetingmaster3.llm import ollama

    monkeypatch.setattr(ollama, "EMBED_BATCH", 2)
    seen: list[dict[str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(
            200, json={"embeddings": [[float(len(t)), 1.0] for t in body["input"]]}
        )

    respx.post(f"{OLLAMA}/api/embed").mock(side_effect=answer)
    vectors = await OllamaBackend().embed("nomic-embed-text", ["a", "bb", "ccc"])
    assert vectors == [[1.0, 1.0], [2.0, 1.0], [3.0, 1.0]]
    assert [b["input"] for b in seen] == [["a", "bb"], ["ccc"]]
    assert all(b["model"] == "nomic-embed-text" and b["keep_alive"] == "30s" for b in seen)


@respx.mock
async def test_ollama_embed_model_not_pulled_says_how_to_fix() -> None:
    respx.post(f"{OLLAMA}/api/embed").respond(404, json={"error": "model 'nope' not found"})
    with pytest.raises(MM3Error) as exc:
        await OllamaBackend().embed("nope", ["x"])
    assert exc.value.code == E_LLM_CONFIG
    assert "ollama pull nope" in exc.value.hint


@respx.mock
async def test_ollama_embed_with_a_chat_model_is_unsupported() -> None:
    respx.post(f"{OLLAMA}/api/embed").respond(
        400, json={"error": "this model does not support embeddings"}
    )
    with pytest.raises(MM3Error) as exc:
        await OllamaBackend().embed("qwen3:8b", ["x"])
    assert exc.value.code == E_LLM_EMBED_UNSUPPORTED


@respx.mock
async def test_ollama_embed_rejects_malformed_answers() -> None:
    route = respx.post(f"{OLLAMA}/api/embed")
    bodies: list[dict[str, Any]] = [
        {"embeddings": [[1.0]]},
        {"embeddings": [[]]},
        {"nothing": 1},
        {"embeddings": [["x"]]},
    ]
    for body in bodies:
        route.respond(json=body)
        with pytest.raises(MM3Error) as exc:
            await OllamaBackend().embed(
                "m", ["a", "b"] if body == {"embeddings": [[1.0]]} else ["a"]
            )
        assert exc.value.code == E_LLM_BAD_RESPONSE


@respx.mock
async def test_ollama_lists_only_embedding_models() -> None:
    respx.get(f"{OLLAMA}/api/tags").respond(
        json={"models": [{"name": "nomic-embed-text:latest"}, {"name": "qwen3:8b"}]}
    )

    def show(request: httpx.Request) -> httpx.Response:
        name = json.loads(request.content)["model"]
        caps = ["embedding"] if name.startswith("nomic") else ["completion", "tools"]
        return httpx.Response(200, json={"capabilities": caps, "model_info": {}})

    respx.post(f"{OLLAMA}/api/show").mock(side_effect=show)
    backend = OllamaBackend()
    assert [m.id for m in await backend.list_embedding_models()] == ["nomic-embed-text:latest"]
    assert backend.can_generate("nomic-embed-text:latest") is False  # hidden from note pickers


# -- OpenAI-compatible and OpenRouter --------------------------------------------------------


@respx.mock
async def test_openrouter_embed_sorts_by_index() -> None:
    route = respx.post(f"{ROUTER}/embeddings").respond(
        json={
            "object": "list",
            "data": [
                {"object": "embedding", "index": 1, "embedding": [0.0, 1.0]},
                {"object": "embedding", "index": 0, "embedding": [1.0, 0.0]},
            ],
            "usage": {"prompt_tokens": 4, "total_tokens": 4},
        }
    )
    backend = OpenAICompatBackend("openrouter", ROUTER, api_key="sk-x", kind="openrouter")
    vectors = await backend.embed("openai/text-embedding-3-small", ["first", "second"])
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]
    body = json.loads(route.calls[0].request.content)
    assert body == {"model": "openai/text-embedding-3-small", "input": ["first", "second"]}
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-x"


@respx.mock
async def test_server_without_embeddings_is_unsupported() -> None:
    respx.post("http://127.0.0.1:1234/v1/embeddings").respond(404, text="Not Found")
    backend = OpenAICompatBackend("lmstudio", "http://127.0.0.1:1234/v1")
    with pytest.raises(MM3Error) as exc:
        await backend.embed("some-model", ["x"])
    assert exc.value.code == E_LLM_EMBED_UNSUPPORTED


@respx.mock
async def test_openrouter_lists_embedding_models_from_its_own_endpoint() -> None:
    respx.get(f"{ROUTER}/embeddings/models").respond(
        json={
            "data": [
                {
                    "id": "openai/text-embedding-3-small",
                    "name": "Text Embedding 3 Small",
                    "context_length": 8192,
                    "pricing": {"prompt": "0.00000002", "completion": "0"},
                    "architecture": {
                        "input_modalities": ["text"],
                        "output_modalities": ["embeddings"],
                    },
                }
            ]
        }
    )
    backend = OpenAICompatBackend("openrouter", ROUTER, kind="openrouter")
    models = await backend.list_embedding_models()
    assert [m.id for m in models] == ["openai/text-embedding-3-small"]
    assert models[0].text_only is False  # never offered for writing notes
    assert models[0].price_in == pytest.approx(0.02)


@respx.mock
async def test_plain_server_picks_embedding_models_by_name() -> None:
    respx.get("http://127.0.0.1:1234/v1/models").respond(
        json={"data": [{"id": "text-embedding-nomic-embed-text-v1.5"}, {"id": "qwen3-8b"}]}
    )
    backend = OpenAICompatBackend("lmstudio", "http://127.0.0.1:1234/v1")
    assert [m.id for m in await backend.list_embedding_models()] == [
        "text-embedding-nomic-embed-text-v1.5"
    ]


# -- Bedrock ---------------------------------------------------------------------------------


def _clients() -> tuple[Any, Any]:
    kw = {"region_name": "us-east-1", "aws_access_key_id": "AKIA", "aws_secret_access_key": "s"}
    return boto3.client("bedrock-runtime", **kw), boto3.client("bedrock", **kw)


def _body(data: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(data).encode()
    return {"body": StreamingBody(io.BytesIO(raw), len(raw)), "contentType": "application/json"}


async def test_bedrock_titan_one_text_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bedrock, "EMBED_CONCURRENCY", 1)  # the Stubber answers in order
    runtime, control = _clients()
    model = "amazon.titan-embed-text-v2:0"
    with Stubber(runtime) as stub:
        for i, text in enumerate(("alpha", "beta")):
            stub.add_response(
                "invoke_model",
                _body({"embedding": [float(i), 1.0], "inputTextTokenCount": 1}),
                {
                    "modelId": model,
                    "body": json.dumps({"inputText": text, "dimensions": 1024, "normalize": True}),
                    "contentType": "application/json",
                    "accept": "application/json",
                },
            )
        backend = BedrockBackend("bedrock", runtime_client=runtime, control_client=control)
        assert await backend.embed(model, ["alpha", "beta"]) == [[0.0, 1.0], [1.0, 1.0]]
        stub.assert_no_pending_responses()


async def test_bedrock_cohere_batches_with_input_type() -> None:
    runtime, control = _clients()
    model = "cohere.embed-multilingual-v3"
    with Stubber(runtime) as stub:
        stub.add_response(
            "invoke_model",
            _body({"embeddings": [[0.5, 0.5]], "id": "x", "texts": ["q"]}),
            {
                "modelId": model,
                "body": json.dumps(
                    {"texts": ["q"], "input_type": "search_query", "truncate": "END"}
                ),
                "contentType": ANY,
                "accept": ANY,
            },
        )
        backend = BedrockBackend("bedrock", runtime_client=runtime, control_client=control)
        assert await backend.embed(model, ["q"], purpose="query") == [[0.5, 0.5]]


async def test_bedrock_maps_access_errors_and_refuses_chat_models() -> None:
    runtime, control = _clients()
    with Stubber(runtime) as stub:
        stub.add_client_error("invoke_model", service_error_code="AccessDeniedException")
        backend = BedrockBackend("bedrock", runtime_client=runtime, control_client=control)
        with pytest.raises(MM3Error) as exc:
            await backend.embed("amazon.titan-embed-text-v2:0", ["x"])
    assert exc.value.code == "E_LLM_AUTH"
    with pytest.raises(MM3Error) as exc:
        await backend.embed("anthropic.claude-haiku-5-5", ["x"])
    assert exc.value.code == E_LLM_EMBED_UNSUPPORTED


async def test_bedrock_lists_titan_and_cohere_on_demand() -> None:
    runtime, control = _clients()
    summaries = [
        {
            "modelArn": "arn:x",
            "modelId": mid,
            "modelName": mid,
            "providerName": "p",
            "outputModalities": ["EMBEDDING"],
            "inferenceTypesSupported": types,
            "modelLifecycle": {"status": "ACTIVE"},
        }
        for mid, types in (
            ("amazon.titan-embed-text-v2:0", ["ON_DEMAND"]),
            ("cohere.embed-english-v3", ["ON_DEMAND"]),
            ("amazon.titan-embed-image-v1", ["ON_DEMAND"]),
            ("amazon.titan-embed-text-v1:2:8k", ["PROVISIONED"]),
        )
    ]
    with Stubber(control) as stub:
        stub.add_response(
            "list_foundation_models",
            {"modelSummaries": summaries},
            {"byOutputModality": "EMBEDDING"},
        )
        backend = BedrockBackend("bedrock", runtime_client=runtime, control_client=control)
        ids = [m.id for m in await backend.list_embedding_models()]
    assert ids == ["amazon.titan-embed-text-v2:0", "cohere.embed-english-v3"]


# -- fake ------------------------------------------------------------------------------------


async def test_fake_embeddings_are_deterministic_unit_vectors() -> None:
    fake = FakeLLMBackend()
    a, b = await fake.embed("m", ["Costs exceeded the forecast", "Costs exceeded the forecast"])
    assert a == b == fake_embedding("Costs exceeded the forecast")
    assert math.isclose(sum(x * x for x in a), 1.0)
    assert fake.embed_calls == [("m", ("Costs exceeded the forecast",) * 2)]


def test_every_backend_reports_embedding_support() -> None:
    assert supports_embeddings(OllamaBackend())
    assert supports_embeddings(OpenAICompatBackend("x", "http://127.0.0.1:1/v1"))
    assert supports_embeddings(BedrockBackend("b"))
    assert supports_embeddings(FakeLLMBackend())
    assert not supports_embeddings(FakeLLMBackend(supports_embeddings=False))
    assert not supports_embeddings(object())
