"""The WhisperX job stages: ``transcribe`` → ``align`` → ``diarize`` (Phase 06).

* ``transcribe`` (faster-whisper via WhisperX) writes ``transcript.json``. It checks the
  language first and pauses for a decision when the audio is not English (spec §3).
* ``align`` (wav2vec2) writes ``aligned.json`` with word timestamps. If alignment is impossible,
  it warns and keeps the segment timestamps.
* ``diarize`` (pyannote) writes ``diarization.json`` and the final ``transcript.final.json`` (a
  serialised ``domain.Transcript``). If diarization is off or fails, it warns and produces
  a transcript without speaker labels (``diarized=false``). The job does not fail.

Each stage loads its own model and frees it before returning, so at most one model is resident
and nothing is left on the GPU after ``diarize`` (spec R5). CUDA out-of-memory is retried once
automatically with a smaller batch and ``int8_float16`` (spec §3).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from meetingmaster3.config.paths import resolve_paths
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.stage import (
    BaseStage,
    InputRequired,
    JobCancelled,
    Stage,
    StageContext,
    UnavailableStage,
    input_path,
)
from meetingmaster3.transcription import models
from meetingmaster3.transcription.convert import (
    clean_segments,
    split_by_speaker,
    talk_time,
    to_transcript,
)
from meetingmaster3.transcription.engine import Engine, SpeakerTurn, default_engine

if TYPE_CHECKING:
    from meetingmaster3.config.settings import Settings

log = logging.getLogger(__name__)

E_OOM = "E_OOM"
GPU_HALF_TYPES = {"float16", "int8_float16"}

#: Share of the transcription pipeline's time each stage takes, for the initial ETA.
STAGE_SHARE = {"transcribe": 0.6, "align": 0.1, "diarize": 0.3}

LANGUAGE_NAMES = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
    "pt": "Portuguese", "nl": "Dutch", "pl": "Polish", "ru": "Russian", "uk": "Ukrainian",
    "sv": "Swedish", "da": "Danish", "no": "Norwegian", "nn": "Norwegian Nynorsk",
    "fi": "Finnish", "cs": "Czech", "tr": "Turkish", "ar": "Arabic", "he": "Hebrew",
    "hi": "Hindi", "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "vi": "Vietnamese",
    "id": "Indonesian", "el": "Greek", "hu": "Hungarian", "ro": "Romanian", "cy": "Welsh",
}  # fmt: skip


def language_name(code: str | None) -> str:
    if not code:
        return "an unknown language"
    return LANGUAGE_NAMES.get(code, code)


# -- plan ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TranscriptionPlan:
    """The model settings a run uses: job option > setting > hardware recommendation."""

    model: str
    device: str
    compute_type: str
    batch_size: int
    rtf: tuple[float, float]

    def describe(self) -> str:
        return f"{self.model} ({self.compute_type}, batch size {self.batch_size}, {self.device})"


def resolve_plan(settings: Settings, options: dict[str, Any], cuda: bool) -> TranscriptionPlan:
    from meetingmaster3.hardware.detect import get_hardware
    from meetingmaster3.hardware.recommend import profile_recommendation, recommend

    t = settings.transcription
    device = t.device if t.device != "auto" else ("cuda" if cuda else "cpu")
    if device == "cuda" and not cuda:
        device = "cpu"  # asked for CUDA, but torch cannot use it
    rec = recommend(get_hardware(), settings.hardware.profile).transcription
    if device == "cpu" and rec.compute_type in GPU_HALF_TYPES:
        rec = profile_recommendation("cpu")[0]
    model = options.get("transcription_model") or (t.model if t.model != "auto" else rec.model)
    compute_type = options.get("compute_type") or (
        t.compute_type if t.compute_type != "auto" else rec.compute_type
    )
    if device == "cpu" and compute_type in GPU_HALF_TYPES:
        compute_type = "int8"  # CTranslate2 has no float16 kernels on the CPU
    batch_size = int(options.get("batch_size") or t.batch_size or rec.batch_size)
    return TranscriptionPlan(model, device, compute_type, batch_size, (rec.rtf_low, rec.rtf_high))


def initial_eta(ctx: StageContext, plan: TranscriptionPlan) -> float | None:
    """Phase 05's estimate for this stage, used until real progress gives a rate."""
    duration = ctx.job.duration_seconds
    if not duration:
        return None
    from meetingmaster3.hardware.recommend import estimate_seconds

    low, high = estimate_seconds(duration, *plan.rtf)
    return (low + high) / 2 * STAGE_SHARE.get(ctx.stage, 0.3)


