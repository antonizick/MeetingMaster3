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
| WhisperX | 3.8.6 | BSD-2-Clause | Transcription, alignment and diarization orchestration | N | `ml` |
| faster-whisper | 1.2.1 | MIT | Whisper inference | N | `ml` |
| CTranslate2 | 4.8.2 | MIT | Inference engine for faster-whisper | N | `ml` |
| pyannote.audio (+ pyannote.core, .database, .metrics, .pipeline, pyannoteai-sdk) | 4.0.7 | MIT | Speaker diarization, voice activity detection | N | `ml` |
| PyTorch (torch), torchaudio, torchvision | 2.8.0 / 2.8.0 / 0.23.0 | BSD-3-Clause / BSD-2-Clause / BSD-3-Clause | ML runtime, wav2vec2 alignment | N | `ml` |
| torchcodec | 0.7.0 | BSD-3-Clause | Audio decoding for pyannote (unused: MeetingMaster3 passes in-memory audio) | N | `ml` |
| Triton | 3.4.0 | MIT | PyTorch GPU kernels | N | `ml` |
| NVIDIA CUDA runtime, cuBLAS, cuDNN 9.10 and other `nvidia-*-cu12` wheels | 12.8 | NVIDIA proprietary (CUDA EULA / cuDNN licence) | GPU libraries pulled in by PyTorch; installed by the user from PyPI | N | `ml` |
| transformers, tokenizers, safetensors, huggingface-hub | 4.57.6 / 0.22.2 / 0.8.0 / 0.36.2 | Apache-2.0 | Alignment models for non-torchaudio languages; model downloads | N | `ml` |
| Lightning, pytorch-lightning, torchmetrics | 2.6.6 / 2.6.6 / 1.9.0 | Apache-2.0 | pyannote model loading | N | `ml` |
| numpy, pandas | 2.5.4 / 3.0.6 | BSD-3-Clause (numpy also bundles 0BSD/MIT/Zlib/CC0 parts) | Arrays, diarization tables | N | `ml` |
| onnxruntime | 1.31.0 | MIT | WhisperX dependency | N | `ml` |
| nltk | 3.10.3 | Apache-2.0 | Sentence splitting during alignment | N | `ml` |
| opentelemetry-* | see `uv.lock` | Apache-2.0 | pyannote's telemetry client, **always disabled** by MeetingMaster3 (`PYANNOTE_METRICS_ENABLED=false`) | N | `ml` |
| Other transitive packages of the `ml` extra | see `uv.lock` | permissive (MIT / BSD / Apache-2.0) | | N | `ml` |

Development only (not distributed): `respx` (BSD-3-Clause), used to mock httpx in tests; `boto3` is also in the dev group so the Bedrock adapter is tested in CI.

## Vendored browser assets (Phase 10)

Copied unmodified from the npm packages into `src/meetingmaster3/web/static/vendor/` (licence file next to each;
versions in `vendor/VERSIONS.txt`). Served by the app itself; the browser never contacts a CDN.

| Component | Version | License | Use | Redistributed? (Y/N) |
|---|---|---|---|---|
| htmx.org | 2.0.11 | 0BSD (Zero-Clause BSD) | Server interaction (partials, actions) | Y |
| @alpinejs/csp | 3.17.4 | MIT | Local UI state, CSP-safe build | Y |

Dev-only: `playwright` 1.63.0 (Apache-2.0) drives the browser smoke test; it downloads no browser unless you run
`playwright install`.

## Planned components (not yet added)

| Component | Version | License | Use | Redistributed? (Y/N) | Status |
|---|---|---|---|---|---|

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
| OpenAI Whisper, CTranslate2 conversions (`Systran/faster-whisper-*`, `mobiuslabsgmbh/faster-whisper-large-v3-turbo`) | MIT | Downloaded on first use (or `mm3 models download`) into the model cache. |
| [`pyannote/speaker-diarization-community-1`](https://huggingface.co/pyannote/speaker-diarization-community-1) (segmentation, WeSpeaker embedding, PLDA) | CC-BY-4.0, gated | Each user accepts the terms at that URL and supplies their own read token, once. Attribution: pyannote.audio team / pyannoteAI. The WeSpeaker embedding model in its `embedding/` folder is also used directly for opt-in voiceprints (Phase 07); no extra download. |
| pyannote segmentation weights used for voice activity detection, shipped inside the WhisperX wheel (`whisperx/assets/pytorch_model.bin`) | MIT (pyannote), in the BSD-2-Clause WhisperX wheel | Not downloaded separately. |
| wav2vec2 alignment, English: torchaudio `WAV2VEC2_ASR_BASE_960H` (fairseq, trained on LibriSpeech) | MIT (fairseq weights) | Downloaded from download.pytorch.org into the model cache. |
| wav2vec2 alignment, fr/de/es/it: torchaudio VoxPopuli models; other languages: Hugging Face models chosen by WhisperX (for example `jonatasgrosman/wav2vec2-large-xlsr-53-*`) | Per model: VoxPopuli weights are CC-BY-NC-4.0 (non-commercial); check each Hugging Face model card | Only downloaded when a recording in that language is transcribed. |
| LLMs (Ollama, Bedrock, OpenAI-compatible endpoints) | Chosen by the user; each has its own licence | The project ships no LLM. |

## Test fixtures (in the repository)

| File | Source | License |
|---|---|---|
| `tests/fixtures/audio/ami-es2002a-two-speakers.fixture.opus` | 60 s excerpt (500-560 s) of meeting ES2002a, Mix-Headset, from the [AMI Meeting Corpus](https://groups.inf.ed.ac.uk/ami/corpus/), re-encoded to 16 kHz mono Opus | CC-BY-4.0. Attribution: AMI Meeting Corpus, University of Edinburgh and the AMI Consortium. See `tests/fixtures/README.md`. |

## Vendored front-end assets

Added in Phase 10 and later (Markdown editor, diff renderer, etc.), each with version and licence
recorded here. No assets are loaded from a CDN at runtime.
