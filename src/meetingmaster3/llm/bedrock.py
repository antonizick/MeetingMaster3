"""AWS Bedrock backend using the Converse and ConverseStream APIs (optional ``bedrock`` extra).

Embeddings (Phase 15i) use ``InvokeModel`` with Amazon Titan Text Embeddings V2 or Cohere Embed."""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import threading
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

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
    EmbedPurpose,
    GenerateRequest,
    GenerateResult,
    ModelInfo,
    Usage,
    check_answer,
    check_vectors,
    connection_failure,
    embed_unsupported,
    llm_error,
)
from meetingmaster3.llm.budget import DEFAULT_CONTEXT_WINDOW
from meetingmaster3.llm.pricing import with_table_price
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
TITAN_DIMENSIONS = 1024
EMBED_CONCURRENCY = 4
"""Titan takes one text per call; this many calls run at once."""
COHERE_BATCH = 96
"""Cohere Embed takes up to 96 texts per call."""
MODELS_FILE = Path(__file__).with_name("bedrock_models.yaml")
GEO_PREFIXES = frozenset({"us", "eu", "apac", "global", "jp", "au", "ca", "us-gov", "apne"})
"""First segments of cross-Region inference profile ids (``us.anthropic.claude-...``)."""
FINISH_REASONS = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "model_context_window_exceeded": "length",
}
"""Bedrock ``stopReason`` values in the OpenAI-style words the generator checks."""


@functools.cache
def _context_table(path: Path = MODELS_FILE) -> dict[str, int]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): int(v) for k, v in (data.get("context_windows") or {}).items()}


def base_model_id(model: str) -> str:
    """``us.anthropic.claude-x`` -> ``anthropic.claude-x``; other ids unchanged."""
    head, sep, rest = model.partition(".")
    return rest if sep and head.lower() in GEO_PREFIXES else model


def known_context_window(model: str, table: Mapping[str, int] | None = None) -> int | None:
    """The context window of ``model``'s family from ``bedrock_models.yaml`` (longest prefix
    wins), or None for a model the table does not know (ADR-0044)."""
    table = _context_table() if table is None else table
    model_id = base_model_id(model).lower()
    matches = [prefix for prefix in table if model_id.startswith(prefix.lower())]
    return table[max(matches, key=len)] if matches else None


def region_geo(region: str) -> str:
    """The inference-profile prefix of a Region (``us-east-1`` -> ``us``, ``ap-*`` -> ``apac``)."""
    head = region.split("-", 1)[0].lower()
    return {"ap": "apac"}.get(head, head)


def collect_models(
    summaries: list[dict[str, Any]], profiles: list[dict[str, Any]], region: str
) -> list[ModelInfo]:
    """One entry per usable text model, with the id that can be called (ADR-0042).

    A model that supports on-demand calls is listed by its own id. One that is only callable
    through an inference profile is listed by that profile's id (the profile of the account's own
    geography first, then ``global.``), so the base id and its ``us.`` twin are not both shown.
    Provisioned-only and non-ACTIVE models are left out. A profile whose base model the list
    does not mention (a newer model) is kept as it is. Account access is not reported by the
    listing; a model the account may not call fails with ``E_LLM_CONFIG`` when it is used."""
    geo = region_geo(region)
    by_base: dict[str, list[str]] = {}
    for p in profiles:
        by_base.setdefault(base_model_id(p["inferenceProfileId"]), []).append(
            p["inferenceProfileId"]
        )

    def best_profile(base: str) -> str | None:
        ids = by_base.get(base, [])
        for prefix in (f"{geo}.", "global."):
            for pid in sorted(ids):
                if pid.startswith(prefix):
                    return pid
        return sorted(ids)[0] if ids else None

    found: list[ModelInfo] = []
    known: set[str] = set()
    for m in summaries:
        base = m["modelId"]
        known.add(base)
        if "TEXT" not in m.get("outputModalities", []):
            continue
        if m.get("modelLifecycle", {}).get("status", "ACTIVE") != "ACTIVE":
            continue
        types = set(m.get("inferenceTypesSupported", []))
        target: str | None = base
        callable_: bool | None = True
        if types and "ON_DEMAND" not in types:
            target = best_profile(base) if "INFERENCE_PROFILE" in types else None
            callable_ = target is not None
        elif not types:
            callable_ = None  # an older API answer without the field: try it as listed
        found.append(
            with_table_price(
                ModelInfo(
                    id=target or base,
                    name=m.get("modelName"),
                    context_window=known_context_window(target or base),
                    callable=callable_,
                )
            )
        )
    listed = {m.id for m in found}
    for p in profiles:  # profiles of models the foundation list does not describe
        pid = p["inferenceProfileId"]
        if base_model_id(pid) in known or pid in listed:
            continue
        found.append(
            with_table_price(
                ModelInfo(
                    id=pid,
                    name=p.get("inferenceProfileName"),
                    context_window=known_context_window(pid),
                    callable=True,
                )
            )
        )
    return sorted(found, key=lambda m: m.id)


