# syntax=docker/dockerfile:1.7
# MeetingMaster3 image. Build from the repository root:
#   docker build -f docker/Dockerfile --target runtime-gpu -t meetingmaster3:gpu .
#   docker build -f docker/Dockerfile --target runtime-cpu -t meetingmaster3:cpu .
# No model weights are baked in: they live in the /models volume (`mm3 models download`).

ARG PYTHON_IMAGE=python:3.12-slim-trixie
ARG UV_IMAGE=ghcr.io/astral-sh/uv@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168

FROM ${UV_IMAGE} AS uv

# ---- builder (shared): project metadata + sources, no ML yet -------------------------------
FROM ${PYTHON_IMAGE} AS builder-base
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./

# ---- builder-gpu: the locked wheels from PyPI (torch 2.8.0 + CUDA 12.8 + cuDNN 9 wheels) ----
FROM builder-base AS builder-gpu
ARG EXTRAS="--extra ml --extra bedrock"
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project ${EXTRAS}
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable ${EXTRAS}

# ---- builder-cpu: same lock, then swap torch for the CPU-only wheels ------------------------
FROM builder-base AS builder-cpu
ARG EXTRAS="--extra ml --extra bedrock"
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project ${EXTRAS}
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable ${EXTRAS}
# CPU torch from the PyTorch CPU index (same versions as uv.lock), then drop the nvidia-* wheels
# and triton that the locked CUDA build pulled in.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /opt/venv/bin/python --reinstall --no-deps \
      --index-url https://download.pytorch.org/whl/cpu \
      "torch==2.8.0+cpu" "torchaudio==2.8.0+cpu" "torchvision==0.23.0+cpu" \
 && uv pip freeze --python /opt/venv/bin/python | sed -n 's/^\(nvidia-[^=]*\|triton\)==.*/\1/p' \
    | xargs -r uv pip uninstall --python /opt/venv/bin/python

# ---- runtime base: ffmpeg, tini, non-root user ----------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime-base
ARG MM3_UID=1000
ARG MM3_GID=1000
ARG VERSION=0.0.0
ARG REVISION=unknown
LABEL org.opencontainers.image.title="MeetingMaster3" \
      org.opencontainers.image.description="Local-first meeting transcription and note generation" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://example.invalid/OWNER/REPO" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"
# No curl (the healthcheck uses Python) and no system pip: neither is needed at run time, and both
# carried scanner findings (Phase 15). The app's own environment is /opt/venv (no pip either).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg tini \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip uninstall -y -q pip \
 && groupadd --gid ${MM3_GID} mm3 \
 && useradd --uid ${MM3_UID} --gid ${MM3_GID} --no-create-home --home-dir /tmp --shell /usr/sbin/nologin mm3 \
 && mkdir -p /config /data /models /vault \
 && chown ${MM3_UID}:${MM3_GID} /config /data /models /vault
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    MM3_IN_DOCKER=1 \
    MM3_CONFIG_DIR=/config MM3_DATA_DIR=/data MM3_CACHE_DIR=/data/cache MM3_MODELS_DIR=/models \
    HF_HOME=/models/hf TORCH_HOME=/models/torch \
    MM3_SERVER__HOST=0.0.0.0 MM3_SERVER__PORT=8765
EXPOSE 8765
VOLUME ["/config", "/data", "/models"]
USER mm3
WORKDIR /data
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=4)"]
ENTRYPOINT ["tini", "--"]
CMD ["mm3", "serve"]

# ---- runtime-cpu ------------------------------------------------------------------------------
FROM runtime-base AS runtime-cpu
COPY --from=builder-cpu /opt/venv /opt/venv

# ---- runtime-gpu (default last target) --------------------------------------------------------
# The cuDNN/cuBLAS/CUDA runtime libraries come from the nvidia-* wheels torch depends on
# (ADR-0014/0026); the host only needs an NVIDIA driver that supports CUDA 12.8.
FROM runtime-base AS runtime-gpu
COPY --from=builder-gpu /opt/venv /opt/venv
