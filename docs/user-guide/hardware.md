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
Writing the notes with a local `qwen3:8b` adds about 3-4 minutes per hour of audio, so a whole job takes
about 8-10 minutes. Peak GPU memory was 2.8 GB for transcription and 5.8 GB for the LLM (never at the
same time). `medium` was not faster than `large-v3-turbo`. The other speeds are still **estimates**
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

## Warnings
Each warning has a severity (`info`, `warning`, `critical`). Examples: `large-v3` with `float16` on
8 GB (critical, likely out of memory), a 14B model on 8 GB (critical, spills to the CPU), another
program using most of the VRAM, or a large Whisper model on a CPU-only machine.

## Where the numbers live
`src/meetingmaster3/hardware/recommendations.yaml`. Each profile's values are tagged
`status: estimated` or `status: measured`.
