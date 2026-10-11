# Phase 08: LLM Backend Abstraction

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 02 (can run in parallel with 03–07) · **Branch:** `phase-08-llm-backends`

## Read first
`CLAUDE.md`, `prompts/_shared-instructions.md`, and `docs/SPECIFICATION.md` §8, §12 (extensibility), §15.1 (A4), §15.2 (R5, R6) and §15.3 (S5, S6). ADR-0004.

## Goal
A thin, uniform interface over Ollama, AWS Bedrock and OpenAI-compatible endpoints (with an OpenRouter preset). Adding a backend means one new module plus a registry entry. Every backend declares whether data leaves the machine.

## Tasks
1. **Interface (`llm/base.py`):**
   ```python
   class LLMBackend(Protocol):
       id: str
       kind: str
       is_local: bool

       async def generate(self, req: GenerateRequest) -> GenerateResult: ...
       async def stream(self, req: GenerateRequest) -> AsyncIterator[str]: ...
       async def list_models(self) -> list[ModelInfo]: ...
       async def test_connection(self) -> ConnectionStatus: ...
       def context_window(self, model: str) -> int | None: ...
   ```
   `GenerateRequest(system, messages|prompt, model, temperature, max_tokens, stop, json_mode?, timeout)`. `GenerateResult(text, model, usage{in,out}?, finish_reason, latency_ms)`. Errors are normalised to `MM3Error` codes: `E_LLM_AUTH`, `E_LLM_UNREACHABLE`, `E_LLM_RATE_LIMIT`, `E_LLM_CONTEXT`, `E_LLM_TIMEOUT`.
2. **Ollama (`llm/ollama.py`):** httpx against `/api/chat` (streaming and non-streaming), `/api/tags`, `/api/show` (read `num_ctx` / the model's context length) and `/api/ps`, plus an `unload_all()` helper (`keep_alive: 0`) that Phase 06 uses. Set `options.num_ctx` from the budget. `is_local = True` when the host is loopback or `host.docker.internal`; otherwise `False`, and the UI shows a "remote Ollama" badge.
3. **OpenAI-compatible (`llm/openai_compat.py`):** use plain httpx `/v1/chat/completions` (with SSE streaming) and `/v1/models`, unless the official SDK is justified in an ADR. Presets: `openrouter` (base URL `https://openrouter.ai/api/v1`, optional `HTTP-Referer`/`X-Title` headers), `openai`, and `custom` (any base URL; covers LM Studio, vLLM and llama.cpp). `is_local` is derived from the host.
4. **Bedrock (`llm/bedrock.py`):** boto3 `bedrock-runtime` **Converse** and **ConverseStream** APIs (sync calls run in a thread). Credentials come from the standard AWS chain (profile or env); the region is configurable; `list_models` uses `bedrock` `list_foundation_models` filtered to text and converse-capable models. Lives in the optional `bedrock` extra, with a lazy import.
5. **Registry and config (`llm/registry.py`):** config shape `llm.backends: {<name>: {kind, base_url?, api_key?, region?, profile?, default_model, params{}}}` and `llm.default_backend` (note: Phase 05's `mm3 doctor` reads `llm.backends.ollama.base_url` to probe Ollama, so keep that key or update `hardware/doctor.py`) (default: an `ollama` instance at `http://127.0.0.1:11434`). Factory build plus a cache. API keys are `SecretStr`.
6. **Context budgeting (`llm/budget.py`, R6):** a token estimator (≈ 4 chars/token, or the backend's tokenizer where cheap), `fits(model, prompt) -> bool` at 70% of the context window, and the `chunk_transcript(transcript, max_tokens)` helper that splits on speaker-turn boundaries with a small overlap. Phase 09 uses it.
7. **Egress policy (S6):** `requires_consent(backend)` returns True for non-local backends. The job options carry `cloud_consent: bool`, and the generation stage (Phase 09) refuses to call a non-local backend without it (`E_CONSENT_REQUIRED`). Settings can remember consent per backend.
8. **API:** `GET /api/llm/backends` (masked config, `is_local`), `POST /api/llm/backends/{name}/test`, `GET /api/llm/backends/{name}/models`, and `GET /api/llm/recommendations` (merging Phase 05's local recommendations with the cloud suggestions in a YAML data file: capability, cost tier and privacy note; **no hard-coded prices**; link to the provider pricing pages instead).
9. **Robustness:** timeouts, bounded retries with jitter for 429/5xx, cancellation propagation, and request and response bodies never logged above DEBUG (and redacted even then).
10. **`mm3 doctor`:** add a reachability and model-presence check for each configured backend.

## Tests
Respx/httpx mock transports for Ollama and OpenAI-compatible (generate, stream, list, auth error, 429 retry, context error mapping); botocore Stubber for Bedrock; budget and chunking properties (no turn split mid-way, coverage of all segments); consent enforcement; secret masking in API output. A `network`-marked live test against the local Ollama on the reference machine (with a small model, e.g. `llama3.2:3b` or whatever is installed; check `ollama list`).

## Acceptance criteria
- Against the local Ollama, `generate` and `stream` work. Connection tests report clearly for all three kinds; Bedrock and OpenRouter are tested with stubs, and live only if Nick provides keys.
- Adding a fake fourth backend in a test requires only a class and a registry entry.

## Phase-specific docs
`docs/user-guide/llm-backends.md` (setup for each backend, privacy implications, Ollama install pointer); `docs/dev-guide/adding-a-backend.md`; configuration doc; SECURITY and PRIVACY (egress consent, key storage); THIRD_PARTY_NOTICES (httpx, boto3, …). Then the standard close-out checklist.
