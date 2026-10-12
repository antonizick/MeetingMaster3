# LLM backends

MeetingMaster3 writes notes with a language model. You choose where that model runs. Everything
is configured under `llm:` in `config.yaml` (see [`configuration.md`](configuration.md)).

| Backend | `kind` | Where your transcript goes |
|---|---|---|
| Ollama on this computer (default) | `ollama` | Stays on this machine |
| Ollama on another machine | `ollama` | Treated as **cloud**: it leaves this machine |
| LM Studio, vLLM, llama.cpp on this computer | `openai_compat` | Stays on this machine |
| OpenRouter | `openrouter` | Sent to OpenRouter and the model provider |
| OpenAI | `openai` | Sent to OpenAI |
| AWS Bedrock | `bedrock` | Sent to AWS (your account and region) |

A backend is "local" only when its address is loopback (`127.0.0.1`, `localhost`) or
`host.docker.internal`. Anything else needs your consent before the app sends a transcript
(see [Privacy](#privacy-and-consent)).

## Ollama (recommended, local)
1. Install Ollama from <https://ollama.com/download> and start it (`ollama serve`, or the system service).
2. Pull a model that fits your GPU, e.g. `ollama pull qwen3:8b`. `uv run mm3 doctor` (from Phase 05) suggests sizes for your hardware.
3. Nothing to configure: with no `llm.backends` entry the app uses `http://127.0.0.1:11434`. To pin a model:
```yaml
llm:
  backends:
    ollama:
      kind: ollama
      default_model: qwen3:8b
```
The app sizes Ollama's context window from the prompt, and asks Ollama to unload its models before
transcription so an 8 GB GPU is not out of memory. It also reads each model's capabilities and context length
from Ollama (`/api/show`). Embedding-only models, and models with too little context to summarise a meeting
(below about 4,096 tokens, after the *Largest context for local models* cap), are not offered. A job that names
one is refused when it is submitted, with `E_LLM_MODEL_UNSUITABLE` or `E_LLM_CONTEXT`. Setting
`default_model`, or ticking *Use this model for new meetings too* after a failure, saves you choosing each time.

In Docker, point `base_url` at `http://host.docker.internal:11434`; Ollama must listen on an address the container can reach.

## OpenRouter
```yaml
llm:
  default_backend: openrouter
  backends:
    openrouter:
      kind: openrouter
      default_model: <a model id from "List models">
      # headers: {HTTP-Referer: "https://your.site", X-Title: "My notes"}   # optional
```
Put the key in the environment rather than the file: `export MM3_SECRETS__OPENROUTER_API_KEY=...`.

## OpenAI or any OpenAI-compatible server
```yaml
llm:
  backends:
    lmstudio:
      kind: openai_compat
      base_url: http://127.0.0.1:1234/v1     # include /v1
      default_model: <model id>
      context_window: 32768                  # if the server does not report it
```
`kind: openai` is the same with the OpenAI base URL preset and `MM3_SECRETS__OPENAI_API_KEY`.

## AWS Bedrock
Install the optional extra: `uv sync --extra bedrock`. Credentials come from the standard AWS chain
(an AWS profile or `AWS_*` variables), or `MM3_SECRETS__AWS_ACCESS_KEY_ID` and `..._SECRET_ACCESS_KEY`.
```yaml
llm:
  backends:
    bedrock:
      kind: bedrock
      region: us-east-1
      profile: my-profile          # optional
      default_model: <model or inference-profile id>
      context_window: 200000       # Bedrock cannot report this; set it for your model
```
Enable access to the model in the Bedrock console first. Newer models are called through an
inference profile id (for example `us.<model-id>`); "List models" shows both.

## Checking it works
```bash
uv run mm3 llm list          # configured backends, local or cloud
uv run mm3 llm test          # connects to each one and checks the default model exists
```
The same tests are available at `POST /api/llm/backends/{name}/test` and the Settings page (Phase 12).
Errors carry a code: `E_LLM_AUTH` (bad key), `E_LLM_UNREACHABLE`, `E_LLM_RATE_LIMIT`, `E_LLM_CONTEXT`
(prompt too long), `E_LLM_TIMEOUT`.

## Privacy and consent
- The first use of a non-local backend in each job needs your confirmation. You can remember it per
  backend with `consent_remembered: true`. Local backends never ask.
- Only the transcript text and prompt are sent, never the audio.
- API keys live in `config.yaml` (mode `0600`) or the environment, are masked in the UI and API, and
  are removed from logs. Request and response bodies are never logged above DEBUG.
- Provider pricing and data-retention policies change. `GET /api/llm/recommendations` lists suggestions
  with links to each provider's pricing page; the app deliberately shows no prices of its own.
