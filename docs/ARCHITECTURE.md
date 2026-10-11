# Architecture

> **Status:** skeleton from Phase 01. Expanded by every phase that adds a component. The canonical
> design is [`SPECIFICATION.md`](SPECIFICATION.md) (section 15 amendments win over sections 1-14).

## System shape
Single-user, local-first web app. A FastAPI backend serves server-rendered Jinja2 pages with HTMX and
Alpine.js (all assets vendored, no CDN), pushes progress over SSE, and writes Markdown into the user's
Obsidian vault, which is the source of truth. Bound to `127.0.0.1:8765` by default.

## Components (spec section 4)
1. Upload and job orchestration service
2. Transcription and diarization pipeline (WhisperX)
3. Speaker mapping and voiceprint store
4. Template engine and prompt assembler
5. LLM backend abstraction and model recommender (Ollama, Bedrock, OpenAI-compatible)
6. Markdown writer/parser (round-trip)
7. Settings and config manager
8. Feedback collector

## Key refinements from section 15
- Python 3.12 + uv; package `meetingmaster3` in `src/`; CLI `mm3` (R1, R2).
- XDG paths for config, data and model cache, overridable by `MM3_*` variables (R3).
- Per-stage checkpoints in SQLite and job artifacts; resume from the first incomplete stage (R4).
- One GPU job at a time, with explicit VRAM handoff before the LLM stage (R5).
- Map-reduce note generation when the transcript exceeds about 70% of the context window (R6).
- Audio normalised to 16 kHz mono WAV, kept as Opus for 90 days by default (R7, R8).
- Strict section markers so regeneration never touches content outside them (R11).
- Security baseline S1-S8 applies to every component.

## Target layout
```
src/meetingmaster3/
  config/ domain/ markdown/ vault/ storage/ jobs/ audio/ hardware/
  transcription/ speakers/ llm/ templates/ feedback/ web/ starter_templates/
```
Full tree: `prompts/_shared-instructions.md` section 2. ML imports are lazy, inside
`transcription/` and `speakers/` only.

## Implemented so far (Phases 02, 05 and 08)
| Module | Responsibility |
|---|---|
| `app.py` | `create_app(settings)` factory. Middleware order (outermost first): TrustedHost, security headers, CSRF. |
| `cli.py` | Typer CLI `mm3`: `serve`, `version`, `doctor`, `config path`, `config show`, `llm list`, `llm test`. |
| `config/paths.py` | XDG directories with `MM3_*_DIR` overrides; created `0700`. |
| `config/settings.py` | Pydantic `Settings`. Precedence: defaults < `config.yaml` < `MM3_*` env. Atomic `0600` save. Secrets are `SecretStr`. |
| `errors.py` | `MM3Error(code, message, hint)` and a JSON/HTML exception handler chosen by `Accept`. |
| `logging.py` | Logging setup with a secret-redaction filter on the handler. |
| `web/security.py` | Security-headers and CSRF middleware. |
| `hardware/detect.py` | `HardwareInfo`: nvidia-smi, then torch.cuda (only if importable), then CPU/RAM from `/proc`. Cached; `get_hardware(refresh=True)` re-detects. |
| `hardware/profiles.py` | `cpu`, `vram8`, `vram16`, `vram24plus`, chosen from total VRAM or `hardware.profile`. |
| `hardware/recommend.py` + `recommendations.yaml` | Per-profile transcription and local-LLM recommendations, ETA estimates and risk warnings. All numbers are data, tagged estimated or measured. |
| `hardware/doctor.py` | Environment checks for `mm3 doctor` (ffmpeg, Python, ML extras, HF token, Ollama, vault, data dirs). |
| `web/hardware.py` | `GET /api/hardware`, `POST /api/hardware/refresh`. |
| `web/routes.py` | `GET /healthz`, `GET /` (Jinja2 base layout, placeholder page). |
| `llm/base.py` | `LLMBackend` protocol, request/result types, error codes (`E_LLM_*`), `is_local_url`. |
| `llm/ollama.py`, `openai_compat.py`, `bedrock.py` | The three adapters (Phase 08). Bedrock is lazy-imported; sync boto3 calls run in threads. |
| `llm/_http.py` | Shared httpx send with bounded jittered retries (429/5xx) and error normalisation. |
| `llm/registry.py` | Kind to factory map and `BackendRegistry` (config to cached backend instances). |
| `llm/budget.py`, `llm/consent.py` | 70% context budgeting and speaker-turn chunking; cloud-egress consent check. |
| `llm/recommendations.py` + `cloud_recommendations.yaml` | Local (Phase 05) plus cloud model suggestions, no prices. |
| `web/llm.py` | `/api/llm/*` routes (masked config, test, models, recommendations). |

All other packages are empty placeholders with a docstring, filled in by later phases.

_To be expanded in Phases 03-15 (data flow, job state machine, sequence diagrams)._
