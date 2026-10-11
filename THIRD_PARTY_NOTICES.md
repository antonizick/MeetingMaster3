# Third-Party Notices

MeetingMaster3 is licensed under Apache-2.0 (see `LICENSE`). This file inventories the third-party
components the project plans to use. It is updated by every phase that adds a dependency or
vendored asset; the final audit is part of Phase 15.

> **Status:** pre-alpha. Nothing is redistributed yet; dependencies are installed from PyPI. The
> "Runtime dependencies (locked)" table below is generated from `uv.lock` by
> `uv run python scripts/gen_third_party.py`; re-run it whenever dependencies change. The "planned"
> table lists components not yet added; their versions are filled in when they are pinned, and
> licences are **re-verified when each dependency is added**.

## Runtime dependencies (locked)

Generated; do not edit by hand. Core runtime only (no dev tools, no optional `ml`/`bedrock` groups).

<!-- GENERATED:runtime-deps:start -->
| Package | Version | License |
|---|---|---|
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| certifi | 2026.7.22 | Mozilla Public License 2.0 (MPL 2.0) |
| click | 8.5.0 | BSD-3-Clause |
| colorama | 0.4.6 | BSD-3-Clause (Windows only) |
| fastapi | 0.143.0 | MIT |
| h11 | 0.16.0 | MIT License |
| httpcore | 1.0.9 | BSD-3-Clause |
| httptools | 0.9.0 | MIT |
| httpx | 0.28.1 | BSD License |
| idna | 3.20 | BSD-3-Clause |
| jinja2 | 3.1.6 | BSD License |
| markdown-it-py | 4.2.0 | MIT License |
| markupsafe | 3.0.4 | BSD-3-Clause |
| mdurl | 0.1.2 | MIT License |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| pydantic | 2.14.0 | MIT |
| pydantic-core | 2.50.0 | MIT |
| pydantic-settings | 2.15.0 | MIT |
| pygments | 2.21.0 | BSD-2-Clause |
| python-dotenv | 1.2.4 | BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| pyyaml | 6.0.3 | MIT License |
| rich | 15.0.0 | MIT License |
| shellingham | 1.5.4 | ISC License (ISCL) |
| starlette | 1.7.0 | BSD-3-Clause |
| typer | 0.27.3 | MIT |
| typing-extensions | 4.16.0 | PSF-2.0 |
| typing-inspection | 0.4.4 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| uvloop | 0.23.0 | Apache Software License; MIT License |
| watchfiles | 1.3.0 | MIT License |
| websockets | 17.2 | BSD-3-Clause |
<!-- GENERATED:runtime-deps:end -->

## Optional extras

| Component | Version | License | Use | Redistributed? (Y/N) | Extra |
|---|---|---|---|---|---|
| boto3 | 1.43.x | Apache-2.0 | AWS Bedrock Converse client | N | `bedrock` |
| botocore | 1.43.x | Apache-2.0 | boto3 core (pulled in by boto3) | N | `bedrock` |
| s3transfer, jmespath, python-dateutil, urllib3, six | see `uv.lock` | Apache-2.0 / MIT / BSD | boto3 dependencies | N | `bedrock` |

Development only (not distributed): `respx` (BSD-3-Clause), used to mock httpx in tests; `boto3` is also in the dev group so the Bedrock adapter is tested in CI.

## Planned components (not yet added)

| Component | Version | License | Use | Redistributed? (Y/N) | Status |
|---|---|---|---|---|---|
| WhisperX | tbd | BSD-2-Clause | Transcription, alignment, diarization orchestration | N | planned |
| faster-whisper | tbd | MIT | Whisper inference | N | planned |
| CTranslate2 | tbd | MIT | Inference engine for faster-whisper | N | planned |
| pyannote.audio | tbd | MIT | Speaker diarization and embeddings | N | planned |
| PyTorch | tbd | BSD-3-Clause | ML runtime | N | planned |
| HTMX | tbd | BSD-2-Clause | Browser-side server interaction | Y (vendored in `static/vendor/`) | planned |
| Alpine.js | tbd | MIT | Browser-side local state | Y (vendored in `static/vendor/`) | planned |

**ffmpeg and ffprobe** (LGPL-2.1+ or GPL-2.0+, depending on the build) are required at runtime since
Phase 04. MeetingMaster3 runs them as separate programs installed by the user (no linking, nothing
bundled); the Opus encoder used for retained audio is libopus (BSD-3-Clause) inside the user's ffmpeg.

Docker images (Phase 14) will additionally contain the base image, ffmpeg (LGPL/GPL depending on
build) and NVIDIA CUDA runtime libraries under their own licences; those are listed here when the
image is built.

## Model weights (never bundled)

Model weights are **never** committed to this repository, baked into Docker images or redistributed
by this project. Users download them to their own machine, under the weights' own terms.

| Model family | License / terms | Notes |
|---|---|---|
| OpenAI Whisper (via faster-whisper / CTranslate2 conversions) | MIT | Downloaded on first use into the model cache. |
| pyannote gated models (speaker diarization / segmentation) | Gated on Hugging Face; terms set by the model authors | Each user must accept the terms on Hugging Face and supply their own token. Exact model IDs and acceptance URLs are recorded in Phase 06. |
| wav2vec2 alignment models | Varies per language model | Chosen and recorded in Phase 06. |
| LLMs (Ollama, Bedrock, OpenAI-compatible endpoints) | Chosen by the user; each has its own licence | The project ships no LLM. |

## Vendored front-end assets

Added in Phase 10 and later (Markdown editor, diff renderer, etc.), each with version and licence
recorded here. No assets are loaded from a CDN at runtime.
