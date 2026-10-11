from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytest.importorskip("boto3")
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from botocore.stub import Stubber

from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.base import GenerateRequest
from meetingmaster3.llm.bedrock import BedrockBackend, map_boto_error

MODEL = "anthropic.test-model-v1:0"
REQ = GenerateRequest(model=MODEL, prompt="hi", system="sys", max_tokens=20, stop=("X",))


def clients() -> tuple[Any, Any]:
    kw = {"region_name": "us-east-1", "aws_access_key_id": "AKIA", "aws_secret_access_key": "s"}
    return boto3.client("bedrock-runtime", **kw), boto3.client("bedrock", **kw)


def backend(runtime: Any, control: Any, **kw: Any) -> BedrockBackend:
    return BedrockBackend(
        "bedrock", default_model=MODEL, runtime_client=runtime, control_client=control, **kw
    )


async def test_generate_via_converse() -> None:
    runtime, control = clients()
    with Stubber(runtime) as stub:
        stub.add_response(
            "converse",
            {
                "output": {"message": {"role": "assistant", "content": [{"text": "hello"}]}},
                "stopReason": "end_turn",
                "usage": {"inputTokens": 4, "outputTokens": 2, "totalTokens": 6},
                "metrics": {"latencyMs": 5},
            },
            {
                "modelId": MODEL,
                "messages": [{"role": "user", "content": [{"text": "hi"}]}],
                "system": [{"text": "sys"}],
                "inferenceConfig": {"temperature": 0.2, "maxTokens": 20, "stopSequences": ["X"]},
            },
        )
        result = await backend(runtime, control).generate(REQ)
    assert (result.text, result.finish_reason) == ("hello", "end_turn")
    assert result.usage.input_tokens == 4  # type: ignore[union-attr]


async def test_client_errors_are_normalised() -> None:
    runtime, control = clients()
    cases = {
        "ThrottlingException": "E_LLM_RATE_LIMIT",
        "AccessDeniedException": "E_LLM_AUTH",
        "ModelTimeoutException": "E_LLM_TIMEOUT",
    }
    for code, expected in cases.items():
        with Stubber(runtime) as stub:
            stub.add_client_error("converse", service_error_code=code)
            with pytest.raises(MM3Error) as exc:
                await backend(runtime, control).generate(REQ)
        assert exc.value.code == expected
    with Stubber(runtime) as stub:
        stub.add_client_error(
            "converse",
            service_error_code="ValidationException",
            service_message="Input is too long for requested model",
        )
        with pytest.raises(MM3Error) as exc:
            await backend(runtime, control).generate(REQ)
    assert exc.value.code == "E_LLM_CONTEXT"


def test_missing_credentials_map_to_auth() -> None:
    assert map_boto_error(NoCredentialsError()).code == "E_LLM_AUTH"
    assert (
        map_boto_error(ClientError({"Error": {"Code": "Weird"}}, "x")).code == "E_LLM_BAD_RESPONSE"
    )


async def test_list_models_filters_to_text_and_active() -> None:
    runtime, control = clients()
    with Stubber(control) as stub:
        stub.add_response(
            "list_foundation_models",
            {
                "modelSummaries": [
                    {
                        "modelId": "b",
                        "modelArn": "arn:b",
                        "modelName": "B",
                        "outputModalities": ["TEXT"],
                        "modelLifecycle": {"status": "ACTIVE"},
                    },
                    {"modelId": "img", "modelArn": "arn:i", "outputModalities": ["IMAGE"]},
                    {
                        "modelId": "old",
                        "modelArn": "arn:o",
                        "outputModalities": ["TEXT"],
                        "modelLifecycle": {"status": "LEGACY"},
                    },
                ]
            },
            {"byOutputModality": "TEXT"},
        )
        stub.add_response(
            "list_inference_profiles",
            {
                "inferenceProfileSummaries": [
                    {
                        "inferenceProfileName": "P",
                        "inferenceProfileArn": "arn:aws:bedrock:::p",
                        "inferenceProfileId": "us.a",
                        "status": "ACTIVE",
                        "type": "SYSTEM_DEFINED",
                        "models": [{"modelArn": "arn:b"}],
                    }
                ]
            },
        )
        models = await backend(runtime, control).list_models()
    assert [m.id for m in models] == ["b", "us.a"]


async def test_test_connection_reports_auth_failure() -> None:
    runtime, control = clients()
    with Stubber(control) as stub:
        stub.add_client_error("list_foundation_models", service_error_code="ExpiredTokenException")
        status = await backend(runtime, control).test_connection()
    assert not status.ok and status.code == "E_LLM_AUTH"


class FakeStreamClient:
    def __init__(self, events: list[dict[str, Any]], fail: Exception | None = None) -> None:
        self.events, self.fail = events, fail

    def converse_stream(self, **_: Any) -> dict[str, Any]:
        if self.fail:
            raise self.fail
        return {"stream": iter(self.events)}


async def test_stream_yields_text_deltas() -> None:
    events = [
        {"contentBlockDelta": {"delta": {"text": "A"}}},
        {"messageStart": {}},
        {"contentBlockDelta": {"delta": {"text": "B"}}},
    ]
    b = BedrockBackend("bedrock", runtime_client=FakeStreamClient(events))
    assert [p async for p in b.stream(REQ)] == ["A", "B"]


async def test_stream_error_is_mapped() -> None:
    err = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow"}}, "ConverseStream"
    )
    b = BedrockBackend("bedrock", runtime_client=FakeStreamClient([], fail=err))
    with pytest.raises(MM3Error) as exc:
        [p async for p in b.stream(REQ)]
    assert exc.value.code == "E_LLM_RATE_LIMIT"


async def test_stream_cancellation_stops_worker() -> None:
    consumed = 0

    def endless() -> Any:
        nonlocal consumed
        while True:
            consumed += 1
            yield {"contentBlockDelta": {"delta": {"text": "x"}}}

    class Client:
        def converse_stream(self, **_: Any) -> dict[str, Any]:
            return {"stream": endless()}

    b = BedrockBackend("bedrock", runtime_client=Client())

    async def consume() -> None:
        async for _ in b.stream(REQ):
            await asyncio.sleep(0.01)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.1)
    settled = consumed
    await asyncio.sleep(0.1)
    assert consumed == settled  # the worker thread stopped pulling events


def test_bedrock_is_never_local() -> None:
    assert BedrockBackend("b").is_local is False
