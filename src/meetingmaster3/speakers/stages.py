"""The ``speaker_suggest`` stage and the ``await_speaker_confirmation`` pause.

``speaker_suggest`` profiles every diarized speaker (talk time, clean speech, sample snippets) and,
only when ``privacy.voiceprints_enabled`` is true, embeds their voices and ranks known people.
It writes ``speakers.json`` (shown to the UI; never contains vectors) and, when it embedded
voices, ``speaker_embeddings.json`` (private to the job folder, deleted after confirmation).

``await_speaker_confirmation`` pauses the job until the user confirms names, then stores the one
speaker map of the job (``speaker_map.json`` plus ``transcript.named.json``), enrolls the voices
the user asked to remember, and writes ``speakers.confirmed.json`` as its artifact.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from meetingmaster3.domain.transcript import (
    SPEAKER_LABEL_RE,
    SpeakerMap,
    Transcript,
    clean_name,
)
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.stage import (
    AwaitInputStage,
    BaseStage,
    InputRequired,
    JobCancelled,
    StageContext,
)
from meetingmaster3.speakers import cascade
from meetingmaster3.speakers.embeddings import (
    Embedder,
    SpeakerProfile,
    embed_profiles,
    profile_speakers,
    turns_from,
)
from meetingmaster3.speakers.match import match_speakers
from meetingmaster3.speakers.store import MAX_NAME_LENGTH, VoiceprintStore, check_person_id
from meetingmaster3.speakers.vectors import weighted_mean

log = logging.getLogger(__name__)

SPEAKERS_FILE = "speakers.json"
EMBEDDINGS_FILE = "speaker_embeddings.json"
CONFIRMED_FILE = "speakers.confirmed.json"

EmbedderFactory = Callable[[StageContext], Embedder]


def default_embedder(ctx: StageContext) -> Embedder:
    """The pyannote embedder from the cached diarization pipeline (raises ``MM3Error`` when the
    engine or the model is missing)."""
    from meetingmaster3.config.paths import resolve_paths
    from meetingmaster3.speakers.embeddings import PyannoteEmbedder
    from meetingmaster3.transcription import models

    missing = models.missing_engine_modules()
    if missing:
        raise MM3Error(
            "E_ENGINE_MISSING",
            f"The speech engine is not installed (missing: {', '.join(missing)}).",
            models.INSTALL_HINT,
        )
    settings = ctx.settings.transcription
    models_dir = resolve_paths().models_dir
    models.configure_model_cache(models_dir, offline=settings.offline)
    snapshot = models.diarization_snapshot(models_dir, settings.diarization_model)
    if snapshot is None or not (snapshot / "embedding").is_dir():
        raise MM3Error(
            "E_MODEL_MISSING",
            "The speaker model is not downloaded.",
            "Run `mm3 models download` (it needs your Hugging Face token).",
        )
    from meetingmaster3.transcription.engine import WhisperXEngine

    cuda = WhisperXEngine().cuda_available() and settings.device != "cpu"
    return PyannoteEmbedder(
        snapshot / "embedding",
        pipeline=settings.diarization_model,
        device="cuda" if cuda else "cpu",
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def load_final_transcript(ctx: StageContext) -> Transcript:
    return Transcript.model_validate_json(ctx.artifacts["diarize"].read_text(encoding="utf-8"))


class SpeakerSuggestStage(BaseStage):
    name = "speaker_suggest"
    display_name = "Speaker suggestions"
    uses_gpu = True

    def __init__(self, embedder_factory: EmbedderFactory | None = None) -> None:
        super().__init__()
        self._embedder_factory = embedder_factory or default_embedder

    def run(self, ctx: StageContext) -> Path:
        transcript = load_final_transcript(ctx)
        labels = transcript.speaker_labels
        enabled = ctx.settings.privacy.voiceprints_enabled
        ctx.artifact(EMBEDDINGS_FILE).unlink(missing_ok=True)
        out: dict[str, Any] = {
            "diarized": transcript.diarized and bool(labels),
            "voiceprints_enabled": enabled,
            "model_id": None,
            "threshold": ctx.settings.speakers.match_threshold,
            "speakers": [],
        }
        if not out["diarized"]:
            return ctx.write_json(SPEAKERS_FILE, out)  # nothing to name: confirmation passes
        diarization = _read_json(ctx.job_dir / "diarization.json")
        turns = turns_from(diarization, transcript)
        talk = (diarization or {}).get("speakers") or None
        profiles = profile_speakers(turns, labels, talk_seconds=talk)
        candidates: dict[str, list[dict[str, Any]]] = {}
        if enabled:
            ctx.progress(0.0, "Recognising voices")
            model_id = self.embed(ctx, profiles)
            if model_id is not None:
                out["model_id"] = model_id
                candidates = self.suggest(ctx, profiles, model_id)
                ctx.write_json(
                    EMBEDDINGS_FILE,
                    {
                        "model_id": model_id,
                        "speakers": {
                            p.label: {"embedding": p.embedding, "seconds": p.embedded_seconds}
                            for p in profiles.values()
                            if p.embedding is not None
                        },
                    },
                )
        mapping = SpeakerMap()
        for label in labels:
            p = profiles[label]
            ranked = candidates.get(label, [])
            out["speakers"].append(
                {
                    "label": label,
                    "placeholder": mapping.display_name(label, labels),
                    **p.stats(),
                    "snippets": [s.to_dict() for s in p.snippets],
                    "candidates": ranked,
                    "suggestion": next((c for c in ranked if c["suggested"]), None),
                }
            )
        ctx.progress(1.0, "Speakers ready to confirm")
        return ctx.write_json(SPEAKERS_FILE, out)

    def embed(self, ctx: StageContext, profiles: dict[str, SpeakerProfile]) -> str | None:
        """Fill the profiles' embeddings; returns the model id, or ``None`` (with a warning)
        when voices could not be embedded. Naming still works without suggestions."""
        embedder: Embedder | None = None
        try:
            embedder = self._embedder_factory(ctx)
            embed_profiles(
                embedder,
                ctx.artifacts["ingest"],
                profiles,
                check=ctx.check_cancelled,
                progress=lambda f: ctx.progress(0.9 * f, "Recognising voices"),
            )
            return embedder.model_id
        except (JobCancelled, InputRequired):
            raise
        except Exception as exc:
            reason = exc.message if isinstance(exc, MM3Error) else type(exc).__name__
            hint = f" {exc.hint}" if isinstance(exc, MM3Error) and exc.hint else ""
            log.warning("Speaker embedding failed: %s", reason, exc_info=True)
            ctx.warn(f"No name suggestions for this meeting: {reason}.{hint}")
            for p in profiles.values():
                p.embedding = None
            return None
        finally:
            if embedder is not None:
                embedder.close()
            self.free_gpu()

    @staticmethod
    def free_gpu() -> None:
        from meetingmaster3.transcription.models import free_gpu_memory

        free_gpu_memory("speaker embeddings released")

    @staticmethod
    def suggest(
        ctx: StageContext, profiles: dict[str, SpeakerProfile], model_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        if ctx.db is None:  # pragma: no cover - the runner always passes the database
            return {}
        store = VoiceprintStore(ctx.db, enabled=True)
        settings = ctx.settings.speakers
        ranked = match_speakers(
            {label: p.embedding for label, p in profiles.items()},
            store.known_people(model_id),
            threshold=settings.match_threshold,
            margin=settings.match_margin,
        )
        return {label: [c.to_dict() for c in cands] for label, cands in ranked.items()}


# -- confirmation ------------------------------------------------------------------------------


def _invalid(message: str, hint: str = "") -> MM3Error:
    return MM3Error(
        "E_INPUT_INVALID",
        message,
        hint
        or 'Send {"speakers": {"<label>": {"name": "<name>", "person_id": "<id>" | null, '
        '"enroll": true | false}}}; a plain string is accepted as the name.',
        status_code=422,
    )


ENTRY_KEYS = frozenset({"name", "person_id", "enroll"})


def normalise_entry(label: str, value: Any) -> dict[str, Any]:
    if not isinstance(label, str) or not SPEAKER_LABEL_RE.match(label):
        raise _invalid(f"{str(label)[:64]!r} is not a speaker label.")
    if isinstance(value, str):
        value = {"name": value}
    if not isinstance(value, dict):
        raise _invalid(f"Speaker {label!r} needs a name.")
    unknown = set(value) - ENTRY_KEYS
    if unknown:
        raise _invalid(f"Unknown field(s) for speaker {label!r}: {', '.join(sorted(unknown))}.")
    name = value.get("name")
    if not isinstance(name, str) or not clean_name(name) or len(name) > MAX_NAME_LENGTH:
        raise _invalid(
            f"Speaker {label!r} needs a non-empty name (up to {MAX_NAME_LENGTH} characters).",
            "Type a name for every speaker, or keep the suggested placeholder.",
        )
    person_id = value.get("person_id")
    if person_id is not None:
        if not isinstance(person_id, str):
            raise _invalid(f"Speaker {label!r}: person_id must be a string.")
        try:
            person_id = check_person_id(person_id)
        except MM3Error as exc:
            raise _invalid(f"Speaker {label!r}: {person_id[:64]!r} is not a person id.") from exc
    enroll = value.get("enroll", False)
    if not isinstance(enroll, bool):
        raise _invalid(f"Speaker {label!r}: enroll must be true or false.")
    return {"name": clean_name(name), "person_id": person_id, "enroll": enroll}


def normalise_answer(data: dict[str, Any]) -> dict[str, Any]:
    """``{"speakers": {label: name | {name, person_id?, enroll?}}}`` →
    ``{"speakers": {label: {"name", "person_id", "enroll"}}}``."""
    speakers = data.get("speakers")
    if not isinstance(speakers, dict):
        raise _invalid('Expected {"speakers": {"<label>": ...}}.')
    if len(speakers) > 200:
        raise _invalid("Too many speakers.")
    return {"speakers": {label: normalise_entry(label, v) for label, v in speakers.items()}}


class SpeakerConfirmationStage(AwaitInputStage):
    """Pauses the job until the user confirms speaker names, then applies them.

    The question's payload is ``speakers.json``. A transcript without speakers needs no answer:
    the stage completes at once with an empty map."""

    def __init__(self) -> None:
        super().__init__("await_speaker_confirmation", "Confirm speakers", "speaker_confirmation")

    def payload(self, ctx: StageContext) -> dict[str, Any]:
        path = ctx.artifacts.get("speaker_suggest")
        return (_read_json(path) if path is not None else None) or {}

    def validate_input(self, data: dict[str, Any]) -> dict[str, Any]:
        return normalise_answer(data)

    def run(self, ctx: StageContext) -> Path:
        transcript = load_final_transcript(ctx)
        labels = transcript.speaker_labels
        answer = ctx.input()
        if answer is None:
            if transcript.diarized and labels:
                raise InputRequired(self.kind, self.payload(ctx))
            answer = {"speakers": {}}
        entries = normalise_answer(answer)["speakers"]
        dropped = sorted(set(entries) - set(labels))
        if dropped:
            ctx.warn(f"Ignored names for unknown speaker labels: {', '.join(dropped)}.")
        entries = {label: e for label, e in entries.items() if label in labels}
        enrolled = self.enroll(ctx, entries)
        speaker_map = SpeakerMap(names={label: e["name"] for label, e in entries.items()})
        cascade.save_job_speakers(ctx.job_dir, speaker_map, transcript)
        ctx.artifact(EMBEDDINGS_FILE).unlink(missing_ok=True)  # biometric data: not kept
        return ctx.write_json(
            CONFIRMED_FILE,
            {
                "speakers": entries,
                "speaker_map": speaker_map.names,
                "participants": cascade.speaker_names(speaker_map, labels),
                "enrolled": enrolled,
            },
        )

    def enroll(self, ctx: StageContext, entries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Store the voices the user asked to remember. Labels with the same person (by id, or
        by name) are merged into one embedding, weighted by their clean speech."""
        wanted = {label: e for label, e in entries.items() if e["enroll"]}
        if not wanted:
            return []
        if not ctx.settings.privacy.voiceprints_enabled:
            ctx.warn("Voices were not remembered because voice recognition is turned off.")
            return []
        data = _read_json(ctx.artifact(EMBEDDINGS_FILE))
        if data is None or ctx.db is None:
            ctx.warn("Voices were not remembered: no voice data was computed for this meeting.")
            return []
        model_id = str(data["model_id"])
        vectors: dict[str, dict[str, Any]] = data.get("speakers", {})
        store = VoiceprintStore(
            ctx.db,
            enabled=True,
            max_embeddings=ctx.settings.speakers.max_embeddings_per_person,
        )
        groups: dict[str, list[str]] = {}
        for label, e in wanted.items():
            key = e["person_id"] or "name:" + e["name"].casefold()
            groups.setdefault(key, []).append(label)
        enrolled = []
        for labels in groups.values():
            usable = [lbl for lbl in labels if vectors.get(lbl, {}).get("embedding")]
            if not usable:
                ctx.warn(f"Not enough clear speech to remember {entries[labels[0]]['name']}.")
                continue
            entry = entries[labels[0]]
            person = store.find(entry["person_id"]) if entry["person_id"] else None
            if person is None:
                same_name = store.find_by_name(entry["name"])
                person = same_name[0] if len(same_name) == 1 else None
            if person is None:
                person = store.create_person(entry["name"])
            elif person.display_name != entry["name"]:
                person = store.rename(person.person_id, entry["name"])
            seconds = [float(vectors[lbl].get("seconds") or 0.0) or 1.0 for lbl in usable]
            centroid = weighted_mean([vectors[lbl]["embedding"] for lbl in usable], seconds)
            store.add_embedding(
                person.person_id,
                centroid,
                model_id=model_id,
                seconds=sum(seconds),
                source_job_id=ctx.job_id,
            )
            for lbl in labels:
                entries[lbl]["person_id"] = person.person_id
            enrolled.append({"person_id": person.person_id, "name": person.display_name,
                             "labels": usable})  # fmt: skip
        return enrolled