def oom_error(stage: str, plan: TranscriptionPlan | None, attempt: int) -> MM3Error:
    smaller = models.smaller_model(plan.model) if plan else None
    what = f" with {plan.describe()}" if plan else ""
    if smaller:
        hint = (
            f"Retry with a smaller model ({smaller}), or close other programs that use the GPU "
            "and resume the job."
        )
        details: dict[str, Any] = {"suggested_overrides": {"transcription_model": smaller}}
    else:
        hint = "Close other programs that use the GPU and resume the job, or use the CPU."
        details = {}
    if plan:
        details["plan"] = asdict(plan)
    details["attempt"] = attempt
    return MM3Error(
        E_OOM,
        f"The GPU ran out of memory during {stage}{what}.",
        hint,
        status_code=507,
        details=details,
    )


# -- base ------------------------------------------------------------------------------------------


EngineFactory = Callable[[], Engine]


class TranscriptionStage(BaseStage):
    """Shared plumbing: engine creation (after the model cache is configured), progress
    callbacks that honour cancellation, and the one-shot OOM retry."""

    uses_gpu = True

    def __init__(self, engine_factory: EngineFactory | None = None) -> None:
        super().__init__()
        self._engine_factory = engine_factory or default_engine

    def engine(self, ctx: StageContext) -> Engine:
        models.configure_model_cache(
            resolve_paths().models_dir, offline=ctx.settings.transcription.offline
        )
        return self._engine_factory()

    @staticmethod
    def progress_fn(
        ctx: StageContext, low: float, high: float, verb: str, eta: float | None = None
    ) -> Callable[[float], None]:
        """A WhisperX progress callback mapping ``0..100`` onto ``low..high``. It checks for
        cancellation on every call, so a cancel stops the work at the next chunk."""
        first = [True]

        def report(percent: float) -> None:
            ctx.check_cancelled()
            pct = min(100.0, max(0.0, float(percent)))
            ctx.progress(
                low + (high - low) * pct / 100, f"{verb} ({pct:.0f}%)", eta if first[0] else None
            )
            first[0] = False

        return report

    def should_retry(self, ctx: StageContext, exc: Exception) -> bool:
        """Retry exactly once after a CUDA out-of-memory error."""
        if not (isinstance(exc, MM3Error) and exc.code == E_OOM) or ctx.attempt > 1:
            return False
        models.free_gpu_memory(f"{self.name} out of memory")
        self.adjust_after_oom(ctx, exc)
        return True

    def adjust_after_oom(self, ctx: StageContext, exc: MM3Error) -> None:
        """Change ``ctx.options`` before the retry (the runner persists them)."""


# -- transcribe ------------------------------------------------------------------------------------


