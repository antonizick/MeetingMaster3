# Phase 14: Docker & Deployment

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 11, 12 · **Branch:** `phase-14-docker-deployment`

## Read first
`CLAUDE.md`, `prompts/_shared-instructions.md`, and `docs/SPECIFICATION.md` §11, §15.2 (R3, R15, R16) and §15.3 (S1, S5). The Phase 06 ADR (ML pins and CUDA/cuDNN requirements). Nick's OSMods README at `/home/nick/Documents/04 Resources/OSMods/README.md` (host changes must be documented there).

## Goal
`docker compose up` gives a working MeetingMaster3 on Linux, with GPU (NVIDIA) and CPU variants, persistent volumes, connectivity to the host's Ollama, no models baked in, and a lean, secure image.

## Tasks
1. **Dockerfile** (`docker/Dockerfile`), multi-stage:
   - `builder`: uv (copied from the official `ghcr.io/astral-sh/uv` image at a pinned digest), `uv sync --frozen --no-dev --extra ml [--extra bedrock]` into `/opt/venv`, with bytecode compiled.
   - `runtime-gpu`: per R15, **measure both** options, `nvidia/cuda:<ver>-cudnn-runtime-ubuntu24.04` + Python 3.12 versus `python:3.12-slim` + the pip `nvidia-*-cu12` wheels that torch already brings (check whether CTranslate2 finds cuDNN there). Pick the one that works and is smaller; record both sizes in an ADR.
   - `runtime-cpu`: `python:3.12-slim` with CPU torch wheels (use the PyTorch CPU index through a uv index config).
   - Install `ffmpeg` (minimal), and `tini` as PID 1. Run as a **non-root user** (uid/gid configurable via build args so vault file ownership matches the host user, default 1000:1000). `HEALTHCHECK` on `/healthz`. Env: `MM3_CONFIG_DIR=/config`, `MM3_DATA_DIR=/data`, `MM3_MODELS_DIR=/models`, `HF_HOME=/models/hf`, `MM3_SERVER__HOST=0.0.0.0` inside the container (Phase 02 settings use `MM3_<SECTION>__<FIELD>` names; a non-loopback host prints a warning) **with** the compose port mapping bound to `127.0.0.1` on the host (S1). Document this distinction clearly. `localhost` and `127.0.0.1` are always trusted (the port is ignored); any other hostname must be listed in `MM3_SERVER__ALLOWED_HOSTS` (JSON list).
   - OCI labels (source, license, version). No secrets in layers. A `.dockerignore` that excludes tests, docs, `.git`, caches, audio and `.env`.
2. **Compose** (`docker/compose.yaml`): service `meetingmaster3`, `ports: ["127.0.0.1:8765:8765"]`, volumes `${MM3_VAULT_PATH}:/vault` (compose variable; set `MM3_VAULT__PATH=/vault` in the container environment), `mm3-config:/config`, `mm3-data:/data`, `mm3-models:/models` (named volumes or bind mounts, documented), a GPU reservation (`deploy.resources.reservations.devices: [{driver: nvidia, count: 1, capabilities: [gpu]}]`), `extra_hosts: ["host.docker.internal:host-gateway"]`, the default Ollama URL `http://host.docker.internal:11434`, `env_file: .env` (optional), `restart: unless-stopped`, and `read_only: true` with tmpfs for `/tmp` if feasible. `docker/compose.cpu.yaml` is an override without the GPU. An optional `ollama` profile runs `ollama/ollama` with its own GPU reservation and volume, and documents the VRAM sharing caveat (R5).
3. **Host Ollama reachability (R16):** the host Ollama listens on 127.0.0.1 by default, which the container cannot reach via host-gateway. Document the options: `OLLAMA_HOST=0.0.0.0` via a systemd drop-in (security trade-off: firewall it), `network_mode: host` for the app (simplest on Linux; port binding then comes from MM3_HOST, so keep it 127.0.0.1), or the `ollama` compose profile. **Ask Nick which to use on his machine** before changing any host service, and document whatever host change is made in OSMods.
4. **NVIDIA Container Toolkit:** `mm3 doctor` inside the container detects the GPU. The install guide covers `nvidia-container-toolkit` installation and `nvidia-ctk runtime configure --runtime=docker`. If it is not installed on the reference machine, **ask Nick before installing**. If installed, document it in OSMods with undo steps.
5. **Image hygiene:** target sizes are recorded (measure, don't guess). A `make` or `just` file (or `scripts/`) for build, up, down, logs, doctor, `models-download` (run inside the container to populate the models volume) and prune. Document the prune guidance (`docker image prune`, builder cache, models volume size).
6. **Single-container alternative** (spec §11): a documented `docker run` command equivalent to the compose setup.
7. **CI:** a workflow that builds the CPU image (and the GPU image without running it) on PRs that touch `docker/` or dependencies, with a smoke test that runs the CPU container, hits `/healthz` and runs `mm3 doctor --no-gpu`. Optional: publish to GHCR on tags (disabled until Phase 16, behind a manual approval).
8. **Native install path:** document the non-Docker path too (uv + system ffmpeg + NVIDIA driver), since that is how Nick develops.

## Tests and verification
On the reference machine: build both images and record the sizes; `docker compose up`; complete a real fixture meeting end to end from the browser with the GPU in the container and Ollama reachable; verify the files land in the mounted vault with the correct host ownership; restart the container and confirm the job history and config persist; confirm the CPU variant works (slowly) with a short clip.

## Acceptance criteria
- Measured image sizes are documented. No model weights are in the image (verified with `docker history` / `dive`).
- The end-to-end flow works in the GPU container on the 8 GB machine, and the vault files are owned by uid 1000.
- The port is bound only to 127.0.0.1 on the host (verify with `ss -ltnp`).

## Phase-specific docs
`docs/user-guide/install-docker.md`, `docs/user-guide/install-native.md`, README Installation (both paths; Docker primary), SECURITY (container posture, port binding, Ollama exposure trade-off), ADR (base image choice with sizes), and the OSMods documentation for any host change (toolkit, Ollama drop-in, Docker config). Then the standard close-out checklist.