def finish_reason(stop: str | None) -> str | None:
    return FINISH_REASONS.get(stop, stop) if stop else None


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
        if code == "ValidationException":
            return _validation_error(message)
        if code in {"ServiceUnavailableException", "InternalServerException"}:
            return llm_error(
                E_LLM_UNREACHABLE, "Bedrock is temporarily unavailable.", status_code=503
            )
        return llm_error(E_LLM_BAD_RESPONSE, f"Bedrock returned an error ({code or 'unknown'}).")
    return llm_error(E_LLM_BAD_RESPONSE, f"Unexpected Bedrock failure: {type(exc).__name__}.")


def _validation_error(message: str) -> MM3Error:
    """Bedrock's ``ValidationException`` texts (recorded live 2026-10-15) as setup errors."""
    low = message.lower()
    if "inference profile" in low and "on-demand" in low:
        return llm_error(
            E_LLM_CONFIG,
            "This Bedrock model can only be called through an inference profile.",
            "Use its inference profile ID instead, for example us.<model id> or global.<model id> "
            "(Load models lists them).",
            status_code=400,
        )
    if "doesn't support on-demand" in low or "does not support on-demand" in low:
        return llm_error(
            E_LLM_CONFIG,
            "This Bedrock model needs Provisioned Throughput, which the app does not use.",
            "Choose another model or its inference profile ID.",
            status_code=400,
        )
    if "model identifier is invalid" in low:
        return llm_error(
            E_LLM_CONFIG,
            "Bedrock does not know this model ID in the configured region.",
            "Check the ID and the region; Load models lists what this account can see.",
            status_code=400,
        )
    detail = redact(message.removeprefix("The model returned the following errors: "))[:200]
    return llm_error(
        E_LLM_CONFIG,
        f"Bedrock refused the request: {detail}",
        "Check the backend's model and parameters (params).",
        status_code=400,
    )


def _validation_message(exc: Exception) -> str | None:
    """The text of a Bedrock ``ValidationException``, or None for any other failure."""
    from botocore.exceptions import ClientError

    if not isinstance(exc, ClientError):
        return None
    err = exc.response.get("Error", {})
    return str(err.get("Message", "")) if err.get("Code") == "ValidationException" else None


THINKING_OFF: dict[str, Any] = {"thinking": {"type": "disabled"}}
"""What asks a Claude model not to think (``generation.think`` off). Newer models want something
else and say so in a ValidationException; :meth:`BedrockBackend._adapt` follows that advice."""
THINKING_KEYS = frozenset({"thinking", "output_config"})
THINKING_ROOM = 4096
"""Output tokens added to ``maxTokens`` when a Claude model may think: reasoning counts against
``maxTokens``, and Opus 5.5 thinks even at low effort (an empty section otherwise, measured
live 2026-10-15). Only the tokens used are billed."""
NO_THINKING = ({"thinking": {"type": "disabled"}}, {"thinking": {"type": "between_tools"}})


class _Stop:
    def __init__(self, reason: str | None) -> None:
        self.reason = reason


