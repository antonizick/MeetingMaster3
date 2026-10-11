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
Rules:
- `is_local` is true only when data stays on this machine. It drives the consent check.
- Raise `MM3Error` with the `E_LLM_*` codes from `base.py`. For httpx-based adapters use
  `_http.send` (bounded jittered retries on 429/5xx, no retry on timeouts) and
  `_http.error_from_response`; they never put bodies above DEBUG.
- Never swallow `asyncio.CancelledError`. If you use threads (as `bedrock.py` does), give the worker a stop flag.
- Import optional SDKs lazily inside the module.
- Probes (`test_connection`) should use a single attempt so an unreachable server fails fast.

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
