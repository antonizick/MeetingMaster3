# Phase 15f: Right-size the LLM context window and re-measure performance

**Model:** Opus 5.5 (`/model claude-opus-5-5`) · **Depends on:** 15e · **Branch:** `phase-15f-context-right-sizing` · **Worktree:** `../MeetingMaster3-phase-15f`

Inserted with `/phase-add` after 15e (ADR-0030, ADR-0034). While closing Phase 15e we found that on the 8 GB laptop
part of `qwen3:8b` always runs on the CPU (Ollama fills the free VRAM and silently puts the rest on the CPU), and that
MeetingMaster3 asks Ollama for more context than its prompts can use in map-reduce mode, which makes the spill worse.
The same day Nick enabled flash attention and an 8-bit KV cache on the host Ollama (a host change, already done and
documented). This phase fixes the app side, re-measures, recalibrates the time estimates and documents the Ollama
settings for other users. It touches the generator's budgeting and docs only, so it **can run in parallel with 15d**.

## Read first
- `CLAUDE.md`, `prompts/MM3_shared-instructions.md`, `docs/MM3_SPECIFICATION.md` §15 (R5 VRAM hand-off, R6 context handling,
  R17 performance, R29 Default Notes).
- The Phase 15, 15a and 15e Phase Log entries (measurements, the 15e follow-up about `num_ctx`).
- ADR-0016 (map-reduce), ADR-0017 (one `num_ctx` per note so a local Ollama never reloads the model), ADR-0039
  (Default Notes, `params.detail: high`, its 3 000-token topic reserve and 3 500-token map output).
- `docs/PERFORMANCE.md`, `docs/user-guide/hardware.md`, `src/meetingmaster3/hardware/recommendations.yaml`.
- Nick's vault note `04 Resources/OSMods/Ollama VRAM Tuning.md` (the host settings and the before/after numbers).

## Nick's request (verbatim intent, 2026-10-14)
"Up to this point, the performance for this system has been absolutely fantastic and we did not seem to be exceeding
the 8GB of VRAM including both the Ollama model as well as the context window. You mentioned that the app asks Ollama
for more memory than it uses... Is that to say it's asking for unnecessary memory in a wasteful manner? Are there any
adjustments we can make that would keep us within the 8 gigabytes of VRAM?" After the measurements below he approved
the host change and asked to "plan item 2": fix the double-counted context in the app, then re-measure.

## Decisions already made
- Host Ollama: `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` via a systemd drop-in on Prometheus's
  `prometheus-ollama.service` (OSMods "Ollama VRAM Tuning", 2026-10-14). **The app must never change the host Ollama**;
  it only documents recommended settings.
- One `num_ctx` per note stays (ADR-0017): every call of a note, map and reduce, uses the same value.

## Goal
Every generation call asks Ollama for the context it really needs plus a measured safety margin, never for the output
reserve twice; the time estimates and docs reflect the tuned 8 GB machine; other users learn which Ollama settings help
on small GPUs. No quality regression in the eval.

## What exists (verified 2026-10-14; re-check before relying on it)
- `src/meetingmaster3/templates/generator.py:NoteGenerator.prepare`
  - full mode: `num_ctx = _num_ctx(window, prompt_tokens + reserve)` (correct: prompt plus the largest output).
  - map-reduce: `num_ctx = _num_ctx(window, usable_tokens(window) + reserve)`. But the map prompt is sized by
    `map_budget(window, detail)` = usable − prompt overhead − map output − cue room, and the reduce notes by
    `room = usable − system − tail − reserve`, so every call already fits in `usable_tokens(window)` (70 % of the
    window, `llm/budget.py:BUDGET_FRACTION`). The reserve is counted twice. With `generation.max_context` 16 384:
    Default Notes (reserve 3 000, map output 3 500) asks for 15 360; Executive Summary (reserve 1 000) for 13 312.
  - `_num_ctx(window, need)` rounds up to 1 024 and floors at `MIN_NUM_CTX` 4 096, capped by the window.
- `src/meetingmaster3/llm/ollama.py:OllamaBackend._num_ctx` uses `req.num_ctx` when given (the generator always gives
  it), else estimates. `llm/budget.py:estimate_tokens` is 4 characters per token, never measured against
  qwen3's tokenizer. **The safety margin has to be inside `num_ctx`**: if `num_ctx` is too small, Ollama silently
  drops the start of the prompt. Today the double count accidentally hides an underestimate.
- Tests: `tests/unit/templates/test_generator.py:test_full_mode_generates_every_section_in_order` asserts a single
  `num_ctx` per note; `tests/unit/llm/test_ollama.py` covers the backend's sizing. No test pins the map-reduce value.
- Measured on the reference laptop (desktop holds ~1.4 GB of VRAM; Ollama 0.33.3; qwen3:8b Q4_K_M; same 9.5k-token
  prompt, 300-token answer):

  | Ollama settings | ctx 12 288: CPU share, writing | ctx 15 360: CPU share, writing |
  |---|---|---|
  | defaults (before) | 25 %, 6.8 tok/s | 29 %, 5.6 tok/s |
  | FA + q8_0, test instance (normal priority) | 16 %, 16.7 tok/s | 18 %, 9.8 tok/s |
  | FA + q8_0, live service (`Nice=5`, idle I/O, set by Prometheus) | 16 %, 10-12 tok/s | 18 %, 9.3 tok/s |

  Even at 8 192 the default spilled 18 % (11 % after tuning): qwen3:8b's weights (~5.2 GB) plus buffers do not fully
  fit next to the desktop. Phase 15's "Ollama peaks at 5.5-5.8 GB" was most likely the GPU part only
  (`nvidia-smi` per process), not the whole model.
