"""AWS Bedrock backend using the Converse and ConverseStream APIs (optional ``bedrock`` extra)."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any

from meetingmaster3.errors import MM3Error
from meetingmaster3.llm._http import looks_like_context_error
from meetingmaster3.llm.base import (
    E_LLM_AUTH,
    E_LLM_BAD_RESPONSE,
    E_LLM_CONFIG,
    E_LLM_CONTEXT,
    E_LLM_RATE_LIMIT,
    E_LLM_TIMEOUT,
    E_LLM_UNREACHABLE,
    ConnectionStatus,
    GenerateRequest,
    GenerateResult,
    ModelInfo,
    Usage,
    connection_failure,
    llm_error,
)
from meetingmaster3.logging import redact

log = logging.getLogger(__name__)

PROVIDER = "AWS Bedrock"
DEFAULT_REGION = "us-east-1"
AUTH_CODES = {
    "AccessDeniedException",
    "UnrecognizedClientException",
    "ExpiredTokenException",
    "InvalidSignatureException",
    "UnauthorizedException",
}
_DONE = object()


def _import_boto() -> Any:
    try:
        import boto3
    except ImportError as exc:
        raise llm_error(
            E_LLM_CONFIG,
            "AWS Bedrock needs the optional 'bedrock' extra (boto3).",
            "Install it with `uv sync --extra bedrock`.",
            status_code=501,
        ) from exc
    return boto3


def map_boto_error(exc: Exception) -> MM3Error:
    """Normalise botocore failures to ``MM3Error`` codes."""
    if isinstance(exc, MM3Error):
        return exc
    from botocore.exceptions import (
        ClientError,
        NoCredentialsError,
        PartialCredentialsError,
        ProfileNotFound,
        ReadTimeoutError,
    )
    from botocore.exceptions import (
        ConnectionError as BotoConnectionError,
    )

    if isinstance(exc, (NoCredentialsError, PartialCredentialsError, ProfileNotFound)):
        return llm_error(
            E_LLM_AUTH,
            "No usable AWS credentials were found.",
            "Set an AWS profile or the standard AWS_* environment variables.",
            status_code=401,
        )
    if isinstance(exc, ReadTimeoutError):
        return llm_error(E_LLM_TIMEOUT, "Bedrock did not answer in time.", status_code=504)
    if isinstance(exc, BotoConnectionError):
        return llm_error(
            E_LLM_UNREACHABLE,
            "Cannot reach AWS Bedrock.",
            "Check the network connection and the configured region.",
            status_code=503,
        )
    if isinstance(exc, ClientError):
        err = exc.response.get("Error", {})
        code, message = err.get("Code", ""), err.get("Message", "")
        log.debug("Bedrock %s: %s", code, redact(message[:300]))
        if code in AUTH_CODES:
            return llm_error(
                E_LLM_AUTH,
                f"Bedrock refused the request ({code}).",
                "Check the credentials, the region and that model access is enabled in Bedrock.",
                status_code=401,
            )
        if code in {
            "ThrottlingException",
            "TooManyRequestsException",
            "ServiceQuotaExceededException",
        }:
            return llm_error(E_LLM_RATE_LIMIT, "Bedrock is throttling requests.", status_code=429)
        if code in {"ModelTimeoutException", "RequestTimeout"}:
            return llm_error(E_LLM_TIMEOUT, "Bedrock timed out.", status_code=504)
        if code == "ValidationException" and looks_like_context_error(message):
            return llm_error(
                E_LLM_CONTEXT,
                "The prompt does not fit the model's context window (Bedrock).",
                "Use a model with a larger context or let the app split the transcript.",
                status_code=413,
            )
        if code in {"ServiceUnavailableException", "InternalServerException"}:
            return llm_error(
                E_LLM_UNREACHABLE, "Bedrock is temporarily unavailable.", status_code=503
            )
        return llm_error(E_LLM_BAD_RESPONSE, f"Bedrock returned an error ({code or 'unknown'}).")
    return llm_error(E_LLM_BAD_RESPONSE, f"Unexpected Bedrock failure: {type(exc).__name__}.")


class BedrockBackend:
    kind = "bedrock"
    is_local = False

    def __init__(
        self,
        id: str,
        region: str | None = None,
        profile: str | None = None,
        default_model: str | None = None,
        params: Mapping[str, Any] | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        context_window: int | None = None,
        runtime_client: Any = None,
        control_client: Any = None,
    ) -> None:
        self.id = id
        self.region = region or DEFAULT_REGION
        self.profile = profile
        self.default_model = default_model
        self.params = dict(params or {})
        self._keys = (access_key_id, secret_access_key)
        self._override_ctx = context_window
        self._runtime = runtime_client
        self._control = control_client

    # -- clients (lazy: boto3 is optional) ------------------------------------------------

    def _session(self) -> Any:
        boto3 = _import_boto()
        key, secret = self._keys
        if key and secret:
            return boto3.Session(
                aws_access_key_id=key, aws_secret_access_key=secret, region_name=self.region
            )
        return boto3.Session(profile_name=self.profile, region_name=self.region)

    def _client(self, service: str) -> Any:
        from botocore.config import Config

        cfg = Config(retries={"max_attempts": 4, "mode": "adaptive"}, read_timeout=600)
        return self._session().client(service, config=cfg)

    @property
    def runtime(self) -> Any:
        if self._runtime is None:
            self._runtime = self._client("bedrock-runtime")
        return self._runtime

    @property
    def control(self) -> Any:
        if self._control is None:
            self._control = self._client("bedrock")
        return self._control

    # -- request building -----------------------------------------------------------------

    def _kwargs(self, req: GenerateRequest) -> dict[str, Any]:
        inference: dict[str, Any] = {"temperature": req.temperature}
        if req.max_tokens:
            inference["maxTokens"] = req.max_tokens
        if req.stop:
            inference["stopSequences"] = list(req.stop)
        kwargs: dict[str, Any] = {
            "modelId": req.model,
            "messages": [{"role": m.role, "content": [{"text": m.content}]} for m in req.chat()],
            "inferenceConfig": inference,
        }
        if system := req.system_text():
            kwargs["system"] = [{"text": system}]
        if self.params:
            kwargs["additionalModelRequestFields"] = self.params
        return kwargs

    # -- LLMBackend -----------------------------------------------------------------------

    async def generate(self, req: GenerateRequest) -> GenerateResult:
        started = time.monotonic()
        kwargs = self._kwargs(req)
        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(self.runtime.converse, **kwargs), timeout=req.timeout
            )
        except TimeoutError as exc:
            raise llm_error(
                E_LLM_TIMEOUT, "Bedrock did not answer in time.", status_code=504
            ) from exc
        except Exception as exc:
            raise map_boto_error(exc) from exc
        try:
            parts = data["output"]["message"]["content"]
            text = "".join(p["text"] for p in parts if "text" in p)
        except (KeyError, TypeError) as exc:
            raise llm_error(E_LLM_BAD_RESPONSE, "Unexpected response from Bedrock.") from exc
        usage = data.get("usage") or {}
        return GenerateResult(
            text=text,
            model=req.model,
            usage=Usage(usage.get("inputTokens"), usage.get("outputTokens")),
            finish_reason=data.get("stopReason"),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[object] = asyncio.Queue()
        stop = threading.Event()
        kwargs = self._kwargs(req)

        def put(item: object) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, item)

        def pump() -> None:
            try:
                response = self.runtime.converse_stream(**kwargs)
                for event in response["stream"]:
                    if stop.is_set():
                        break
                    delta = event.get("contentBlockDelta", {}).get("delta", {})
                    if "text" in delta:
                        put(delta["text"])
            except Exception as exc:
                put(exc)
            finally:
                put(_DONE)

        task = loop.run_in_executor(None, pump)
        try:
            while True:
                item = await asyncio.wait_for(queue.get(), timeout=req.timeout)
                if item is _DONE:
                    return
                if isinstance(item, Exception):
                    raise map_boto_error(item) from item
                yield str(item)
        except TimeoutError as exc:
            raise llm_error(
                E_LLM_TIMEOUT, "Bedrock did not answer in time.", status_code=504
            ) from exc
        finally:
            stop.set()  # a cancelled or abandoned stream lets the worker thread wind down
            task.cancel()

    async def list_models(self) -> list[ModelInfo]:
        try:
            data = await asyncio.to_thread(
                self.control.list_foundation_models, byOutputModality="TEXT"
            )
        except Exception as exc:
            raise map_boto_error(exc) from exc
        models = [
            ModelInfo(id=m["modelId"], name=m.get("modelName"))
            for m in data.get("modelSummaries", [])
            if "TEXT" in m.get("outputModalities", [])
            and m.get("modelLifecycle", {}).get("status", "ACTIVE") == "ACTIVE"
        ]
        try:  # newer models are only callable through inference profiles (e.g. "us.<model>")
            profiles = await asyncio.to_thread(self.control.list_inference_profiles)
            models += [
                ModelInfo(id=p["inferenceProfileId"], name=p.get("inferenceProfileName"))
                for p in profiles.get("inferenceProfileSummaries", [])
            ]
        except Exception as exc:
            log.debug("Bedrock inference profiles unavailable: %s", type(exc).__name__)
        return sorted(models, key=lambda m: m.id)

    async def test_connection(self) -> ConnectionStatus:
        started = time.monotonic()
        try:
            models = await self.list_models()
        except MM3Error as exc:
            return connection_failure(exc)
        present = None
        message = f"Connected to Bedrock in {self.region}; {len(models)} text model(s) listed."
        hint = "Cloud backend: transcript text is sent to AWS when this backend is used."
        if self.default_model:
            present = self.default_model in {m.id for m in models}
            if not present:
                message += f" Model {self.default_model!r} was not listed."
                hint = "Enable model access in the Bedrock console, or check the id and region."
        return ConnectionStatus(
            ok=True,
            message=message,
            latency_ms=int((time.monotonic() - started) * 1000),
            hint=hint,
            models=len(models),
            default_model_present=present,
            details={"location": "cloud", "region": self.region},
        )

    def context_window(self, model: str) -> int | None:
        return self._override_ctx

    async def warm(self, model: str) -> None:
        return None
