# Third-Party Notices

MeetingMaster3 is licensed under Apache-2.0 (see `LICENSE`). This file inventories the third-party
components the project plans to use. It is updated by every phase that adds a dependency or
vendored asset; the final audit is part of Phase 15.

> **Status:** pre-alpha. Nothing below is installed or redistributed yet. Versions are filled in when
> each dependency is pinned in `uv.lock` (Phase 02 onward). Licences are the upstream licences as
> understood at planning time and are **re-verified when each dependency is added**.

## Software components

| Component | Version | License | Use | Redistributed? (Y/N) | Status |
|---|---|---|---|---|---|
| FastAPI | tbd | MIT | Web framework / API | N (installed from PyPI) | planned |
| WhisperX | tbd | BSD-2-Clause | Transcription, alignment, diarization orchestration | N | planned |
| faster-whisper | tbd | MIT | Whisper inference | N | planned |
| CTranslate2 | tbd | MIT | Inference engine for faster-whisper | N | planned |
| pyannote.audio | tbd | MIT | Speaker diarization and embeddings | N | planned |
| PyTorch | tbd | BSD-3-Clause | ML runtime | N | planned |
| HTMX | tbd | BSD-2-Clause | Browser-side server interaction | Y (vendored in `static/vendor/`) | planned |
| Alpine.js | tbd | MIT | Browser-side local state | Y (vendored in `static/vendor/`) | planned |

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