- 15e timings (before tuning, `docs/PERFORMANCE.md`): Default Notes 497 s (31 min), 780 s (59 min), 927 s (113 min);
  Executive Summary 167 s / 318 s. `recommendations.yaml` vram8 `notes_rtf: [3.5, 7]` (Default Notes).
- `scripts/measure_performance.py` runs whole jobs on private audio (`MM3_PRIVATE_TEST_AUDIO`), with `--template`.
  For notes-only timing from existing meetings, use a private script under
  `~/.local/share/meetingmaster3/private-eval-15f/` (generate from the companion transcript, as in 15e), never in
  the repo, and delete it at close-out.
- `docker/compose.yaml` has an optional bundled Ollama (`--profile ollama`, image `ollama/ollama:latest`) with no
  environment settings; `docs/user-guide/install-docker.md` and `docs/user-guide/hardware.md` say nothing about
  flash attention or the KV cache type.

## Tasks
1. **Measure the token estimate.** On Nick's three meetings (private) and the synthetic eval meetings, compare
   `estimate_tokens(prompt)` with Ollama's `prompt_eval_count` for full-mode, map and reduce calls. Record the ratio
   (mean and worst case) in the ADR. This sets the safety margin; do not guess it.
2. **Fix `num_ctx` in `NoteGenerator.prepare`** so it covers the largest real call of the note: in full mode as today;
   in map-reduce, max(largest map call = map prompt + map output, largest reduce call = system + notes + tail + reserve),
   using the actual sizes where known rather than the budget formula, times the measured margin (default if the
   measurement is close to 4 chars/token: 10 %), rounded up to 1 024 and capped by the window. Keep one value per note
   (ADR-0017). Keep `regenerate_section` and `write_sections` on the same path. Leave the 70 % map-reduce trigger alone.
3. **Tests:** map-reduce `num_ctx` for a standard and a `detail: high` template is below `usable + reserve` and at least
   the largest call's estimated size plus the margin; full mode unchanged; a single `num_ctx` per note still holds;
   an over-long reduce input can never exceed the chosen `num_ctx`.
4. **Re-measure** on the reference machine with the tuned host Ollama: Default Notes and Executive Summary on Nick's
   three meetings (notes only, plus one whole job with `scripts/measure_performance.py` if Nick gives audio paths),
   recording `ollama ps` (size, CPU/GPU split) per run. Note that Prometheus runs Ollama at `Nice=5`; say so next to
   the numbers.
5. **Recalibrate:** `notes_rtf` in `hardware/recommendations.yaml` (comment with the measurements), the hardware test
   that pins it, `docs/PERFORMANCE.md` (new section; keep history), README and `docs/user-guide/hardware.md` job times.
6. **Document the Ollama settings for small GPUs** in `docs/user-guide/hardware.md` (and a pointer from
   `configuration.md` / `install-docker.md`): what `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` do, how
   to set them for a systemd service (drop-in) and in Docker, how to check the split with `ollama ps`, the measured
   gain, and that the app never changes them. Add both variables to the bundled `ollama` service in
   `docker/compose.yaml` (and `compose.cpu.yaml` only if they apply to CPU; check Ollama's docs).
7. **Eval:** rerun the full generation eval (all 23 templates, plus `--long`) with `qwen3:8b` and compare with
   `tests/eval/baseline.json` (`python -m tests.eval.baseline`). `num_ctx` affects every template's map-reduce
   calls. No regression; update the baseline if quality is equal (state the run date and Ollama settings).

## Out of scope
- Changing the host Ollama or Prometheus's unit (done; Nick's system).
- Changing `generation.max_context`, the 70 % trigger, the models or the templates' prompts.
- Pinning the bundled Ollama image (note it for Phase 16's supply-chain check).

## Tests
- `uv run pytest` (with the new generator tests), `ruff check`, `ruff format --check`, `mypy src`; `mypy src tests`
  error count no higher than `main`.
- `MM3_EVAL_MODEL=qwen3:8b uv run pytest tests/eval -s` and the baseline comparison.

## Acceptance criteria
- On a 59-minute meeting with Default Notes, Ollama is asked for about 12-13k context instead of 15 360 (shown by
  `ollama ps` CONTEXT) and no prompt is truncated (Ollama's `prompt_eval_count` ≤ `num_ctx` on every call, logged
  during the measurement).
- Measured times before/after are in `docs/PERFORMANCE.md`; the pre-job estimate matches the new measurements.
- The full eval shows no regression against the baseline.
- The user guide explains the recommended Ollama settings, and the bundled Docker Ollama uses them.

## Phase-specific docs
- ADR (next free number): the token-estimate measurement, the margin, the new `num_ctx` rule, and the measurements.
- `docs/PERFORMANCE.md`, `docs/user-guide/hardware.md`, `docs/user-guide/install-docker.md`, README, `CHANGELOG.md`,
  `docs/dev-guide/template-format.md` §7/§9 if they describe `num_ctx`.
- Spec §15: amend R6 only if the rule for sizing the context changes materially (next free R number).

Then the standard close-out checklist.
