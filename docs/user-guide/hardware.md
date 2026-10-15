# Hardware and model recommendations

MeetingMaster3 detects your GPU and picks sensible transcription settings and local-LLM suggestions
for it. Detection needs no ML packages: it uses `nvidia-smi`, then `torch.cuda` if torch happens to
be installed, then falls back to the CPU. AMD (ROCm) and Apple GPUs are not supported and are
treated as CPU-only.

## Check your machine
```bash
uv run mm3 doctor
```
Prints the detected hardware, the profile, the recommended settings, any warnings, and environment
checks (ffmpeg and ffprobe, Python, the transcription engine and its downloaded models, Hugging
Face token, Ollama, vault, data directories).
It exits non-zero only for blocking problems (missing ffmpeg, wrong Python, an unwritable vault or
data directory). The same data is available at `GET /api/hardware`; `POST /api/hardware/refresh`
re-runs detection (for example after you close another GPU program).

## Profiles
The profile is chosen from total VRAM. Thresholds sit a little below the nominal size because cards
report slightly less (an "8 GB" card shows 8192 MiB).

| Profile | Total VRAM | Whisper model | Compute type | Batch | Diarization | Speed (x real time) |
|---|---|---|---|---|---|---|
| `cpu` | under about 7 GB or no GPU | small (or medium) | int8 | 4 | optional | 0.5-2 |
| `vram8` | about 7-14 GB | large-v3-turbo (or medium, small) | int8_float16 | 8 | yes | 13-16 (measured) |
| `vram16` | about 14-22 GB | large-v3 (or large-v3-turbo) | float16 | 16 | yes | 30-50 |
| `vram24plus` | about 22 GB and up | large-v3 (or large-v3-turbo) | float16 | 24 | yes | 40-70 |

The `vram8` speed was **measured** in Phase 15 on the reference laptop (RTX 2070 Max-Q 8 GB, whole
transcribe + align + diarize pipeline, diarization on): 10 minutes of audio in 47 s, 31 minutes in
139 s and 72 minutes in 275 s, so **a 60-minute meeting takes about 4-5 minutes** to transcribe.
Writing the notes with a local `qwen3:8b`, with the recommended Ollama settings below, adds about
2 minutes per hour of audio with a short template such as Executive Summary (a whole job about 6-7
minutes) and about 3.5-4 minutes with the default template, **Default Notes**, which writes much
fuller notes (a whole job about 8-9 minutes, see [`../PERFORMANCE.md`](../PERFORMANCE.md)). With
Ollama's default settings the notes take about twice as long. Peak GPU memory was 2.8 GB for
transcription and about 6 GB for the LLM (never at the same time). `medium` was not faster than `large-v3-turbo`. The other speeds are still **estimates**
from the specification; they are targets, not promises. Before a job starts, the app shows
`duration / speed` as a range, plus the notes time when the default backend is local. Method and raw
numbers: [PERFORMANCE.md](../PERFORMANCE.md). More in [transcription.md](transcription.md).

### Overriding the profile
Set `hardware.profile` in `config.yaml` (or `MM3_HARDWARE__PROFILE`) to `cpu`, `vram8`, `vram16` or
`vram24plus`. The default `auto` uses detection. Declaring a profile larger than the real GPU produces
a warning, because out-of-memory failures are likely.

## Local LLM (Ollama) suggestions
| Profile | Suggested models | Context that fits |
|---|---|---|
| `cpu` | 3-4B at Q4_K_M, or use a cloud backend | short prompts only |
| `vram8` | 7-9B at Q4_K_M (Llama 3.1 8B, Qwen 2.5 7B, Gemma 2 9B) | about 8k-16k tokens |
| `vram16` | 12-14B at Q4_K_M, or 8B at Q8_0 | about 16k-32k tokens |
| `vram24plus` | about 30B at Q4_K_M, or 14B at Q8_0 | 32k+ tokens |

