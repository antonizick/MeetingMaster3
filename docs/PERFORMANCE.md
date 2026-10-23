# Performance

Measured in Phase 15 (2026-10-12) on the reference machine. These numbers replace the estimates for
the 8 GB profile (`src/meetingmaster3/hardware/recommendations.yaml`, `status: measured`), the README
hardware table and the time shown before a job starts (spec R17). Other profiles are still
estimates. Your hardware, recordings and models will differ: treat these as a guide, not a promise.

## Summary (8 GB laptop GPU)
| What | 10 min | 31 min | 72 min |
|---|---|---|---|
| Transcribe + align + diarize, `large-v3-turbo` | 47 s (12.8x) | 139 s (13.5x) | 275 s (15.8x) |
| Transcribe + align + diarize, `medium` | 49 s (12.2x) | 138 s (13.6x) | 295 s (14.7x) |
| Notes, `qwen3:8b`, Executive Summary | 22-30 s | 94-111 s | 210-280 s (map-reduce) |
| **Upload to note in the vault (whole job)** | **79-85 s** | **252-271 s** | **552-600 s** |

So on this laptop **a 60-minute meeting is transcribed with speakers in about 4-5 minutes**, and the
complete job, including notes written by a local 8B model, takes **about 8-10 minutes** (8-9 before Summary Detailed). With a
cloud LLM the notes take seconds instead (not measured here; that depends on the provider).

- `medium` is **not faster** than `large-v3-turbo` on this GPU (turbo has 4 decoder layers) and
  uses slightly more memory; keep turbo as the default and `medium` as the out-of-memory fallback.
- **Diarization is about half** of the transcription time and runs at a constant ~28x real time.
- **Peak GPU memory of the app** is 2.8 GB with turbo and 3.3 GB with medium; Ollama with qwen3:8b
  peaks at 5.5-5.8 GB. They never share the GPU: the app asks Ollama to unload before transcription
  and frees Whisper and pyannote before generation (spec R5). The whole GPU never exceeded 6.8 GB.
- **Peak RAM** of the app is 2.5-3.1 GB during transcription (models in memory); Ollama's runner
  holds about 5.4 GB of RAM while loaded.

Phase 15a added a **Summary Detailed** section to every template (one more model call per note).
Measured on the owner's two meetings with `qwen3:8b`, same machine, template without and with the
section: 72 minutes (`action-focused`, map-reduce) 259 s → 289 s (+30 s, +12 %); 31 minutes
(`detailed-meeting-minutes`, full context) 185 s → 262 s (+77 s, +42 %). The pre-job estimate now
uses notes at 12-18× real time (was 15-21×). Adding the section to an *existing* note ("Update older
notes") re-reads the transcript: 66 s for the 31-minute meeting and 317 s for the 72-minute one (its
map step runs again; caching the map notes is on the roadmap). Updating both notes on the real
vault took 5 min 14 s in all. The final eval passes 71/71 notes (one note re-run after a 3/4
action-recall miss that did not repeat) at 50 s per note on average (max 93 s), against 33 s
before; every Summary Detailed has 2-3 paragraphs and 277-517 words (mean 334). The long meeting
still completes through map-reduce (630 s): decisions 6/6, actions 15/16, questions 3/5.

