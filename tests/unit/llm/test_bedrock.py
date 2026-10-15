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
    assert (result.text, result.finish_reason) == ("hello", "stop")
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


# -- 15g: context windows, empty answers, paging (ADR-0044, ADR-0045) ---------------------------


@pytest.mark.parametrize(
    ("model", "window"),
    [
        ("anthropic.claude-haiku-5-5", 200_000),
        ("us.anthropic.claude-sonnet-5-5", 200_000),  # geo inference profile
        ("global.anthropic.claude-sonnet-5-5", 200_000),
        ("apac.amazon.nova-pro-v1:0", 300_000),
        ("amazon.nova-micro-v1:0", 128_000),
        ("amazon.nova-2-lite-v1:0", 128_000),  # family fallback
        ("meta.llama3-8b-instruct-v1:0", 8192),  # Llama 3.0 beats the Llama 3 family entry
        ("us.meta.llama3-3-70b-instruct-v1:0", 128_000),
        ("mistral.mistral-large-2407-v1:0", 128_000),
        ("mistral.mixtral-8x7b-instruct-v0:1", 32_000),
        ("vendor.unknown-model", None),
        ("arn:aws:bedrock:us-east-1:123:application-inference-profile/x", None),
    ],
)
def test_known_context_window_matches_longest_prefix(model: str, window: int | None) -> None:
    from meetingmaster3.llm.bedrock import known_context_window

    assert known_context_window(model) == window


def test_configured_context_window_wins() -> None:
    b = BedrockBackend("b", context_window=50_000)
    assert b.context_window("anthropic.claude-haiku-5-5") == 50_000
    assert BedrockBackend("b").context_window("us.anthropic.claude-haiku-5-5") == 200_000


async def test_budget_uses_the_table_not_8192() -> None:
    from meetingmaster3.llm.budget import window_for

    assert await window_for(BedrockBackend("b"), "us.anthropic.claude-sonnet-5-5") == 200_000


def _converse_reply(text: str | None, stop: str) -> dict[str, Any]:
    content = [] if text is None else [{"text": text}]
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop,
        "usage": {"inputTokens": 4, "outputTokens": 20, "totalTokens": 24},
        "metrics": {"latencyMs": 5},
    }


async def test_empty_answer_at_max_tokens_is_an_error() -> None:
    runtime, control = clients()
    with Stubber(runtime) as stub:
        stub.add_response("converse", _converse_reply(None, "max_tokens"))
        with pytest.raises(MM3Error) as exc:
            await backend(runtime, control).generate(REQ)
    assert exc.value.code == "E_LLM_BAD_RESPONSE" and "output allowance" in exc.value.message


async def test_cut_off_answer_with_text_is_returned_as_length() -> None:
    runtime, control = clients()
    with Stubber(runtime) as stub:
        stub.add_response("converse", _converse_reply("partial", "max_tokens"))
        result = await backend(runtime, control).generate(REQ)
    assert (result.text, result.finish_reason) == ("partial", "length")


async def test_filtered_empty_answer_is_an_error() -> None:
    runtime, control = clients()
    with Stubber(runtime) as stub:
        stub.add_response("converse", _converse_reply("", "content_filtered"))
        with pytest.raises(MM3Error) as exc:
            await backend(runtime, control).generate(REQ)
    assert "content filter" in exc.value.message


async def test_stream_empty_at_max_tokens_is_an_error() -> None:
    events: list[dict[str, Any]] = [
        {"messageStart": {}},
        {"messageStop": {"stopReason": "max_tokens"}},
    ]
    b = BedrockBackend("bedrock", runtime_client=FakeStreamClient(events))
    with pytest.raises(MM3Error) as exc:
        [p async for p in b.stream(REQ)]
    assert exc.value.code == "E_LLM_BAD_RESPONSE"


