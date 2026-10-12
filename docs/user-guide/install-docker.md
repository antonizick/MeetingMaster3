# Installation: Docker Compose

`docker compose up` gives you MeetingMaster3 on Linux, with an NVIDIA GPU or on the CPU alone.
Models are **not** baked into the image: they are downloaded once into a volume, after which jobs
make no network calls. For the non-Docker path see [install-native.md](install-native.md).

## Requirements
- Docker Engine 25 or newer with the Compose plugin (`docker compose version`; the files use `!reset`).
- For the GPU image: an NVIDIA driver that supports CUDA 12.8 (570 or newer) and the
  **NVIDIA Container Toolkit** (below). The CUDA toolkit is *not* needed on the host.
- Your Obsidian vault folder, and about 15 GB of disk for the GPU image (4 GB for the CPU image) plus
  about 2 GB for models.

## 1. NVIDIA Container Toolkit (GPU only)
```bash
# Arch / Omarchy
sudo pacman -S nvidia-container-toolkit
# Debian / Ubuntu: add NVIDIA's apt repository first, see
#   https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
sudo nvidia-ctk runtime configure --runtime=docker   # edits /etc/docker/daemon.json
sudo systemctl restart docker
docker run --rm --gpus all --entrypoint nvidia-smi meetingmaster3:gpu   # after the build, see below
```
To undo: remove the `"nvidia"` runtime entry from `/etc/docker/daemon.json`, restart Docker and
uninstall the package.

## 2. Start it
From the repository root:
```bash
cp .env.example .env              # optional: tokens and settings (never committed)
export MM3_VAULT_PATH="$HOME/Documents"          # your Obsidian vault folder (required)
docker compose -f docker/compose.yaml up -d --build           # GPU
docker compose -f docker/compose.yaml -f docker/compose.cpu.yaml up -d --build   # CPU only
```
Or with the Makefile: `make up`, `make up CPU=1`, `make logs`, `make doctor`, `make down`.
Open <http://127.0.0.1:8765/>. The first build takes several minutes (the GPU image holds PyTorch with
its CUDA libraries).

Download the models into the models volume (needs a Hugging Face token for diarization, see
[transcription.md](transcription.md); set `MM3_SECRETS__HF_TOKEN` in `.env` or in Settings):
```bash
make models-download     # = docker compose ... exec meetingmaster3 mm3 models download
make doctor              # hardware report from inside the container
```

## What is mounted
| Container path | Host side | Holds |
|---|---|---|
| `/vault` | `$MM3_VAULT_PATH` (bind mount) | notes and companion transcripts the app writes |
| `/config` | volume `mm3-config` | `config.yaml` (mode 0600, your keys), `settings` |
| `/data` | volume `mm3-data` | job database, retained audio, logs |
| `/models` | volume `mm3-models` | Hugging Face and torch model caches (`HF_HOME=/models/hf`) |

Files in the vault are owned by uid/gid **1000:1000** by default. If your host user differs, set
`MM3_UID` and `MM3_GID` (for example `export MM3_UID=$(id -u) MM3_GID=$(id -g)`) before `up --build`.
To use host folders instead of named volumes, replace `mm3-config:/config` etc. in `docker/compose.yaml`
with `./state/config:/config` (the folders must be writable by that uid).

The container runs as that non-root user with a read-only root filesystem, a `tmpfs` for `/tmp`, all
capabilities dropped and `no-new-privileges`.

## Network posture (read this)
MeetingMaster3 has no login, so the published port is bound to the **host's loopback only**
(`127.0.0.1:8765`; verify with `ss -ltnp | grep 8765`). Inside the container the app listens on `0.0.0.0`
(`MM3_SERVER__HOST`), because Docker's bridge cannot reach a container's own loopback, and the app prints a
warning about it; the port mapping is the guard. Never change the mapping to `0.0.0.0:8765`. To reach it
from another machine, use an SSH tunnel (`ssh -L 8765:127.0.0.1:8765 host`). `localhost` and `127.0.0.1`
are always accepted as Host headers; add any other hostname to `MM3_SERVER__ALLOWED_HOSTS='["mm3.lan"]'`.

## Reaching Ollama on the host
Ollama listens on `127.0.0.1:11434` by default, which a bridge-network container cannot reach through
`host.docker.internal`. Pick one:

| Option | How | Trade-off |
|---|---|---|
| **Host network for the app** (simplest on Linux) | add `-f docker/compose.host-network.yaml` (`make up HOSTNET=1`) | No host change. The app shares the host's network, binds `127.0.0.1` itself and reaches Ollama at `127.0.0.1:11434`. You lose Docker's port isolation, so the bind must stay on loopback. |
| Make Ollama listen on all interfaces | `sudo systemctl edit ollama` with `[Service]` / `Environment="OLLAMA_HOST=0.0.0.0"`, then restart | Ollama (also unauthenticated) becomes reachable from your LAN unless a firewall blocks 11434. |
| Bundled Ollama | `docker compose -f docker/compose.yaml --profile ollama up -d`, then `docker compose exec ollama ollama pull qwen3:8b` and set `MM3_OLLAMA_URL=http://ollama:11434` | A second copy of the models, and Ollama shares the GPU's 8 GB of VRAM with the transcriber. Because `ollama` is not a local-looking host name, the app treats it as a cloud endpoint and asks for consent: prefer a host Ollama. |

`host.docker.internal` is treated as local for consent and for the "unload Ollama before
transcribing" step.

## Single container (without Compose)
```bash
docker build -f docker/Dockerfile --target runtime-gpu -t meetingmaster3:gpu .
docker run -d --name meetingmaster3 --gpus all \
  --user 1000:1000 --read-only --tmpfs /tmp:size=2g --cap-drop ALL --security-opt no-new-privileges \
  -p 127.0.0.1:8765:8765 \
  -v "$HOME/Documents:/vault" -e MM3_VAULT__PATH=/vault \
  -v mm3-config:/config -v mm3-data:/data -v mm3-models:/models \
  --add-host host.docker.internal:host-gateway \
  -e MM3_LLM__BACKENDS__OLLAMA__KIND=ollama \
  -e MM3_LLM__BACKENDS__OLLAMA__BASE_URL=http://host.docker.internal:11434 \
  --restart unless-stopped meetingmaster3:gpu
```
Drop `--gpus all` and use `--target runtime-cpu` / `meetingmaster3:cpu` for the CPU image.

## Sizes, cleaning up and upgrading
Measured sizes are in ADR-0026 (GPU image 13.3 GB on disk, 4.6 GB compressed; CPU image 3.5 GB on disk).
```bash
docker image prune -f && docker builder prune -f   # dangling images and build cache (make prune)
docker system df -v                                # what takes the space, including volumes
docker volume rm meetingmaster3_mm3-models         # frees the models (they download again)
```
Upgrade with `git pull && make up`; the volumes keep your config, history and models. Removing the
`mm3-config` or `mm3-data` volumes deletes settings and job history (never your vault).

## Troubleshooting
- `could not select device driver "nvidia"`: the toolkit is missing or Docker was not restarted.
- `make doctor` shows "GPU: none detected": run the `nvidia-smi` check above; use the CPU override if
  the machine has no NVIDIA GPU.
- Notes appear owned by the wrong user: rebuild with the right `MM3_UID`/`MM3_GID`.
- "Host not allowed": add the host name to `MM3_SERVER__ALLOWED_HOSTS`.
