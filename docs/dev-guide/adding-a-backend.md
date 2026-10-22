# Adding an LLM backend

A backend is one module plus one registry line.

## 1. Implement `LLMBackend` (`src/meetingmaster3/llm/base.py`)
```python
class MyBackend:
    kind = "my_kind"
    def __init__(self, id: str, ...): self.id = id; self.is_local = ...
    async def generate(self, req: GenerateRequest) -> GenerateResult: ...
    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]: ...   # async generator
    async def list_models(self) -> list[ModelInfo]: ...
    async def test_connection(self) -> ConnectionStatus: ...   # never raises; report failures
    def context_window(self, model: str) -> int | None: ...    # sync; answer from a cache
    async def warm(self, model: str) -> None: ...              # fill that cache (best effort)
```
`ModelInfo` (what `list_models` returns) also carries optional fields the pickers use; fill what your provider
tells you and leave the rest `None`: `price_in` / `price_out` (USD per 1M tokens), `price_source` (`live` or `table`
with `price_as_of`), `free`, `callable` (False for models that cannot be called on demand), `access`
(`granted`/`denied`) and `text_only`. Return the id that can actually be called (Bedrock collapses a base model and its
`us.`/`global.` inference profile into one entry, `bedrock.collect_models`).

The **one filter** every picker uses is `templates/model_check.py:assess()` (generates text, text-only, callable,
access, not in the `unsuitable` list of `cloud_recommendations.yaml`, workable context window); `usable()` and
`suggest()` use it, and `templates/picker.py:build_picker()` turns a backend's models into the grouped, priced picker
data served by both `/api/llm/backends/{name}/models` and `/settings/llm/{name}/models`. Local backends never show prices.
Prices for a provider that does not report them belong in a dated table like `bedrock_models.yaml` (`llm/pricing.py`).

Rules:
- `is_local` is true only when data stays on this machine. It drives the consent check.
- Raise `MM3Error` with the `E_LLM_*` codes from `base.py`. For httpx-based adapters use
  `_http.send` (bounded jittered retries on 429/5xx, no retry on timeouts) and
  `_http.error_from_response`; they never put bodies above DEBUG.
- Never swallow `asyncio.CancelledError`. If you use threads (as `bedrock.py` does), give the worker a stop flag.
- Import optional SDKs lazily inside the module.
- Probes (`test_connection`) should use a single attempt so an unreachable server fails fast.

### Optional: embeddings (Phase 15i)
Search embeds passages through the backends. To support it, set `supports_embeddings = True` and implement the
`Embedder` protocol (`llm/base.py`):
```python
class MyBackend:
    supports_embeddings = True

    async def embed(
        self, model: str, texts: Sequence[str], *, purpose: EmbedPurpose = "document"
    ) -> list[list[float]]: ...

    async def list_embedding_models(self) -> list[ModelInfo]: ...  # never offered for notes
```
- Return one vector per text, in order; batch inside `embed` as the provider allows (Ollama 32 per call,
  OpenAI-style 64, Titan one text per call with bounded concurrency). Validate the answer with
  `base.check_vectors(provider, vectors, count)`.
- `purpose` is `"query"` for a search query; pass it on where the provider distinguishes (Cohere `input_type`).
  Model-specific text prefixes (nomic's `search_document:`/`search_query:`) are added by `search/embedder.py`, not
  by the backend.
- Errors like `generate`: a backend or model that cannot embed raises `base.embed_unsupported(...)`
  (`E_LLM_EMBED_UNSUPPORTED`); a model that is not installed is `E_LLM_CONFIG` with the fix in the hint.
- Callers check `base.supports_embeddings(backend)`. `Embedder` is a separate protocol so a backend (or test double)
  without embeddings still satisfies `LLMBackend`. `FakeLLMBackend.embed` gives deterministic toy vectors
  (`fake_embedding`), so the search tests can assert rankings offline.
- A cloud embedder is only called with the backend's `cloud_embedding_consent` (`EmbedderChoice.require_consent`).

## 2. Register it (`llm/registry.py`)
```python
def _mine(name: str, cfg: BackendConfig, settings: Settings) -> LLMBackend:
    return MyBackend(name, base_url=cfg.base_url, api_key=_secret(cfg), ...)

register_kind("my_kind", _mine)
```
Users then write `llm.backends.<name>.kind: my_kind`. Add any new setting to `BackendConfig`
(`config/settings.py`) with a default, and to [`configuration.md`](../user-guide/configuration.md).

## 3. Test it
Mock HTTP with `respx`, or a stub client for SDKs (see `tests/unit/llm/`). `test_registry_api.py::test_fourth_backend_plugs_in`
shows the minimum a new backend needs. Cover: generate, stream, list, auth error, rate limit with
retry, context-length mapping, and that a key never appears in output.

## 4. Document it
`docs/user-guide/llm-backends.md`, `THIRD_PARTY_NOTICES.md` for any new dependency, and a CHANGELOG line.

## Helpers for callers (Phase 09)
- `llm.budget`: `estimate_tokens`, `fits(backend, model, prompt)`, `chunk_transcript(turns, max_tokens)`.
- `llm.consent.enforce_consent(backend, cloud_consent=..., remembered=...)`.
- `OllamaBackend.unload_all()` frees VRAM before transcription (R5).