class TranscribeStage(TranscriptionStage):
    name = "transcribe"
    display_name = "Transcribing"

    def run(self, ctx: StageContext) -> Path:
        engine = self.engine(ctx)
        plan = resolve_plan(ctx.settings, ctx.options, engine.cuda_available())
        if ctx.attempt > 1:
            ctx.warn(
                f"Ran out of GPU memory; retrying with batch size {plan.batch_size} and "
                f"{plan.compute_type}."
            )
        forced = ctx.options.get("language") or ctx.settings.transcription.language
        answer = ctx.input()
        if plan.device == "cuda":
            ctx.progress(0.0, "Freeing GPU memory")
            from meetingmaster3.transcription.handoff import release_local_llm

            release_local_llm(ctx.settings, ctx.options.get("backend"))
        ctx.check_cancelled()
        eta = initial_eta(ctx, plan)
        ctx.progress(0.01, f"Loading {plan.describe()}", eta)

        asr: Any = None
        oom: MM3Error | None = None
        try:
            audio = engine.load_audio(ctx.artifacts["ingest"])
            ctx.check_cancelled()
            asr = engine.load_asr(
                plan.model,
                device=plan.device,
                compute_type=plan.compute_type,
                language=forced,
                # A cached model loads without asking Hugging Face for updates, so model
                # downloads stay the only network calls (no per-job lookup).
                local_only=models.offline_mode()
                or models.whisper_cached(resolve_paths().models_dir, plan.model),
            )
            ctx.check_cancelled()
            detected: tuple[str, float] | None = None
            language = forced
            if language is None and plan.model.endswith(".en"):
                language = "en"
            if language is None:
                ctx.progress(0.04, "Detecting the language")
                detected = engine.detect_language(asr, audio)
                language = self.language_gate(ctx, detected, answer)
            result = engine.transcribe(
                asr,
                audio,
                batch_size=plan.batch_size,
                language=language,
                progress=self.progress_fn(ctx, 0.08, 1.0, "Transcribing", eta),
            )
            audio_seconds = engine.audio_seconds(audio)
        except (JobCancelled, InputRequired, MM3Error):
            raise
        except Exception as exc:
            if not models.is_oom(exc):
                raise
            log.warning("Out of GPU memory while transcribing with %s", plan.describe())
            oom = oom_error("transcription", plan, ctx.attempt)
        finally:
            asr = None  # drop the model before freeing (spec R5)
            models.free_gpu_memory("transcribe")
        if oom is not None:
            raise oom
        data = {
            "language": result.get("language") or language,
            "language_detected": detected[0] if detected else None,
            "language_probability": round(detected[1], 4) if detected else None,
            "model": plan.model,
            "compute_type": plan.compute_type,
            "batch_size": plan.batch_size,
            "device": plan.device,
            "duration": round(audio_seconds, 3),
            "segments": clean_segments(result.get("segments", [])),
        }
        return ctx.write_json("transcript.json", data)

    def language_gate(
        self, ctx: StageContext, detected: tuple[str, float], answer: dict[str, Any] | None
    ) -> str:
        """English passes. Otherwise apply the user's answer, or the ``on_non_english`` policy,
        or pause the job with an ``InputRequired("language")`` question."""
        code, probability = detected
        if code == "en":
            return "en"
        name = language_name(code)
        policy = ctx.options.get("on_non_english") or ctx.settings.transcription.on_non_english
        action = answer.get("action") if answer else (None if policy == "ask" else policy)
        if action is None:
            raise InputRequired(
                "language",
                {
                    "detected": code,
                    "language_name": name,
                    "probability": round(probability, 2),
                    "choices": ["proceed", "abort"],
                    "message": (
                        f"This recording sounds like {name} ({probability:.0%} confidence), not "
                        "English. MeetingMaster3's note templates are written for English. "
                        f"Proceed to transcribe it in {name}, or abort."
                    ),
                },
            )
        if action == "abort":
            if answer is not None:
                # Forget the answer so that resuming the job asks again.
                input_path(ctx.job_dir, self.name).unlink(missing_ok=True)
                raise JobCancelled(ctx.job_id)
            raise MM3Error(
                "E_NOT_ENGLISH",
                f"The recording sounds like {name}, and non-English audio is set to abort.",
                'Resume the job with {"overrides": {"on_non_english": "proceed"}}, or change '
                "transcription.on_non_english in Settings.",
                status_code=422,
            )
        language = (answer or {}).get("language") or code
        ctx.warn(
            f"The recording sounds like {name} ({probability:.0%} confidence); it is "
            f"transcribed in {language_name(language)}. Note quality may be lower than for "
            "English."
        )
        return str(language)

    def validate_input(self, data: dict[str, Any]) -> dict[str, Any]:
        action = data.get("action")
        language = data.get("language")
        if action not in {"proceed", "abort"} or (
            language is not None
            and (not isinstance(language, str) or not language.isalpha() or len(language) > 3)
        ):
            raise MM3Error(
                "E_INPUT_INVALID",
                'Expected {"action": "proceed" | "abort"} and optionally "language": "<code>".',
                'Answer "proceed" to transcribe in the detected language (or name another, '
                'e.g. "en"), or "abort".',
                status_code=422,
            )
        return {"action": action, **({"language": language.lower()} if language else {})}

    def adjust_after_oom(self, ctx: StageContext, exc: MM3Error) -> None:
        plan = exc.details.get("plan") or {}
        batch = int(plan.get("batch_size") or ctx.options.get("batch_size") or 8)
        ctx.options["batch_size"] = max(1, batch // 2)
        if plan.get("device", "cuda") == "cuda":
            ctx.options["compute_type"] = "int8_float16"


# -- align -----------------------------------------------------------------------------------------


class AlignStage(TranscriptionStage):
    name = "align"
    display_name = "Aligning"

    def run(self, ctx: StageContext) -> Path:
        data: dict[str, Any] = json.loads(ctx.artifacts["transcribe"].read_text(encoding="utf-8"))
        segments: list[dict[str, Any]] = data.get("segments", [])
        out = {k: v for k, v in data.items() if k != "segments"}
        if not segments:
            return ctx.write_json("aligned.json", {**out, "aligned": False, "segments": []})
        language = str(data.get("language") or "en")
        engine = self.engine(ctx)
        device = str(data.get("device") or ("cuda" if engine.cuda_available() else "cpu"))
        ctx.progress(0.0, f"Loading the {language_name(language)} alignment model")

        aligner: Any = None
        oom: MM3Error | None = None
        reason: str | None = None
        result: dict[str, Any] = {}
        try:
            audio = engine.load_audio(ctx.artifacts["ingest"])
            aligner, metadata = engine.load_aligner(language, device=device)
            ctx.check_cancelled()
            result = engine.align(
                aligner,
                metadata,
                segments,
                audio,
                device=device,
                progress=self.progress_fn(ctx, 0.1, 1.0, "Aligning words"),
            )
        except (JobCancelled, InputRequired):
            raise
        except Exception as exc:
            if models.is_oom(exc) and ctx.attempt == 1:
                oom = oom_error("alignment", None, ctx.attempt)
            else:
                reason = (
                    f"no alignment model for {language_name(language)}"
                    if "No default align-model" in str(exc)
                    else ("out of GPU memory" if models.is_oom(exc) else type(exc).__name__)
                )
                log.warning("Alignment failed (%s)", reason, exc_info=not models.is_oom(exc))
        finally:
            aligner = None
            models.free_gpu_memory("align")
        if oom is not None:
            raise oom
        if reason is not None or not result.get("segments"):
            ctx.warn(
                f"Word-level timestamps are unavailable ({reason or 'nothing aligned'}); the "
                "transcript keeps segment-level timestamps."
            )
            return ctx.write_json("aligned.json", {**out, "aligned": False, "segments": segments})
        return ctx.write_json(
            "aligned.json",
            {**out, "aligned": True, "segments": clean_segments(result["segments"])},
        )


# -- diarize ---------------------------------------------------------------------------------------


class DiarizeStage(TranscriptionStage):
    name = "diarize"
    display_name = "Diarizing"

    def run(self, ctx: StageContext) -> Path:
        meta: dict[str, Any] = json.loads(ctx.artifacts["align"].read_text(encoding="utf-8"))
        segments: list[dict[str, Any]] = meta.get("segments", [])
        settings = ctx.settings.transcription
        wanted = ctx.options.get("diarize")
        wanted = settings.diarize if wanted is None else bool(wanted)
        model_id = settings.diarization_model
        info: dict[str, Any] = {"model": model_id, "status": "ok", "turns": [], "speakers": {}}
        diarized = False
        try:
            if not wanted:
                info["status"] = "disabled"
                ctx.warn("Speaker diarization is turned off; the transcript has no speakers.")
            elif not segments:
                info["status"] = "empty"
            else:
                turns = self.diarize(ctx, model_id, info)
                if turns is not None:
                    engine = self.engine(ctx)
                    assigned = engine.assign_speakers(turns, {"segments": segments})
                    segments = clean_segments(
                        split_by_speaker(assigned.get("segments", segments), meta.get("language"))
                    )
                    info["turns"] = [asdict(t) for t in turns]
                    info["speakers"] = talk_time(turns)
                    diarized = bool(turns)
                    if not turns:
                        info["status"] = "no_speech"
        finally:
            models.free_gpu_memory("all transcription models released")
        transcript = to_transcript(
            segments,
            language=meta.get("language"),
            duration=meta.get("duration") or ctx.job.duration_seconds,
            model=meta.get("model"),
            diarized=diarized,
        )
        ctx.write_json("diarization.json", info)
        return ctx.write_json(
            "transcript.final.json", json.loads(transcript.model_dump_json(exclude_none=False))
        )

    def diarize(
        self, ctx: StageContext, model_id: str, info: dict[str, Any]
    ) -> list[SpeakerTurn] | None:
        """Run pyannote. Returns ``None`` after recording a fallback warning in ``info``."""
        token = models.hf_token(ctx.settings)
        snapshot = models.diarization_snapshot(resolve_paths().models_dir, model_id)
        if token is None and snapshot is None:
            err = models.diarization_access_error(RuntimeError("no token"), token_present=False)
            return self.fallback(ctx, info, "skipped", err.message, err.hint)
        lo, hi = ctx.options.get("min_speakers"), ctx.options.get("max_speakers")
        if lo is not None and hi is not None and lo > hi:
            ctx.warn(f"Ignoring the speaker hints: minimum {lo} is more than maximum {hi}.")
            lo = hi = None
        engine = self.engine(ctx)
        use_cuda = engine.cuda_available() and ctx.settings.transcription.device != "cpu"
        device = "cuda" if use_cuda else "cpu"
        ctx.progress(0.0, "Loading the diarization model")
        diarizer: Any = None
        oom: MM3Error | None = None
        failure: MM3Error | None = None
        turns: list[SpeakerTurn] | None = None
        try:
            diarizer = engine.load_diarizer(
                str(snapshot) if snapshot else model_id, token=token, device=device
            )
            ctx.check_cancelled()
            audio = engine.load_audio(ctx.artifacts["ingest"])
            turns = engine.diarize(
                diarizer,
                audio,
                min_speakers=lo,
                max_speakers=hi,
                progress=self.progress_fn(ctx, 0.05, 0.95, "Finding speakers"),
            )
        except (JobCancelled, InputRequired):
            raise
        except Exception as exc:
            if models.is_oom(exc) and ctx.attempt == 1:
                oom = oom_error("diarization", None, ctx.attempt)
            elif models.is_oom(exc):
                failure = MM3Error(
                    E_OOM,
                    "The GPU ran out of memory while finding speakers.",
                    "Close other programs that use the GPU and resume the job.",
                )
            else:
                log.warning("Diarization failed: %s", type(exc).__name__, exc_info=True)
                failure = models.diarization_access_error(exc, token_present=token is not None)
        finally:
            diarizer = None
            models.free_gpu_memory("diarize")
        if oom is not None:
            raise oom
        if failure is not None:
            return self.fallback(ctx, info, "failed", failure.message, failure.hint, failure.code)
        return turns

    @staticmethod
    def fallback(
        ctx: StageContext,
        info: dict[str, Any],
        status: str,
        message: str,
        hint: str,
        code: str = "E_HF_TOKEN_MISSING",
    ) -> None:
        info.update(status=status, error={"code": code, "message": message, "hint": hint})
        ctx.warn(f"Speakers were not separated: {message} {hint}")
        return None


# -- registration ----------------------------------------------------------------------------------

STAGE_CLASSES: dict[str, type[TranscriptionStage]] = {
    "transcribe": TranscribeStage,
    "align": AlignStage,
    "diarize": DiarizeStage,
}


def build_stage(name: str, display_name: str, settings: Settings) -> Stage:
    """The real stage when the ``ml`` extra is installed, otherwise a placeholder that fails
    with install instructions."""
    missing = models.missing_engine_modules()
    if missing:
        return UnavailableStage(
            name,
            display_name,
            uses_gpu=True,
            message=f"Transcription engine not installed (missing: {', '.join(missing)}).",
            hint=models.INSTALL_HINT,
        )
    return STAGE_CLASSES[name]()
