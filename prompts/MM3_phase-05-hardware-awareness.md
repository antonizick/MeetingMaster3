# Phase 05: Hardware Detection & Model Recommendations

**Model:** Sonnet 5.5 (`/model claude-sonnet-5-5`) · **Depends on:** 02 (can run in parallel with 03, 04 and 08) · **Branch:** `phase-05-hardware-awareness`

## Read first
`CLAUDE.md`, `prompts/MM3_shared-instructions.md`, and `docs/MM3_SPECIFICATION.md` §3 (flow step 3), §7 (hardware table), §8 (model recommendations), §10 and §15.2 (R5, R17). Also design pre-notes §4, via spec Appendix A context.

## Goal
The app knows what hardware it is running on and turns that into concrete, explained recommendations for transcription settings and local LLM models. It works without torch installed, so detection must not depend on the ML extras.

## Tasks
1. **`hardware/detect.py`:** detection chain: `nvidia-smi --query-gpu=name,memory.total,memory.used,driver_version --format=csv,noheader,nounits` (subprocess with a timeout), then torch.cuda if it is importable, then a CPU-only fallback (core count, RAM from `/proc/meminfo` or psutil). Returns a `HardwareInfo` (gpus[], cuda_available, free_vram, cpu, ram). Cached, with a refresh option. AMD/ROCm and Apple are out of scope; detect and report them as "unsupported, CPU fallback".
2. **`hardware/profiles.py`:** the profiles `cpu`, `vram8`, `vram16` and `vram24plus`, auto-selected from total VRAM. **The user can override in settings** (spec: "or accepts user declaration").
3. **`hardware/recommend.py`:**
   - Transcription: whisper model (large-v3, large-v3-turbo, medium, small), `compute_type` (float16, int8_float16, int8), `batch_size`, whether diarization is recommended, expected RTF range, and an ETA function `estimate(duration_s) → (low, high)`. Seed the values from the spec §7 table, keep them in a data file (`hardware/recommendations.yaml`) so measured numbers from Phase 15 can replace them, and mark them `estimated` vs `measured`.
   - LLM (local Ollama): model families that fit each profile, e.g. 8 GB → 7–8B at Q4_K_M; 16 GB → 12–14B; 24 GB → ~30B Q4. Include an approximate context-window note and a "quality vs speed" description. Data-driven in the same YAML. Note the **VRAM handoff** (R5): on 8 GB, transcription and the LLM never share the GPU at the same time.
   - Risk warnings: e.g. large-v3 + float16 on 8 GB, or a 14B LLM on 8 GB. Each warning carries a severity and a message.
4. **API:** `GET /api/hardware` (info, chosen profile, recommendations, warnings) and `POST /api/hardware/refresh`.
5. **CLI `mm3 doctor`:** prints the hardware, profile and recommendations, plus environment checks: ffmpeg/ffprobe present, Python version, ML extras installed?, HF token configured?, Ollama reachable (`GET /api/tags` on the configured URL, short timeout)?, vault path writable?, data-dir permissions. Exits non-zero on blocking problems. Phases 06, 08 and 14 extend it.

## Tests
Parse fixtures of `nvidia-smi` output (single and multi-GPU, an 8 GB 2070 Max-Q, a 24 GB 4090, missing binary, garbage output); profile selection boundaries; user override; recommendation and warning tables; doctor checks using fakes. One `gpu`-marked test runs real detection on the reference machine.

## Acceptance criteria
- On the reference machine, `uv run mm3 doctor` reports the RTX 2070 Max-Q with 8 GB, the `vram8` profile, and sensible recommendations.
- The app runs with no GPU and no torch.

## Phase-specific docs
README "Hardware guidance" section (table from the YAML; values marked as estimates); `docs/user-guide/hardware.md`; configuration doc (profile override). Then the standard close-out checklist.