async def test_stream_with_text_and_normal_stop_is_fine() -> None:
    events: list[dict[str, Any]] = [
        {"contentBlockDelta": {"delta": {"text": "A"}}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]
    b = BedrockBackend("bedrock", runtime_client=FakeStreamClient(events))
    assert [p async for p in b.stream(REQ)] == ["A"]


async def test_inference_profiles_are_paged() -> None:
    runtime, control = clients()

    def profile(pid: str) -> dict[str, Any]:
        return {
            "inferenceProfileName": pid,
            "inferenceProfileArn": f"arn:aws:bedrock:::{pid}",
            "inferenceProfileId": pid,
            "status": "ACTIVE",
            "type": "SYSTEM_DEFINED",
            "models": [{"modelArn": "arn:b"}],
        }

    with Stubber(control) as stub:
        stub.add_response("list_foundation_models", {"modelSummaries": []}, None)
        stub.add_response(
            "list_inference_profiles",
            {"inferenceProfileSummaries": [profile("us.a")], "nextToken": "t1"},
        )
        stub.add_response(
            "list_inference_profiles",
            {"inferenceProfileSummaries": [profile("us.b")]},
            {"nextToken": "t1"},
        )
        models = await backend(runtime, control).list_models()
    assert [m.id for m in models] == ["us.a", "us.b"]


async def test_connection_hints_an_unknown_context_window() -> None:
    runtime, control = clients()
    with Stubber(control) as stub:
        stub.add_response(
            "list_foundation_models",
            {
                "modelSummaries": [
                    {"modelId": "vendor.x", "modelArn": "arn:x", "outputModalities": ["TEXT"]}
                ]
            },
            None,
        )
        stub.add_response("list_inference_profiles", {"inferenceProfileSummaries": []})
        status = await BedrockBackend(
            "b", default_model="vendor.x", runtime_client=runtime, control_client=control
        ).test_connection()
    assert status.ok and "context window" in status.hint and "8192" in status.hint


# -- 15g: real ValidationException texts, recorded live on 2026-10-15 (sanitised) -------------

PROFILE_ONLY = (
    "Invocation of model ID anthropic.claude-haiku-5-5 with on-demand throughput isn’t supported. "  # noqa: RUF001 - AWS sends this quote
    "Retry your request with the ID or ARN of an inference profile that contains this model."
)
TEMPERATURE = "The model returned the following errors: `temperature` is deprecated for this model."
THINKING_OFF = (
    'The model returned the following errors: To turn thinking off on this model, send "thinking":'
    ' {"type": "between_tools"} instead of {"type": "disabled"}.'
)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (PROFILE_ONLY, "only be called through an inference profile"),
        ("The provided model identifier is invalid.", "does not know this model ID"),
        ("The provided model doesn't support on-demand throughput.", "Provisioned Throughput"),
        (THINKING_OFF, 'send "thinking": {"type": "between_tools"}'),
    ],
)
async def test_real_validation_errors_are_clear_config_errors(message: str, expected: str) -> None:
    runtime, control = clients()
    with Stubber(runtime) as stub:
        stub.add_client_error(
            "converse", service_error_code="ValidationException", service_message=message
        )
        with pytest.raises(MM3Error) as exc:
            await backend(runtime, control).generate(REQ)
    assert exc.value.code == "E_LLM_CONFIG" and expected in exc.value.message + exc.value.hint
    assert "The model returned the following errors" not in exc.value.message