**VRAM handoff.** On 8 GB, transcription and the LLM never use the GPU at the same time. The app
unloads the transcription models before the note-writing step (and asks Ollama to unload before
transcription starts), so the LLM step begins after transcription ends.

### Ollama settings for small GPUs (recommended on 8 GB)
Ollama never runs out of GPU memory: it fills the free VRAM and **silently runs the rest of the
model on the CPU**, which is several times slower. On an 8 GB laptop the desktop itself holds 1-1.5
GB, and `qwen3:8b`'s weights are about 5.2 GB, so with Ollama's defaults a quarter or more of the
model ends up on the CPU at the context sizes the app uses (12-13k tokens). Two Ollama server
settings shrink the context memory (the KV cache) and fix most of that:

| Variable | Value | What it does |
|---|---|---|
| `OLLAMA_FLASH_ATTENTION` | `1` | A faster attention kernel that also needs less memory. Required by the next one. |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Stores the context cache in 8 bits instead of 16: about half the memory, with a very small loss of precision (Ollama's FAQ recommends it over `q4_0`). |

Measured on the reference laptop (RTX 2070 Max-Q 8 GB, Ollama 0.33.3, `qwen3:8b`, 12k context):
**the share of the model on the CPU fell from 25 % to 16 %, GPU memory by about 0.8 GB, and writing
went from 6.8 to 10-17 tokens per second**. Whole notes became about twice as fast (see
[`../PERFORMANCE.md`](../PERFORMANCE.md)). Recent Ollama versions turn flash attention on by
themselves where the GPU supports it; setting it explicitly does no harm. Where it is not supported
(some older GPUs, some CPUs), Ollama keeps the normal 16-bit cache.

**MeetingMaster3 never changes your Ollama settings.** They are set on the Ollama *server*:

- **Linux, systemd service** (the standard install): `sudo systemctl edit ollama.service`, add
  ```ini
  [Service]
  Environment="OLLAMA_FLASH_ATTENTION=1"
  Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
  ```
  then `sudo systemctl daemon-reload && sudo systemctl restart ollama`. This creates a drop-in file
  (`/etc/systemd/system/ollama.service.d/override.conf`) that package updates leave alone; delete it
  and restart to undo. For a per-user service use `systemctl --user edit <unit>`.
- **Started by hand:** `OLLAMA_FLASH_ATTENTION=1 OLLAMA_KV_CACHE_TYPE=q8_0 ollama serve`.
- **Docker:** the bundled `ollama` service in `docker/compose.yaml` already sets both (override them
  in `.env` if needed); for your own container add `-e OLLAMA_FLASH_ATTENTION=1 -e
  OLLAMA_KV_CACHE_TYPE=q8_0` to `docker run`.
- **macOS app / Windows:** set them as environment variables for Ollama (Ollama FAQ, "How do I
  configure Ollama server?") and restart it.

**Check it:** while a note is being written, run `ollama ps`. `PROCESSOR` shows the split (for
example `16%/84% CPU/GPU`; `100% GPU` is ideal) and `CONTEXT` the context the app asked for. If the
CPU share is high, close GPU-heavy programs (browsers with hardware acceleration use some), or pick a
smaller model.

The app itself asks for only the context a note needs: the largest single call plus a 10 % safety
margin, the same for every call of a note (ADR-0043). With the default `generation.max_context`
(16 384) that is about 13k tokens for a long meeting, and less for short ones.

## Warnings
Each warning has a severity (`info`, `warning`, `critical`). Examples: `large-v3` with `float16` on
8 GB (critical, likely out of memory), a 14B model on 8 GB (critical, spills to the CPU), another
program using most of the VRAM, or a large Whisper model on a CPU-only machine.

## Where the numbers live
`src/meetingmaster3/hardware/recommendations.yaml`. Each profile's values are tagged
`status: estimated` or `status: measured`.
