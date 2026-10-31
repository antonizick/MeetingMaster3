# Third-Party Notices

MeetingMaster3 is licensed under Apache-2.0 (see `LICENSE`). This file inventories every third-party
component the project uses. It is updated by every phase that adds a dependency or vendored asset.

> **Audit (Phase 15, 2026-10-12):** all 144 locked packages (core, `ml` and `bedrock` extras) were
> checked. Every one is under a permissive licence (MIT, BSD, Apache-2.0, PSF, ISC, MPL-2.0 used
> unmodified) **except** NVIDIA's CUDA/cuDNN wheels (proprietary, GPU only, pulled in by PyTorch and
> installed from PyPI under NVIDIA's terms). **No GPL, AGPL or LGPL Python dependency.** The only
> GPL component is Debian's `ffmpeg` build inside the Docker images, run as a separate program
> (see "Docker images" below). The two dependency tables are generated from `uv.lock`:
> `uv run --extra ml --extra bedrock python scripts/gen_third_party.py` (add `--check` to verify the
> file is current and that no dependency needs a licence decision). Nothing is redistributed by this
> repository yet; dependencies are installed from PyPI.

## Runtime dependencies (locked)

Generated; do not edit by hand. Core runtime only (no dev tools, no optional `ml`/`bedrock` groups).

<!-- GENERATED:runtime-deps:start -->
| Package | Version | License |
|---|---|---|
| annotated-doc | 0.0.5 | MIT |
| annotated-types | 0.8.0 | MIT |
| anyio | 4.15.1 | MIT |
| certifi | 2026.10.23 | Mozilla Public License 2.0 (MPL 2.0) |
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

## Optional extras (summary)

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

### Optional extras (locked, generated)

Every package the `ml` and `bedrock` extras add to the core runtime. Generated; do not edit by hand.