**Default Notes** (Phase 15e, R29), the default template since then, writes much longer notes (about
2 000 words, of which 800-1 000 are the numbered topics) and, for meetings over about 40 minutes,
uses the high-detail map step (`params.detail: high`). Measured with `qwen3:8b` on the owner's three
meetings, same machine, 2026-10-14, with Ollama holding a 13-15k context (7.3-7.7 GB, about 27 %
of the model on the CPU next to the desktop's own GPU use):

| Meeting | Mode | Default Notes | Executive Summary (same day) |
|---|---|---|---|
| 31 min, 4 people | full | 497 s (3.7×) | 167 s (11×) |
| 59 min, 2 people | map-reduce, 2 parts | 780 s (4.5×) | 318 s (11×) |
| 113 min, 2 people | map-reduce, 3 parts | 927 s (7.3×) | not run |

So Default Notes takes **about 2.5-3 times as long** as Executive Summary: on this laptop a 60-minute
meeting needs about 13 minutes for the notes, and the whole job about 17-18 minutes. The pre-job
estimate (`notes_rtf` in `recommendations.yaml`) then used 3.5-7× real time (10-20× since Phase 15f), since it describes the
default; other templates finish sooner than it says. Pick a shorter template (Executive Summary, Key
Takeaways) on New meeting when speed matters, or a cloud model.

## Phase 15f: tuned Ollama and right-sized context (2026-10-15)
Two changes, measured separately on the same laptop with `qwen3:8b`, notes only (the owner's three
meetings, generated from their companion transcripts; private, only numbers recorded):

1. **Host Ollama settings** (the owner's machine, not the app): flash attention and an 8-bit KV cache
   (`OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`), recommended for small GPUs in
   [`user-guide/hardware.md`](user-guide/hardware.md#ollama-settings-for-small-gpus-recommended-on-8-gb).
2. **App: `num_ctx` right-sized** (ADR-0043). Long meetings asked Ollama for 15 360 tokens of context
   with Default Notes; now 13 312 (the largest real call plus a measured 10 % margin).

| Meeting | Mode | Default Notes: 15e (default Ollama) | tuned Ollama, old code | tuned Ollama, new code | Executive Summary: 15e | old code | new code |
|---|---|---|---|---|---|---|---|
| 31 min | full | 497 s | 160 s (12 288; 8 % CPU) | 142 s (12 288; 100 % GPU) | 167 s | 70 s | 65 s |
| 59 min | map-reduce, 2 parts | 780 s | 339-367 s (15 360; 11-13 % CPU) | 204-229 s (13 312; 100 % GPU) | 318 s | 128 s | 101 s |
| 113 min | map-reduce, 3 parts | 927 s | 616 s (15 360; 13 % CPU) | 293 s (13 312; 100 % GPU) | not run | 150 s | 126 s |

In brackets: the context Ollama was given (`ollama ps` CONTEXT) and the model's CPU/GPU split. **Read
with care:** the desktop's own GPU use changes over time, and it moved during these runs. Executive
Summary asked for the same 13 312 in both code versions, yet went from 8 % on the CPU to 100 % on the
GPU and 21 % faster. The fair comparison of the app change alone is the **paired run** (59 minutes,
Default Notes, back to back at 08:28-08:38): old code 339 s with 11 % of the model on the CPU, new code
229 s with all of it on the GPU, **32 % faster**. The host settings alone (15e vs tuned, old code)
made Default Notes 2.1-3.1× faster.

So on this laptop, with the recommended Ollama settings, **Default Notes for a 60-minute meeting takes
about 3.5-4 minutes** and Executive Summary under 2; a whole job is about 8-9 and 6-7 minutes
(transcription unchanged, 4-5 minutes per hour; whole jobs were not re-run). The pre-job estimate now
uses 10-20× real time for the notes (was 3.5-7×). With Ollama's defaults expect about twice as long.

- Ollama 0.33.3, service at `Nice=5` with idle I/O priority (set by another app on the reference
  machine; it slows the part of a model that runs on the CPU). GPU memory of the loaded model
  (`ollama ps` SIZE): 6.0 GB at 13 312, 6.6 GB at 15 360.
- **Token estimate:** 108 calls compared `estimate_tokens` (4 characters per token) with Ollama's
  `prompt_eval_count`: mean 1.005; calls of 6 000+ estimated tokens 0.97-1.011; merged map-reduce
  notes up to 1.115 (now counted at 1.15). No call had prompt plus output above its `num_ctx`.
- **Quality:** the full eval (75 notes, 2026-10-15, flash attention + q8_0 cache, new code) passes
  72/75, mean 49 s per note (max 102 s). Against the Phase 15 baseline (default Ollama) five notes
  found one action or question fewer. Re-runs: two were sampling noise (passed on re-run); three
  (`decision-log` and `agile-standup` 1/2 questions, `retrospective` 3-4/4 actions) behave the same
  with the **old code** on the tuned Ollama, so they come with the host settings, not the app change.
  The baseline was updated to this run. The long all-hands (map-reduce, window 8 192) still completes:
  decisions 5/6, actions 15/16, questions 3/5 (Phase 15a: 6/6, 15/16, 3/5).

## Search index (Phase 15i, 2026-10-22 14:56 CDT)
Measured on the RTX 2070 Max-Q (8 GB) with Ollama 0.40.6 and `nomic-embed-text` (768 dimensions), default
passage size (350 tokens, 50 overlap), on a private copy of Nick's vault: **13 meetings** (13 notes, 13 companion
transcripts, 123 Markdown files in the vault) → **467 passages**. Only these aggregate numbers are recorded.

| What | Result |
|---|---|
| Full index, cold (Ollama loads the embedding model) | 13.6 s (12.6 s of it embedding) |
| Full rebuild, model loaded | 10.6 s (about 44 passages/s) |
| Update after saving one note (one section changed) | 0.07 s, 1 passage re-embedded |
| Update with nothing changed | 0.017 s |
| `search.db` size | 4.0 MB (about 9 KB per passage: text, FTS index, 3 KB vector); up to 10.8 MB right after a full build, until SQLite folds its write-ahead log (`-wal`) back in |
| Word search (FTS5, BM25) | 2 ms median |
| Embedding the query (Ollama, model warm) | about 60 ms |
| Vector search, brute force over 467 passages | 10 ms (`math.sumprod` over cached `array('f')`); synthetic 20 000 passages: 340 ms |
| Hybrid search end to end | about 120 ms median |

**Relevance check** (private: 17 questions written from the meeting titles, 10 everyday and 7 deliberately phrased
without the notes' words, e.g. "battery-powered automobiles" for a talk about electric vehicles; the expected
meetings judged by hand):

| | Words only | Hybrid (meaning + words) |
|---|---|---|
| A right meeting ranked first | 13 of 17 | **16 of 17** |
| Recall of the expected meetings in the top 3 | 0.98 | 0.98 |
| Meetings returned per question (fewer = less noise) | 6.7 | 5.8 |

With only 13 long meetings, an OR word search touches most meetings (transcripts contain many everyday words), so
recall saturates for both; the difference is in **ranking**: meaning search puts the right meeting first more often
and returns fewer unrelated ones. Hybrid was clearly better on the paraphrased set (7 of 7 first vs 5 of 7), so the
defaults were kept and `bge-m3` / `qwen3-embedding` were not tried (ADR-0050). On the synthetic corpus
(`tests/fixtures/search_vault/`) the three meetings about one topic in three wordings rank 1-3 with
`nomic-embed-text`, while words alone find one or two (`tests/integration/test_search_real_embedder.py`).

GPU: embedding holds the GPU only between jobs, one batch of 32 passages (about 0.7 s) at a time, and Ollama keeps
the 274 MB model for 30 s after the last batch.

## Ask-AI agent (Phase 15j, 2026-10-22 16:37 CDT)
Measured with `tests/eval/ask_eval.py` on the synthetic eight-meeting corpus (`tests/ask_corpus.py`: one topic,
money spent beyond the plan, in three meetings in different words with different people and stated roles, plus
decoys; six questions incl. one with no answer), index embedded with the local `nomic-embed-text`. One question =
1 plan call + one read call per candidate meeting + (when fewer than two are relevant) one follow-up round + 1
answer call.

| Backend · model | Recall | Precision | Count right | Rows match files | People named | Links valid | Time per question | Cost per question |
|---|---|---|---|---|---|---|---|---|
| Ollama `qwen3:8b` (RTX 2070 Max-Q 8 GB, `num_ctx` 10 240) | 1.00 | 0.96 | 5/6 | 6/6 | 6/6 | 6/6 | 55 s mean (24-117 s; an earlier run 39 s), 3-30 s per meeting read | free |
| Bedrock `us.anthropic.claude-haiku-5-5` | 1.00 | 0.96 | 5/6 | 6/6 | 6/6 | 6/6 | 13 s mean (10-16 s), about 2 s per meeting read | USD 0.0009-0.0019 (USD 0.008 for all six) |
| OpenRouter `anthropic/claude-haiku-5.5` | 1.00 | 0.96 | 5/6 | 6/6 | 6/6 | 6/6 | 12.5 s mean (8-16 s) | USD 0.0007-0.0017 (USD 0.007 for all six) |

- The one miss is the same on every backend: the decoy *Team Offsite Planning* ("the plan fits the offsite budget")
  was judged relevant to one of the two overspending questions, so the count was 4 instead of 3. The answer note
  marks such meetings *briefly* when the model says "partly".
- Tokens per question: 5-8 k in and 0.4-2.2 k out with Haiku (Bedrock and OpenRouter agree); Ollama reports only
  the tokens it did not have cached, so its counts are lower. Reads run one after another (one GPU), so the time
  grows with the number of candidate meetings: with `ask.max_meetings` = 25 a local question can take 5-10 minutes.
- **Nick's vault** (private copy, deleted after the check; 13 meetings): "How many times have we discussed the SOC
  manager role? Who was principally in those discussions and what was their role? Also create a table…" with
  local `qwen3:8b`: 4 searches, 9 meetings read, 4 relevant (the three SOC-role meetings, two in depth and one
  briefly, plus one team meeting marked briefly), every table row's date and attendees identical to the notes'
  frontmatter, 3 min 24 s, 35 k tokens in, 2.1 k out. Before the "by context" wording in the read prompt the
  follow-on interview (which says "the role", not "SOC manager") was missed; the synthetic scores did not change.
- Retrieval found every expected meeting on every backend (recall 1.0) after a fix: the question's "decide" was
  taken for "December", so the plan's invented date range hid the launch meeting. Time words are now matched
  strictly, and a date range the model chose that finds nothing is dropped (ADR-0051).

## Raw numbers
Per stage: wall time in seconds (real-time factor in brackets = audio seconds / wall seconds), then
the peak GPU memory of the MeetingMaster3 process, of Ollama, and the app's peak resident memory
(MiB). "Total" is the whole job from upload to the note written in the vault. Timestamps have
one-second resolution.

| Recording | Model | ingest | transcribe | align | diarize | generate | Total |
|---|---|---|---|---|---|---|---|
| 10 min | large-v3-turbo | 1 | 17 (35x) | 9 (67x) | 21 (29x) | 30 | 84.8 s (7.1x) |
| 10 min | medium | 1 | 19 (32x) | 8 (75x) | 22 (27x) | 22 | 78.5 s (7.6x) |
| 31 min | large-v3-turbo | 1 | 41 (46x) | 30 (63x) | 68 (28x) | 111 | 270.6 s (6.9x) |
| 31 min | medium | 1 | 48 (39x) | 25 (75x) | 65 (29x) | 94 | 251.7 s (7.5x) |
| 72 min | large-v3-turbo | 2 | 69 (63x) | 55 (79x) | 151 (29x) | 280 | 600.2 s (7.2x) |
| 72 min | medium | 2 | 90 (48x) | 55 (79x) | 150 (29x) | 210 | 551.8 s (7.9x) |

| Recording | Model | App VRAM: transcribe / align / diarize | Ollama VRAM (generate) | App RSS peak |
|---|---|---|---|---|
| 10 min | large-v3-turbo | 2720 / 2240 / 2846 | 5460 | 2959 |
| 10 min | medium | 3008 / 2240 / 2846 | 5460 | 2949 |
| 31 min | large-v3-turbo | 2720 / 1964 / 2846 | 5574 | 2689 |
| 31 min | medium | 3264 / 2336 / 2846 | 5574 | 2701 |
| 72 min | large-v3-turbo | 2720 / 2622 / 2848 | 5492 | 3068 |
| 72 min | medium | 3200 / 3008 / 2848 | 5816 | 3104 |

Generation time varies with how much was said and with the template; map-reduce (long meetings)
makes more calls. The eval below gives per-template times.

## Method
- **Machine:** laptop with an NVIDIA GeForce RTX 2070 with Max-Q Design (8 GB, driver 610.57),
  Intel Core i7-9750H, 32 GB RAM, Omarchy (Arch) Linux. Native install (`uv`), not Docker.
- **Software:** MeetingMaster3 at the Phase 15 branch; WhisperX 3.8.6, faster-whisper 1.2.1,
  CTranslate2 4.8.2, torch 2.8.0+cu128, pyannote.audio 4.0.7 (`speaker-diarization-community-1`);
  Ollama 0.33.3 with `qwen3:8b` (Q4_K_M). Default `vram8` settings: `int8_float16`, batch 8,
  diarization on, models loaded and freed per stage.
- **Recordings:** the owner's own meetings (private, used locally via `MM3_PRIVATE_TEST_AUDIO`,
  never committed; only numbers were recorded): a 31-minute interview, a 72-minute working meeting
  and the first 10 minutes of the latter. English, 2-5 speakers, MP3.
- **Script:** `scripts/measure_performance.py` runs each (recording, model) pair in a fresh process
  with throw-away config, data and vault folders and the shared model cache. It goes through the
  same job pipeline as the web app (`mm3 process` logic, speaker names answered automatically) and
  samples every 500 ms: `nvidia-smi --query-compute-apps` (per-process GPU memory),
  `nvidia-smi --query-gpu=memory.used` (whole GPU) and `/proc/<pid>/status` (RSS of the app and of
  Ollama's processes). Stage times come from the job database.
  ```
  MM3_PRIVATE_TEST_AUDIO=/path/a.mp3:/path/b.mp3 MM3_SECRETS__HF_TOKEN=hf_... \
    uv run --extra ml python scripts/measure_performance.py --models large-v3-turbo,medium \
    --llm-model qwen3:8b --out performance.json
  ```
- Nothing else heavy ran during the transcription measurements.

## Long meetings (spec §3 edge case)
- **3-hour recording, fake pipeline** (`MM3_FAKE_PIPELINE=1`, a 3-hour Opus file): the job ran to
  the vault in 97 s, almost all of it ffmpeg converting 3 hours of audio to 16 kHz WAV and back to
  Opus for retention. The app's memory stayed flat at **50 MiB** (audio is streamed by ffmpeg in a
  subprocess, never loaded into the app), with 91 progress events and no gaps.
- **Real long recordings:** the 72-minute run above scales linearly (RTF rises slightly with length
  because model loading is a fixed cost). By extrapolation, 3 hours takes about 12 minutes to
  transcribe on this GPU; whisper and pyannote process audio in windows, so GPU memory does not grow
  with length (2.85 GB for both 31 and 72 minutes).
- **Review workspace, 3-hour transcript** (synthetic: 1 029 turns, 24 444 words, every word a
  clickable `<span>`): the page is 1.3 MB of HTML and loads in 1.8 s in Chromium, with 29 633 DOM
  nodes and a 6 MB JavaScript heap; scrolling the transcript stayed at 60 frames per second
  (median 16.7 ms per frame, worst 17.6 ms). No "drop word timings" option is needed.
- Generation of long meetings uses map-reduce (`generation.max_context` 16 384 tokens on 8 GB). The
  eval's long-meeting check passes (below). Regenerating one section of a long meeting repeats the
  map step (about the same time as the first generation); caching the map notes is on the roadmap.

## Cloud backends
Measured live on 2026-10-15 (Phase 15g) with the synthetic eval meetings; full tables, quirks and spend in
[`tests/eval/cloud-results.md`](../tests/eval/cloud-results.md). Cloud generation does not use the GPU, and a
note takes about as long as the slowest section call, not the meeting's length.

| Model (Bedrock / OpenRouter) | Eval pass | Time per note | Cost per note | One-hour meeting* |
|---|---|---|---|---|
| Claude Haiku 5.5 | 73/75 / 74/75 | 17-18 s | about $0.003 | about $0.02 |
| Claude Sonnet 5.5 | 71/75 (Bedrock) | 26 s | about $0.07 | about $0.45 |
| Claude Opus 5.5 | 9/27 (style rules; content good) | 42 s | about $0.15 | about $1 |
| Llama 4 Maverick, Qwen3 32B, GLM-5, Mistral Large, GPT-5.5 | 6/7 each (Bedrock) | 9-53 s | not priced | |
| qwen3:8b on the 8 GB laptop (local, for comparison) | baseline | about 1-2 min | free | about 4-5 min |

\* Measured on a real 31-minute meeting with Default Notes (about 80 000 input tokens in total) and doubled.
Long meetings: a 151 800-token meeting is summarised in 2 parts (9 calls, about 40 s) with Haiku 5.5 on either
provider, because Claude is planned at a 200k window (ADR-0044). Reasoning-only models (DeepSeek R1, gpt-oss on
Bedrock) mostly return empty sections and are not recommended.

## Quality baseline
`tests/eval/baseline.json` records the generation eval with `qwen3:8b` on this machine: every
template against every synthetic eval meeting (`tests/eval/meetings/`), plus the long map-reduce
meeting. Re-run and compare after changing prompts, templates or the model:
```
uv run python -m tests.eval.run_eval --model qwen3:8b --json /tmp/results.json
uv run python -m tests.eval.baseline /tmp/results.json        # exits 1 on a regression
```
Results of the Phase 15 run are in the Phase Log of `MM3_IMPLEMENTATION_PLAN.md`.

## Not measured
16 GB and 24 GB profiles, CPU-only transcription speed and Apple hardware (no such machine was
available; the values stay `estimated`). `generation.max_context` above 16 384 tokens needs a GPU
with more memory. Docker adds no measurable overhead in Phase 14's check (150 s clip in about 60 s
in the GPU container).