async def test_rejected_temperature_is_dropped_and_remembered() -> None:
    runtime, control = clients()
    reply = {
        "output": {"message": {"role": "assistant", "content": [{"text": "ready"}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 4, "outputTokens": 1, "totalTokens": 5},
        "metrics": {"latencyMs": 5},
    }
    without = {
        "modelId": MODEL,
        "messages": [{"role": "user", "content": [{"text": "hi"}]}],
        "system": [{"text": "sys"}],
        "inferenceConfig": {"maxTokens": 20, "stopSequences": ["X"]},
    }
    b = backend(runtime, control)
    with Stubber(runtime) as stub:
        stub.add_client_error(
            "converse", service_error_code="ValidationException", service_message=TEMPERATURE
        )
        stub.add_response("converse", reply, without)  # the retry has no temperature
        stub.add_response("converse", reply, without)  # and so has the next call
        assert (await b.generate(REQ)).text == "ready"
        assert (await b.generate(REQ)).text == "ready"
        stub.assert_no_pending_responses()


async def test_stream_drops_rejected_temperature() -> None:
    calls: list[dict[str, Any]] = []

    class Client:
        def converse_stream(self, **kw: Any) -> dict[str, Any]:
            calls.append(kw)
            if "temperature" in kw["inferenceConfig"]:
                raise ClientError(
                    {"Error": {"Code": "ValidationException", "Message": TEMPERATURE}},
                    "ConverseStream",
                )
            return {"stream": iter([{"contentBlockDelta": {"delta": {"text": "ok"}}}])}

    b = BedrockBackend("bedrock", runtime_client=Client())
    assert [p async for p in b.stream(REQ)] == ["ok"]
    assert len(calls) == 2


OPUS_NO_DISABLE = (
    'The model returned the following errors: "thinking.type.disabled" is not supported for this '
    'model. Use "thinking.type.adaptive" and "output_config.effort" to control thinking behavior.'
)


class Recorder:
    """A runtime client that rejects requests the way the given model did live."""

    def __init__(self, reject: dict[str, str]) -> None:
        self.reject = reject
        self.sent: list[dict[str, Any]] = []

    def converse(self, **kw: Any) -> dict[str, Any]:
        self.sent.append(kw)
        fields = kw.get("additionalModelRequestFields") or {}
        for key, message in self.reject.items():
            if (key in fields and fields[key] == {"type": "disabled"}) or (
                key == "temperature" and "temperature" in kw["inferenceConfig"]
            ):
                raise ClientError(
                    {"Error": {"Code": "ValidationException", "Message": message}}, "Converse"
                )
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 1, "outputTokens": 1},
        }


THINK_OFF = GenerateRequest(model="us.anthropic.claude-x", prompt="hi", think=False)


@pytest.mark.parametrize(
    ("reject", "expected"),
    [
        ({}, {"thinking": {"type": "disabled"}}),  # Haiku 5.5, Claude 4.x
        ({"thinking": THINKING_OFF}, {"thinking": {"type": "between_tools"}}),  # Sonnet 5.5
        ({"thinking": OPUS_NO_DISABLE}, {"output_config": {"effort": "low"}}),  # Opus 5.5
        (  # every 5.x quirk at once: temperature and thinking
            {"temperature": TEMPERATURE, "thinking": OPUS_NO_DISABLE},
            {"output_config": {"effort": "low"}},
        ),
    ],
)
async def test_thinking_off_follows_the_models_advice(
    reject: dict[str, str], expected: dict[str, Any]
) -> None:
    client = Recorder(reject)
    b = BedrockBackend("b", runtime_client=client)
    assert (await b.generate(THINK_OFF)).text == "ok"
    first_ok = len(client.sent)
    assert (await b.generate(THINK_OFF)).text == "ok"  # learned: one call, no retries
    assert len(client.sent) == first_ok + 1
    assert client.sent[-1].get("additionalModelRequestFields") == expected


async def test_thinking_is_left_alone_when_asked_for_or_not_claude() -> None:
    client = Recorder({})
    b = BedrockBackend("b", runtime_client=client)
    await b.generate(GenerateRequest(model="us.anthropic.claude-x", prompt="hi", think=True))
    await b.generate(GenerateRequest(model="us.amazon.nova-pro-v1:0", prompt="hi", think=False))
    assert all("additionalModelRequestFields" not in kw for kw in client.sent)


async def test_user_thinking_params_win() -> None:
    client = Recorder({})
    params = {"thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}}
    await BedrockBackend("b", runtime_client=client, params=params).generate(THINK_OFF)
    assert client.sent[-1]["additionalModelRequestFields"] == params


async def test_an_unrelated_validation_error_is_not_retried() -> None:
    client = Recorder({"thinking": "The provided model identifier is invalid."})
    with pytest.raises(MM3Error) as exc:
        await BedrockBackend("b", runtime_client=client).generate(THINK_OFF)
    assert exc.value.code == "E_LLM_CONFIG" and len(client.sent) == 1