<!-- GENERATED:extras-deps:start -->
| Package | Version | License |
|---|---|---|
| aiohappyeyeballs | 2.7.1 | Python Software Foundation License |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT |
| aiosignal | 1.4.0 | Apache Software License |
| alembic | 1.20.0 | MIT |
| asteroid-filterbanks | 0.4.0 | MIT License |
| attrs | 26.1.0 | MIT |
| av | 19.0.1 | BSD-3-Clause |
| boto3 | 1.43.111 | Apache-2.0 |
| botocore | 1.43.111 | Apache-2.0 |
| charset-normalizer | 3.5.2 | MIT |
| cloudpickle | 3.1.2 | BSD License |
| colorlog | 6.12.0 | MIT License |
| contourpy | 1.4.0 | BSD-3-Clause |
| ctranslate2 | 4.8.2 | MIT |
| cycler | 0.12.1 | BSD License |
| defusedxml | 0.7.1 | Python Software Foundation License |
| einops | 0.8.2 | MIT License |
| faster-whisper | 1.2.1 | MIT License |
| filelock | 4.2.6 | MIT |
| flatbuffers | 25.12.19 | Apache Software License |
| fonttools | 4.66.1 | MIT |
| frozenlist | 1.8.0 | Apache-2.0 |
| fsspec | 2026.9.0 | BSD-3-Clause |
| googleapis-common-protos | 1.75.5 | Apache-2.0 |
| grpcio | 1.84.0 | Apache-2.0 |
| hf-xet | 1.7.0 | Apache-2.0 |
| huggingface-hub | 0.36.2 | Apache Software License |
| jmespath | 1.1.0 | MIT License |
| joblib | 1.6.0 | BSD-3-Clause |
| julius | 0.2.8 | MIT License |
| kiwisolver | 1.5.1 | BSD License |
| lightning | 2.6.6 | Apache Software License |
| lightning-utilities | 0.15.3 | Apache-2.0 |
| mako | 1.4.3 | MIT |
| matplotlib | 3.11.2 | Python Software Foundation License |
| mpmath | 1.3.0 | BSD License |
| multidict | 7.1.0 | Apache-2.0 |
| narwhals | 2.27.1 | MIT |
| networkx | 3.7 | BSD-3-Clause |
| nltk | 3.10.3 | Apache Software License |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| nvidia-cublas-cu12 | 12.8.4.1 | Other/Proprietary License |
| nvidia-cuda-cupti-cu12 | 12.8.90 | Other/Proprietary License |
| nvidia-cuda-nvrtc-cu12 | 12.8.93 | Other/Proprietary License |
| nvidia-cuda-runtime-cu12 | 12.8.90 | Other/Proprietary License |
| nvidia-cudnn-cu12 | 9.10.2.21 | Other/Proprietary License |
| nvidia-cufft-cu12 | 11.3.3.83 | Other/Proprietary License |
| nvidia-cufile-cu12 | 1.13.1.3 | Other/Proprietary License |
| nvidia-curand-cu12 | 10.3.9.90 | Other/Proprietary License |
| nvidia-cusolver-cu12 | 11.7.3.90 | Other/Proprietary License |
| nvidia-cusparse-cu12 | 12.5.8.93 | Other/Proprietary License |
| nvidia-cusparselt-cu12 | 0.7.1 | NVIDIA Proprietary Software |
| nvidia-nccl-cu12 | 2.27.3 | Other/Proprietary License |
| nvidia-nvjitlink-cu12 | 12.8.93 | Other/Proprietary License |
| nvidia-nvtx-cu12 | 12.8.90 | Other/Proprietary License |
| omegaconf | 2.4.0 | BSD License |
| onnxruntime | 1.31.0 | MIT License |
| opentelemetry-exporter-http-transport | 0.66b1 | Apache-2.0 |
| opentelemetry-exporter-otlp | 1.45.1 | Apache-2.0 |
| opentelemetry-exporter-otlp-common | 0.66b1 | Apache-2.0 |
| opentelemetry-exporter-otlp-proto-common | 1.45.1 | Apache-2.0 |
| opentelemetry-exporter-otlp-proto-grpc | 1.45.1 | Apache-2.0 |
| opentelemetry-exporter-otlp-proto-http | 1.45.1 | Apache-2.0 |
| opentelemetry-proto | 1.45.1 | Apache-2.0 |
| opentelemetry-sdk | 1.45.1 | Apache-2.0 |
| opentelemetry-semantic-conventions | 0.66b1 | Apache-2.0 |
| optuna | 5.0.0 | MIT License |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pandas | 3.0.6 | BSD License |
| pillow | 13.0.0 | MIT-CMU |
| primepy | 1.3 | MIT License |
| propcache | 0.5.4 | Apache-2.0 |
| protobuf | 7.36.2 | 3-Clause BSD License |
| pyannote-audio | 4.0.7 | MIT |
| pyannote-core | 6.0.1 | MIT |
| pyannote-database | 6.1.1 | MIT |
| pyannote-metrics | 4.1 | MIT |
| pyannote-pipeline | 4.0.0 | MIT |
| pyannoteai-sdk | 0.4.0 | MIT |
| pyparsing | 3.3.3 | MIT |
| python-dateutil | 2.9.0.post0 | BSD License; Apache Software License |
| pytorch-lightning | 2.6.6 | Apache Software License |
| pytorch-metric-learning | 2.9.0 | MIT License |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python |
| requests | 2.34.2 | Apache Software License |
| s3transfer | 0.19.2 | Apache Software License |
| safetensors | 0.8.0 | Apache Software License |
| scikit-learn | 1.9.1 | BSD-3-Clause |
| scipy | 1.18.1 | BSD License |
| setuptools | 84.2.1 | MIT |
| six | 1.17.0 | MIT License |
| sortedcontainers | 2.4.0 | Apache Software License |
| sqlalchemy | 2.1.4 | MIT |
| sympy | 1.14.0 | BSD License |
| threadpoolctl | 3.7.0 | BSD-3-Clause |
| tokenizers | 0.22.2 | Apache Software License |
| torch | 2.8.0 | BSD License |
| torch-audiomentations | 0.12.0 | MIT License |
| torch-pitch-shift | 1.2.5 | MIT License |
| torchaudio | 2.8.0 | BSD License |
| torchcodec | 0.7.0 | BSD-3-Clause |
| torchmetrics | 1.9.0 | Apache Software License |
| torchvision | 0.23.0 | BSD |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| transformers | 4.57.6 | Apache Software License |
| triton | 3.4.0 | MIT License |
| tzdata | 2026.5 | Apache-2.0 (Windows only) |
| urllib3 | 2.8.0 | MIT |
| whisperx | 3.8.6 | BSD-2-Clause |
| yarl | 1.25.1 | Apache-2.0 |
<!-- GENERATED:extras-deps:end -->

Development only (not distributed): `respx` (BSD-3-Clause), used to mock httpx in tests; `boto3` is also in the dev group so the Bedrock adapter is tested in CI.

## Vendored browser assets (Phase 10)

