# Phase 06: Transcription & Diarization Pipeline (WhisperX)

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 04, 05 · **Branch:** `phase-06-transcription-pipeline`

## Read first
`CLAUDE.md`, `prompts/_shared-instructions.md`, and `docs/SPECIFICATION.md` §3 (edge cases: non-English, OOM), §7, §10, §13 (pyannote risk), §15.2 (R4, R5, R14, R17) and §15.3 (S5, S7). Phase Log entries for 04 and 05. Open question Q4 (test audio).

## Goal
Real, local, diarized transcription as job stages (`transcribe`, `align`, `diarize`) that produce a `domain.Transcript`, working on the 8 GB reference GPU and degrading gracefully.

## Tasks
1. **Dependencies:** add the `ml` extra with WhisperX and its torch/pyannote dependencies, pinned to versions that work together on Python 3.12 + CUDA 12.x. **Verify by actually installing them on the reference machine.** Record the exact versions, the CUDA/cuDNN requirements and any gotchas (e.g. cuDNN version mismatches with CTranslate2) in an ADR. Check the licences and update THIRD_PARTY_NOTICES.
2. **Model management (`transcription/models.py`):** cache under `MM3_MODELS_DIR` (`HF_HOME`, `TORCH_HOME` and the faster-whisper download root all point there); `mm3 models download [--whisper large-v3-turbo] [--diarization]` pre-fetches models; offline mode (`HF_HUB_OFFLINE=1`) is honoured when models are present. For the diarization model, determine the exact pyannote pipeline ID the pinned WhisperX expects (R14), and give clear guidance: "accept the terms at <URL>, create a read token, paste it in Settings". The HF token comes from settings or env as a secret and is passed explicitly, never logged.
3. **Stages (`transcription/stages.py`)**, implementing the Phase 04 `Stage` protocol with lazy imports:
   - `TranscribeStage`: loads faster-whisper through WhisperX with the recommended or overridden model, compute_type and batch_size; checks the detected language after the first chunk, and if it is not English emits a warning (spec §3) and pauses for the user to choose **proceed** or **abort**, reusing the `waiting_for_input` mechanism or a job option `on_non_english`; writes `transcript.json`.
   - `AlignStage`: wav2vec2 alignment for word timestamps; writes `aligned.json`. If alignment fails, warn and continue with segment-level timestamps.
   - `DiarizeStage`: pyannote with optional `min_speakers`/`max_speakers` hints; assigns speakers to words and segments; writes `diarization.json` plus the final `transcript.final.json` (a serialised `domain.Transcript`). **Fallback:** if diarization fails (no token, model not accepted, error) or the user disabled it, produce a single-speaker transcript with `diarized=false` and a visible warning. The job does not fail.
   - Progress: report a fraction per stage, using chunk callbacks where WhisperX exposes them, otherwise coarse steps, and feed the ETA from Phase 05's estimator.
4. **OOM handling (spec §3, R5):** catch CUDA OOM (`torch.cuda.OutOfMemoryError` and CTranslate2's equivalent messages). Free memory, then **retry once automatically** with a reduced batch_size and compute_type `int8_float16`. If it fails again, mark the stage `failed` with code `E_OOM` and a hint suggesting a smaller model (from Phase 05). The UI offers "retry with <smaller model>", which calls the resume API with overrides.
5. **VRAM release (R5):** after the last GPU stage, unload all models (`del`, `gc.collect()`, `torch.cuda.empty_cache()`), and log VRAM before and after at DEBUG. Add a pre-transcription hook that asks a local Ollama to unload its models (`POST /api/generate` with `keep_alive: 0` for loaded models, listed via `/api/ps`), only when the configured LLM backend is local Ollama on the same host.
6. **Register the stages** in the pipeline when the `ml` extra is installed; otherwise the doctor and UI say "Transcription engine not installed" with install instructions.
7. **Test audio (Q4, decided):** add a short (≤ 60 s) CC-licensed two-speaker English clip as `tests/fixtures/audio/<name>.fixture.<ext>`. Also ask Nick for his shareable recordings. Trim 1–2 short excerpts (≤ 60 s, ≤ 2 MB, Opus or FLAC) into further `*.fixture.*` files, and **confirm with Nick that every voice in each excerpt agreed to publication** before committing it. Record the source, licence and consent for each fixture in `tests/fixtures/README.md`. Full-length recordings stay out of git; tests read them from `MM3_PRIVATE_TEST_AUDIO`.

## Tests
Unit tests with mocked whisperx and pyannote modules (stage logic, OOM retry path, diarization fallback, language gate, artifact writing, resume skipping completed stages). `gpu` + `models` integration test: the fixture clip on the reference machine produces at least 2 speakers and sensible text; record the RTF. A `slow` test transcribes a 10-minute clip if one is available.

## Acceptance criteria
- On the reference machine (RTX 2070 Max-Q 8 GB) the fixture runs end to end with diarization, using the `vram8` defaults, with no OOM. Record the measured RTF in the Phase Log and in `hardware/recommendations.yaml` (marked `measured`).
- With no HF token, the job completes with a non-diarized transcript and a clear warning.
- A simulated OOM triggers exactly one automatic retry.

## Phase-specific docs
`docs/user-guide/transcription.md` (models, accuracy and speed trade-offs, diarization setup with the HF token, offline mode, OOM guidance); README prerequisites (NVIDIA driver, CUDA notes, disk space for models); THIRD_PARTY_NOTICES (all ML deps and model licences); SECURITY and PRIVACY (HF token; model downloads are the only network calls); ADR(s) for pins and the diarization model. If an OS-level CUDA or cuDNN package is installed, document it in OSMods. Then the standard close-out checklist.
