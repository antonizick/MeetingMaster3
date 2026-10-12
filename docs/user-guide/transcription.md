# Transcription and speaker diarization

MeetingMaster3 turns a recording into a speaker-attributed transcript on your own machine with
[WhisperX](https://github.com/m-bain/whisperX): faster-whisper transcribes, wav2vec2 aligns every word
to the audio, and pyannote.audio works out who spoke when. After the models are downloaded, nothing
about your recordings leaves the computer.

## 1. Install the transcription engine
The engine is an optional extra because it is large (about 6 GB of Python packages, mostly PyTorch
and NVIDIA CUDA libraries).

```bash
uv sync --extra ml
uv run mm3 doctor          # "Transcription engine: ... installed"
```

**GPU requirements.** An NVIDIA GPU with a driver that supports CUDA 12.8 (driver 570 or newer; the
CUDA and cuDNN libraries come with the Python packages, so you do not install the CUDA toolkit).
Check with `nvidia-smi`. Without a usable GPU, transcription runs on the CPU (much slower; see
below). AMD and Apple GPUs are not supported. ffmpeg is required as for the rest of the app.

**Disk space.** About 6 GB for the packages, plus the models: large-v3-turbo 1.6 GB, the English
alignment model 360 MB, the diarization pipeline 30 MB (medium 1.5 GB, small 480 MB, large-v3 3 GB).

## 2. Set up speaker diarization (one time)
The diarization model, [`pyannote/speaker-diarization-community-1`](https://huggingface.co/pyannote/speaker-diarization-community-1)
(CC BY 4.0), is free but "gated": Hugging Face needs you to accept its terms before downloading.

1. Create a free account at <https://huggingface.co> and sign in.
2. Open <https://huggingface.co/pyannote/speaker-diarization-community-1> and accept the conditions.
3. Create a **read** token at <https://huggingface.co/settings/tokens>.
4. Put the token in Settings (Phase 12), or in `~/.config/meetingmaster3/config.yaml`
   (the file must stay private, mode `0600`):
   ```yaml
   secrets:
     hf_token: "hf_..."
   ```
   or set the environment variable `MM3_SECRETS__HF_TOKEN`.
5. Download the models: `uv run mm3 models download`.

The token is only used to download the model. It is never logged, never shown in full by the app
and never written to your vault. Once the model is downloaded, diarization works without the token.

**Without a token**, transcription still works: the transcript simply has no speaker labels, and
the job shows the warning "Speakers were not separated: …" with these instructions.

## 3. Download models ahead of time (optional)
Models download automatically on first use. To fetch them in advance (for example before going
offline):

```bash
uv run mm3 models download                    # recommended whisper model + English alignment + diarization
uv run mm3 models download --whisper medium   # another whisper model
uv run mm3 models download --align de         # the alignment model for German
uv run mm3 models status                      # what is in the cache
```

Models live in `~/.cache/meetingmaster3/models` (`MM3_MODELS_DIR` overrides it). `HF_HOME` and
`TORCH_HOME` point there while the app runs, so they do not mix with other tools' caches.

## 4. Offline mode
Once models are cached, MeetingMaster3 loads them from disk without contacting Hugging Face at all
(verified: a full diarized job makes no network connections other than to a local Ollama). To make
sure nothing is ever downloaded, set `transcription.offline: true` (or `HF_HUB_OFFLINE=1`); a missing
model then fails with "not downloaded" instead of fetching it.

**No telemetry.** pyannote.audio 4 sends usage metrics to `otel.pyannote.ai` by default. MeetingMaster3
always turns this off (`PYANNOTE_METRICS_ENABLED=false`), together with Hugging Face's telemetry.

## Choosing a model: accuracy and speed
The app picks a model for your hardware (`uv run mm3 doctor` shows it). You can override it in
`transcription.model` or per job.

| Model | VRAM (int8_float16) | Accuracy | Notes |
|---|---|---|---|
| large-v3 | about 6.5 GB | best | Needs 10+ GB for float16; tight on 8 GB |
| large-v3-turbo | about 4 GB | near large-v3 for English | **Default on 8 GB**; much faster than large-v3 |
| medium | about 3 GB | good | The "retry with a smaller model" choice after out-of-memory |
| small | about 1.5 GB | fair | Default on the CPU |

**Measured on the reference laptop** (RTX 2070 Max-Q, 8 GB, large-v3-turbo, int8_float16, batch 8,
diarization on; Phase 15): 10 minutes took 47 s, 31 minutes 139 s and 72 minutes 275 s, about
**13-16x real time**, so **a 60-minute meeting takes about 4-5 minutes**. Diarization takes about half
of that time. Peak GPU memory was 2.8 GB (3.3 GB with `medium`, which was not faster). Short clips are
slower per minute because loading the models takes a few seconds. Raw numbers:
[PERFORMANCE.md](../PERFORMANCE.md).

On the CPU expect roughly real time or slower with `small`; consider turning diarization off.

## Non-English recordings
The app checks the language in the first 30 seconds. English goes straight through. For any other
language the job pauses and asks:

- **Proceed**: transcribe in the detected language (or a language you choose, for example English).
  The note templates are written for English, so note quality may be lower.
- **Abort**: cancel the job. Resuming it asks again.

To skip the question, set `transcription.on_non_english` to `proceed` or `abort`, or force a
language with `transcription.language: en`.

## When the GPU runs out of memory
Another program using the GPU (a game, a browser with hardware acceleration, a second model in
Ollama) can leave too little memory. MeetingMaster3 then:

1. frees memory and **retries once automatically** with half the batch size and `int8_float16`;
2. if that also fails, stops the job with "The GPU ran out of memory" and offers **Retry with a
   smaller model** (for example `medium`), which resumes the job from the transcription step.

Before transcribing, the app also asks a local Ollama to unload its models so they do not compete
for VRAM (turn off with `transcription.unload_ollama: false`). If alignment or diarization still
runs out of memory after one retry, the job finishes without word timings or speakers and says so.

## Warnings you may see
| Warning | Meaning |
|---|---|
| Speakers were not separated: … | No token, model terms not accepted, or diarization failed. The transcript has no speaker labels. Follow the hint, then re-run the job. |
| Word-level timestamps are unavailable … | No alignment model for this language, or alignment failed. Segment timestamps are kept. |
| Ran out of GPU memory; retrying … | The automatic retry described above. |
| The recording sounds like … | The language check; see above. |

Related: [hardware](hardware.md), [configuration](configuration.md).