Copied unmodified from the npm packages into `src/meetingmaster3/web/static/vendor/` (licence file next to each;
versions in `vendor/VERSIONS.txt`). Served by the app itself; the browser never contacts a CDN.

| Component | Version | License | Use | Redistributed? (Y/N) |
|---|---|---|---|---|
| htmx.org | 2.0.11 | 0BSD (Zero-Clause BSD) | Server interaction (partials, actions) | Y |
| @alpinejs/csp | 3.17.4 | MIT | Local UI state, CSP-safe build | Y |

Dev-only: `playwright` 1.63.0 (Apache-2.0) drives the browser tests; it downloads no browser unless you run
`playwright install`. Test-only vendored asset: `tests/e2e/vendor/axe.min.js`, axe-core 4.10.2 (MPL-2.0, licence in
`tests/e2e/vendor/axe-core.LICENSE`, unmodified), injected only by the accessibility test; never served by the app,
not in the wheel or the Docker images.

## Project logo (Phase 15a)

`src/meetingmaster3/web/static/brand/logo*.{webp,png}` is a crop of a photo-composite of the
author, and `hero*.{webp,png}` (the New meeting page) is the whole composite, resized. **It is not covered by the Apache-2.0 licence: the author, Nick Antonizick, released it under
[CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/)** (see `NOTICE`, ADR-0035;
`brand/LICENSE.md`). Forks and redistributions may keep it. CC0 covers copyright only: no trademark
rights, and no right to use the likeness of a person shown (for example to suggest endorsement). The original image
is not in the repository; `scripts/make_logo.py` rebuilds the logo from a source passed as an
argument.

## Programs used at run time

**ffmpeg and ffprobe** (LGPL-2.1+ or GPL-2.0+, depending on the build) are required at runtime since
Phase 04. MeetingMaster3 runs them as separate programs installed by the user (no linking, nothing
bundled); the Opus encoder used for retained audio is libopus (BSD-3-Clause) inside the user's ffmpeg.

### Docker images
The images (`docker/Dockerfile`, built by the user; not published by this repository) contain, as
separate programs and libraries installed from their distributors:
- the `python:3.12-slim-trixie` base image (Debian 13 packages under their own licences, mostly
  GPL/LGPL system tools such as bash, coreutils and util-linux; PSF-2.0 for Python), `tini` (MIT);
- Debian's `ffmpeg` and its libraries (`libavcodec61`, ...). **Debian builds ffmpeg with GPL parts
  enabled, so this build is GPL-2.0-or-later.** MeetingMaster3 only executes it as a subprocess
  (no linking), so the app's Apache-2.0 licence is unaffected (aggregation);
- the Python environment from `uv.lock` (tables above), including NVIDIA's CUDA/cuDNN wheels in the
  GPU image (NVIDIA licences, which permit redistribution as part of those wheels).

**If images are ever published** (for example to GHCR in Phase 16), GPL obligations apply to the
Debian packages in them: keep the Debian copyright files (`/usr/share/doc/*/copyright`, present in
the image), and make the corresponding sources available (Debian's source archive for the exact
versions, or a written offer). `uv` (Apache-2.0/MIT) is used only in the build stage. `curl` and the
base image's system `pip` are removed from the runtime image since Phase 15.

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
| Embedding models for search (Phase 15i): [`nomic-embed-text`](https://ollama.com/library/nomic-embed-text) (default, through Ollama); optionally Amazon Titan Text Embeddings V2 or Cohere Embed on Bedrock, or a model on OpenRouter / an OpenAI-compatible server | `nomic-embed-text`: Apache-2.0 (Nomic AI). Cloud models: the provider's terms | Not bundled: the user pulls `nomic-embed-text` with `ollama pull` (274 MB) or calls a provider. No new Python dependency. |

## Test fixtures (in the repository)

| File | Source | License |
|---|---|---|
| `tests/fixtures/audio/ami-es2002a-two-speakers.fixture.opus` | 60 s excerpt (500-560 s) of meeting ES2002a, Mix-Headset, from the [AMI Meeting Corpus](https://groups.inf.ed.ac.uk/ami/corpus/), re-encoded to 16 kHz mono Opus | CC-BY-4.0. Attribution: AMI Meeting Corpus, University of Edinburgh and the AMI Consortium. See `tests/fixtures/README.md`. |

## Vendored front-end assets

See "Vendored browser assets (Phase 10)" above: htmx and the Alpine CSP build are the only vendored
third-party assets (no editor or diff library: ADR-0024); the logo is the project's own (see
"Project logo"). No assets are loaded from a CDN at runtime.