class BedrockBackend:
    kind = "bedrock"
    is_local = False
    supports_embeddings = True

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
        self._no_temperature: set[str] = set()
        """Models that rejected ``temperature`` once; it is left out for them from then on."""
        self._thinking_off: dict[str, dict[str, Any]] = {}
        """Per model, the request fields that turn its thinking off, learned from its errors."""

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
        inference: dict[str, Any] = {}
        if req.model not in self._no_temperature:
            inference["temperature"] = req.temperature
        if req.max_tokens:
            room = THINKING_ROOM if self._may_think(req) else 0
            inference["maxTokens"] = req.max_tokens + room
        if req.stop:
            inference["stopSequences"] = list(req.stop)
        kwargs: dict[str, Any] = {
            "modelId": req.model,
            "messages": [{"role": m.role, "content": [{"text": m.content}]} for m in req.chat()],
            "inferenceConfig": inference,
        }
        if system := req.system_text():
            kwargs["system"] = [{"text": system}]
        extra = dict(self.params)
        if req.think is False and self._controls_thinking(req.model):
            extra.update(self._thinking_off.get(req.model, THINKING_OFF))
        if extra:
            kwargs["additionalModelRequestFields"] = extra
        return kwargs

    def _may_think(self, req: GenerateRequest) -> bool:
        """True when a Claude model may spend output tokens on reasoning in this call."""
        if not base_model_id(req.model).startswith("anthropic.claude") or req.think is None:
            return False
        if req.think or not self._controls_thinking(req.model):
            return True
        return self._thinking_off.get(req.model, THINKING_OFF) not in NO_THINKING

    def _controls_thinking(self, model: str) -> bool:
        """Claude models think by default (Claude 5.x); others reject unknown fields. Thinking
        fields the user set in ``params`` are left alone."""
        claude = base_model_id(model).startswith("anthropic.claude")
        return claude and not (THINKING_KEYS & set(self.params))

    def _call(self, method: str, kwargs: dict[str, Any]) -> Any:
        """One Converse(Stream) call. When the model rejects a field the app added (temperature,
        the thinking switch) the call is repeated as its error message advises, and the model
        remembers it (ADR-0045). Rejected calls are not billed. Runs in a worker thread."""
        call = getattr(self.runtime, method)
        for _ in range(3):
            try:
                return call(**kwargs)
            except Exception as exc:
                adapted = self._adapt(kwargs, exc)
                if adapted is None:
                    raise
                kwargs = adapted
        return call(**kwargs)

    def _adapt(self, kwargs: dict[str, Any], exc: Exception) -> dict[str, Any] | None:
        message = _validation_message(exc)
        if message is None:
            return None
        model = kwargs["modelId"]
        config = kwargs["inferenceConfig"]
        if "temperature" in message and "temperature" in config:
            log.info("Bedrock model %s rejects temperature; sending it without", model)
            self._no_temperature.add(model)
            config = {k: v for k, v in config.items() if k != "temperature"}
            return {**kwargs, "inferenceConfig": config}
        extra = dict(kwargs.get("additionalModelRequestFields") or {})
        current = {k: extra[k] for k in THINKING_KEYS & set(extra) if k not in self.params}
        if not current or "thinking" not in message:
            return None
        if "between_tools" in message and current != {"thinking": {"type": "between_tools"}}:
            new: dict[str, Any] = {"thinking": {"type": "between_tools"}}
        elif "effort" in message and "output_config" not in current:
            new = {"output_config": {"effort": "low"}}
        else:
            new = {}
        log.info("Bedrock model %s: thinking switched off with %s", model, new or "nothing")
        self._thinking_off[model] = new
        for key in current:
            extra.pop(key)
        extra.update(new)
        adapted = {k: v for k, v in kwargs.items() if k != "additionalModelRequestFields"}
        if new not in NO_THINKING and "maxTokens" in config and current in NO_THINKING:
            adapted["inferenceConfig"] = {
                **config,
                "maxTokens": config["maxTokens"] + THINKING_ROOM,
            }
        return {**adapted, "additionalModelRequestFields": extra} if extra else adapted

    # -- LLMBackend -----------------------------------------------------------------------

    async def generate(self, req: GenerateRequest) -> GenerateResult:
        started = time.monotonic()
        kwargs = self._kwargs(req)
        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(self._call, "converse", kwargs), timeout=req.timeout
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
        finish = finish_reason(data.get("stopReason"))
        check_answer(PROVIDER, text, finish)
        return GenerateResult(
            text=text,
            model=req.model,
            usage=Usage(usage.get("inputTokens"), usage.get("outputTokens")),
            finish_reason=finish,
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
                response = self._call("converse_stream", kwargs)
                for event in response["stream"]:
                    if stop.is_set():
                        break
                    delta = event.get("contentBlockDelta", {}).get("delta", {})
                    if "text" in delta:
                        put(delta["text"])
                    if "messageStop" in event:
                        put(_Stop(event["messageStop"].get("stopReason")))
            except Exception as exc:
                put(exc)
            finally:
                put(_DONE)

        task = loop.run_in_executor(None, pump)
        streamed: list[str] = []
        try:
            while True:
                item = await asyncio.wait_for(queue.get(), timeout=req.timeout)
                if item is _DONE:
                    return
                if isinstance(item, Exception):
                    raise map_boto_error(item) from item
                if isinstance(item, _Stop):
                    check_answer(PROVIDER, "".join(streamed), finish_reason(item.reason))
                    continue
                streamed.append(str(item))
                yield str(item)
        except TimeoutError as exc:
            raise llm_error(
                E_LLM_TIMEOUT, "Bedrock did not answer in time.", status_code=504
            ) from exc
        finally:
            stop.set()  # a cancelled or abandoned stream lets the worker thread wind down
            task.cancel()

    # -- embeddings (Phase 15i) ------------------------------------------------------------

    async def embed(
        self, model: str, texts: Sequence[str], *, purpose: EmbedPurpose = "document"
    ) -> list[list[float]]:
        family = base_model_id(model)
        if family.startswith("amazon.titan-embed"):
            gate = asyncio.Semaphore(EMBED_CONCURRENCY)

            async def one(text: str) -> object:
                async with gate:
                    body = {"inputText": text, "dimensions": TITAN_DIMENSIONS, "normalize": True}
                    data = await self._invoke(model, body)
                    return data.get("embedding")

            vectors = list(await asyncio.gather(*(one(t) for t in texts)))
            return check_vectors(PROVIDER, vectors, len(texts))
        if family.startswith("cohere.embed"):
            out: list[list[float]] = []
            input_type = "search_query" if purpose == "query" else "search_document"
            for start in range(0, len(texts), COHERE_BATCH):
                batch = list(texts[start : start + COHERE_BATCH])
                data = await self._invoke(
                    model, {"texts": batch, "input_type": input_type, "truncate": "END"}
                )
                found = data.get("embeddings")
                if isinstance(found, dict):  # embedding_types requested: {"float": [...]}
                    found = found.get("float")
                out += check_vectors(PROVIDER, found, len(batch))
            return out
        raise embed_unsupported(f"Bedrock model {model!r}")

    async def _invoke(self, model: str, body: dict[str, Any]) -> dict[str, Any]:
        def call() -> dict[str, Any]:
            resp = self.runtime.invoke_model(
                modelId=model,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            raw = resp["body"].read()
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("not an object")
            return data

        try:
            return await asyncio.to_thread(call)
        except (ValueError, KeyError, TypeError) as exc:
            raise llm_error(
                E_LLM_BAD_RESPONSE, "Unexpected embedding answer from Bedrock."
            ) from exc
        except Exception as exc:
            raise map_boto_error(exc) from exc

    async def list_embedding_models(self) -> list[ModelInfo]:
        """Titan and Cohere text embedding models (the ones :meth:`embed` can call)."""
        try:
            data = await asyncio.to_thread(
                self.control.list_foundation_models, byOutputModality="EMBEDDING"
            )
        except Exception as exc:
            raise map_boto_error(exc) from exc
        found = []
        for m in data.get("modelSummaries", []):
            mid = str(m.get("modelId", ""))
            if not mid.startswith(("amazon.titan-embed-text", "cohere.embed")):
                continue
            if m.get("modelLifecycle", {}).get("status", "ACTIVE") != "ACTIVE":
                continue
            types = set(m.get("inferenceTypesSupported", []))
            if types and "ON_DEMAND" not in types:
                continue
            found.append(ModelInfo(id=mid, name=m.get("modelName"), can_generate=False))
        return sorted(found, key=lambda m: m.id)

    async def list_models(self) -> list[ModelInfo]:
        try:
            data = await asyncio.to_thread(
                self.control.list_foundation_models, byOutputModality="TEXT"
            )
        except Exception as exc:
            raise map_boto_error(exc) from exc
        profiles: list[dict[str, Any]] = []
        try:  # newer models are only callable through inference profiles (e.g. "us.<model>")
            profiles = await asyncio.to_thread(self._inference_profiles)
        except Exception as exc:
            log.debug("Bedrock inference profiles unavailable: %s", type(exc).__name__)
        return collect_models(data.get("modelSummaries", []), profiles, self.region)

    def _inference_profiles(self) -> list[dict[str, Any]]:
        """Every system inference profile; the API pages its answer (``nextToken``)."""
        found: list[dict[str, Any]] = []
        kwargs: dict[str, Any] = {}
        for _ in range(50):  # bounded: a misbehaving endpoint cannot loop forever
            page = self.control.list_inference_profiles(**kwargs)
            found += page.get("inferenceProfileSummaries", [])
            if not page.get("nextToken"):
                break
            kwargs = {"nextToken": page["nextToken"]}
        return found

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
            elif self.context_window(self.default_model) is None:
                hint = (
                    f"The context window of {self.default_model!r} is not known, so long "
                    f"meetings are planned for {DEFAULT_CONTEXT_WINDOW} tokens. Set the "
                    "backend's context window (see the model card) for better notes."
                )
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
        return self._override_ctx or known_context_window(model)

    async def warm(self, model: str) -> None:
        return None
