"""The speaker stages inside the job runner, with a deterministic fake embedder."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from meetingmaster3.config.settings import Settings
from meetingmaster3.domain.transcript import SpeakerMap, Transcript
from meetingmaster3.errors import MM3Error
from meetingmaster3.jobs.fakes import FakeEmbedder, fake_transcript
from meetingmaster3.jobs.files import job_dir
from meetingmaster3.jobs.models import JobStatus
from meetingmaster3.jobs.runner import JobRunner
from meetingmaster3.jobs.stage import BaseStage, Stage, StageContext
from meetingmaster3.speakers.cascade import NAMED_TRANSCRIPT_FILE, load_job_speaker_map
from meetingmaster3.speakers.stages import (
    CONFIRMED_FILE,
    EMBEDDINGS_FILE,
    SPEAKERS_FILE,
    SpeakerConfirmationStage,
    SpeakerSuggestStage,
    normalise_answer,
)
from meetingmaster3.speakers.store import VoiceprintStore

from ..jobs.helpers import Log, RecStage, add_job, make_runner, wait_status


class TranscriptStage(BaseStage):
    """A ``diarize`` stand-in writing a given transcript."""

    name = "diarize"

    def __init__(self, transcript: Transcript) -> None:
        super().__init__()
        self.transcript = transcript

    def run(self, ctx: StageContext) -> Path:
        return ctx.write_json("transcript.final.json", self.transcript.model_dump())


def stages(embedder: Any = None, transcript: Transcript | None = None) -> list[Stage]:
    log = Log()
    return [
        RecStage("ingest", log),
        TranscriptStage(transcript or fake_transcript(60)),
        SpeakerSuggestStage(lambda ctx: embedder or FakeEmbedder()),
        SpeakerConfirmationStage(),
        RecStage("generate", log),
    ]


def enabled() -> Settings:
    return Settings(privacy={"voiceprints_enabled": True})  # type: ignore[arg-type]


async def run_to_waiting(runner: JobRunner) -> tuple[str, Path, dict[str, Any]]:
    job_id = add_job(runner)
    assert await wait_status(runner, job_id, JobStatus.WAITING_FOR_INPUT, JobStatus.FAILED) is (
        JobStatus.WAITING_FOR_INPUT
    ), runner.jobs.get(job_id).error_message
    folder = job_dir(runner.jobs_root, job_id)
    return job_id, folder, json.loads((folder / SPEAKERS_FILE).read_text())


async def confirm(runner: JobRunner, job_id: str, speakers: dict[str, Any]) -> dict[str, Any]:
    runner.submit_input(job_id, {"speakers": speakers})
    assert await wait_status(runner, job_id, JobStatus.WRITTEN, JobStatus.FAILED) is (
        JobStatus.WRITTEN
    ), runner.jobs.get(job_id).error_message
    folder = job_dir(runner.jobs_root, job_id)
    data: dict[str, Any] = json.loads((folder / CONFIRMED_FILE).read_text())
    return data


def warnings(runner: JobRunner, job_id: str) -> list[str]:
    return [w["message"] for w in runner.describe(job_id)["warnings"]]


async def test_disabled_by_default_names_work_and_nothing_is_stored(tmp_path: Path) -> None:
    """Acceptance: with voiceprints disabled (the default) no voiceprint rows are written."""
    runner = make_runner(tmp_path, stages())
    await runner.start(prune=False)
    try:
        job_id, folder, payload = await run_to_waiting(runner)
        assert payload["voiceprints_enabled"] is False and payload["model_id"] is None
        assert [s["label"] for s in payload["speakers"]] == ["SPEAKER_00", "SPEAKER_01"]
        first = payload["speakers"][0]
        assert first["placeholder"] == "Speaker 1" and first["talk_seconds"] > 0
        assert first["snippets"] and first["candidates"] == [] and first["suggestion"] is None
        assert first["low_confidence"] is True  # nothing was embedded
        assert not (folder / EMBEDDINGS_FILE).exists()
        assert runner.describe(job_id)["waiting_for"]["speakers"] == payload["speakers"]

        done = await confirm(
            runner, job_id,
            {"SPEAKER_00": {"name": "Alice", "enroll": True}, "SPEAKER_01": "Bob"},
        )  # fmt: skip
        assert done["speaker_map"] == {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}
        assert done["participants"] == ["Alice", "Bob"] and done["enrolled"] == []
        assert any("turned off" in w for w in warnings(runner, job_id))
        store = VoiceprintStore(runner.db, enabled=False)
        assert store.count_rows() == {"voiceprints": 0, "voiceprint_embeddings": 0}
        assert load_job_speaker_map(folder) == SpeakerMap(names=done["speaker_map"])
        named = Transcript.model_validate_json((folder / NAMED_TRANSCRIPT_FILE).read_text())
        assert [s.speaker_name for s in named.segments][:2] == ["Alice", "Bob"]
    finally:
        await runner.stop()


async def test_enroll_then_second_run_suggests_the_right_people(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, stages(), enabled())
    await runner.start(prune=False)
    try:
        job_id, folder, payload = await run_to_waiting(runner)
        assert payload["model_id"] == FakeEmbedder.model_id
        assert all(s["candidates"] == [] for s in payload["speakers"])  # nobody known yet
        assert not any(s["low_confidence"] for s in payload["speakers"])
        assert (folder / EMBEDDINGS_FILE).is_file()
        done = await confirm(
            runner, job_id,
            {"SPEAKER_00": {"name": "Alice", "enroll": True},
             "SPEAKER_01": {"name": "Bob", "enroll": True}},
        )  # fmt: skip
        assert [e["name"] for e in done["enrolled"]] == ["Alice", "Bob"]
        assert not (folder / EMBEDDINGS_FILE).exists()  # per-meeting voice data is not kept
        store = VoiceprintStore(runner.db, enabled=True)
        assert store.count_rows() == {"voiceprints": 2, "voiceprint_embeddings": 2}
        ids = {p.display_name: p.person_id for p in store.list_people()}
        assert done["speakers"]["SPEAKER_00"]["person_id"] == ids["Alice"]

        second, _, payload2 = await run_to_waiting(runner)
        sugg = {s["label"]: s["suggestion"] for s in payload2["speakers"]}
        assert sugg["SPEAKER_00"]["name"] == "Alice" and sugg["SPEAKER_00"]["score"] > 0.99
        assert sugg["SPEAKER_01"]["person_id"] == ids["Bob"]
        # Accepting the suggestion and enrolling again adds a second sample to the same person.
        await confirm(
            runner, second,
            {"SPEAKER_00": {"name": "Alice", "person_id": ids["Alice"], "enroll": True},
             "SPEAKER_01": {"name": "Bob", "person_id": ids["Bob"]}},
        )  # fmt: skip
        alice = store.get(ids["Alice"])
        assert alice.n_samples == 2 and store.get(ids["Bob"]).n_samples == 1
    finally:
        await runner.stop()


async def test_merged_labels_become_one_person(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, stages(), enabled())
    await runner.start(prune=False)
    try:
        job_id, _, _ = await run_to_waiting(runner)
        done = await confirm(
            runner, job_id,
            {"SPEAKER_00": {"name": "Alice", "enroll": True},
             "SPEAKER_01": {"name": " alice ", "enroll": True}},
        )  # fmt: skip
        assert done["participants"] == ["Alice"]
        assert done["enrolled"][0]["labels"] == ["SPEAKER_00", "SPEAKER_01"]
        store = VoiceprintStore(runner.db, enabled=True)
        assert store.count_rows() == {"voiceprints": 1, "voiceprint_embeddings": 1}
    finally:
        await runner.stop()


async def test_existing_person_by_id_or_unique_name(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, stages(), enabled())
    store = VoiceprintStore(runner.db, enabled=True)
    robert = store.create_person("Bob")
    carol = store.create_person("Carol")
    await runner.start(prune=False)
    try:
        job_id, _, _ = await run_to_waiting(runner)
        await confirm(
            runner, job_id,
            {"SPEAKER_00": {"name": "Robert", "person_id": robert.person_id, "enroll": True},
             "SPEAKER_01": {"name": "carol", "enroll": True}},
        )  # fmt: skip
        assert store.get(robert.person_id).display_name == "Robert"  # renamed on enroll
        assert store.get(carol.person_id).n_samples == 1  # matched by its unique name
        assert store.count_rows()["voiceprints"] == 2
    finally:
        await runner.stop()


async def test_deleted_person_or_missing_voice_data(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, stages(), enabled())
    store = VoiceprintStore(runner.db, enabled=True)
    gone = store.create_person("Gone")
    store.delete_person(gone.person_id)
    await runner.start(prune=False)
    try:
        job_id, _, _ = await run_to_waiting(runner)
        await confirm(
            runner, job_id,
            {"SPEAKER_00": {"name": "Dana", "person_id": gone.person_id, "enroll": True}},
        )  # fmt: skip
        assert [p.display_name for p in store.list_people()] == ["Dana"]  # created anew

        job2, folder2, _ = await run_to_waiting(runner)
        (folder2 / EMBEDDINGS_FILE).unlink()
        await confirm(runner, job2, {"SPEAKER_00": {"name": "Eve", "enroll": True}})
        assert any("no voice data" in w for w in warnings(runner, job2))
        assert store.count_rows()["voiceprints"] == 1
    finally:
        await runner.stop()


class BrokenEmbedder(FakeEmbedder):
    def embed(self, audio: Path, segments: Any) -> Any:
        raise MM3Error("E_MODEL_MISSING", "The speaker model is not downloaded.", "Download it.")


class EmptyEmbedder(FakeEmbedder):
    def embed(self, audio: Path, segments: Any) -> Any:
        return [None for _ in segments]


async def test_embedding_failure_still_allows_naming(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, stages(BrokenEmbedder()), enabled())
    await runner.start(prune=False)
    try:
        job_id, folder, payload = await run_to_waiting(runner)
        assert payload["model_id"] is None and not (folder / EMBEDDINGS_FILE).exists()
        assert any("not downloaded" in w for w in warnings(runner, job_id))
        await confirm(runner, job_id, {"SPEAKER_00": {"name": "Ann", "enroll": True}})
        assert any("no voice data" in w for w in warnings(runner, job_id))
    finally:
        await runner.stop()


async def test_too_little_speech_is_not_enrolled(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, stages(EmptyEmbedder()), enabled())
    await runner.start(prune=False)
    try:
        job_id, _, payload = await run_to_waiting(runner)
        assert all(s["low_confidence"] for s in payload["speakers"])
        await confirm(runner, job_id, {"SPEAKER_00": {"name": "Ann", "enroll": True}})
        assert any("Not enough clear speech" in w for w in warnings(runner, job_id))
        assert VoiceprintStore(runner.db, enabled=True).count_rows()["voiceprints"] == 0
    finally:
        await runner.stop()


async def test_transcript_without_speakers_needs_no_confirmation(tmp_path: Path) -> None:
    flat = fake_transcript(60)
    flat = flat.model_copy(
        update={
            "diarized": False,
            "segments": [s.model_copy(update={"speaker_label": None}) for s in flat.segments],
        }
    )
    runner = make_runner(tmp_path, stages(transcript=flat), enabled())
    await runner.start(prune=False)
    try:
        job_id = add_job(runner)
        assert await wait_status(runner, job_id, JobStatus.WRITTEN, JobStatus.FAILED,
                                 JobStatus.WAITING_FOR_INPUT) is JobStatus.WRITTEN  # fmt: skip
        folder = job_dir(runner.jobs_root, job_id)
        payload = json.loads((folder / SPEAKERS_FILE).read_text())
        assert payload["diarized"] is False and payload["speakers"] == []
        assert json.loads((folder / CONFIRMED_FILE).read_text())["speaker_map"] == {}
    finally:
        await runner.stop()


async def test_unknown_labels_are_ignored_with_a_warning(tmp_path: Path) -> None:
    runner = make_runner(tmp_path, stages())
    await runner.start(prune=False)
    try:
        job_id, _, _ = await run_to_waiting(runner)
        done = await confirm(runner, job_id, {"SPEAKER_00": "Ann", "SPEAKER_99": "Ghost"})
        assert done["speaker_map"] == {"SPEAKER_00": "Ann"}
        assert any("SPEAKER_99" in w for w in warnings(runner, job_id))
    finally:
        await runner.stop()


@pytest.mark.parametrize(
    ("data", "match"),
    [
        ({}, "Expected"),
        ({"speakers": []}, "Expected"),
        ({"speakers": {"bad label!": "x"}}, "not a speaker label"),
        ({"speakers": {"S0": 5}}, "needs a name"),
        ({"speakers": {"S0": "  "}}, "non-empty name"),
        ({"speakers": {"S0": "x" * 201}}, "non-empty name"),
        ({"speakers": {"S0": {"name": "A", "colour": "red"}}}, "Unknown field"),
        ({"speakers": {"S0": {"name": "A", "person_id": 7}}}, "must be a string"),
        ({"speakers": {"S0": {"name": "A", "person_id": "../x"}}}, "not a person id"),
        ({"speakers": {"S0": {"name": "A", "enroll": "yes"}}}, "true or false"),
        ({"speakers": {f"S{i}": "A" for i in range(201)}}, "Too many"),
    ],
)
def test_answer_validation(data: dict[str, Any], match: str) -> None:
    with pytest.raises(MM3Error, match=match) as err:
        normalise_answer(data)
    assert err.value.status_code == 422


def test_answer_normalisation() -> None:
    pid = "0f" * 16
    out = normalise_answer(
        {"speakers": {"S0": " Ann  Lee ", "S1": {"name": "Bo", "person_id": pid.upper()}}}
    )
    assert out == {
        "speakers": {
            "S0": {"name": "Ann Lee", "person_id": None, "enroll": False},
            "S1": {"name": "Bo", "person_id": pid, "enroll": False},
        }
    }


def test_default_embedder_reports_missing_engine_or_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from meetingmaster3.jobs.stage import CancelToken
    from meetingmaster3.speakers.stages import default_embedder
    from meetingmaster3.transcription import models

    ctx = StageContext(
        job=None,  # type: ignore[arg-type]
        stage="speaker_suggest",
        job_dir=tmp_path,
        settings=Settings(),
        options={},
        artifacts={},
        attempt=1,
        token=CancelToken(),
        _progress=lambda *a: None,
    )
    monkeypatch.setattr(models, "missing_engine_modules", lambda: ["torch"])
    with pytest.raises(MM3Error) as err:
        default_embedder(ctx)
    assert err.value.code == "E_ENGINE_MISSING" and "uv sync --extra ml" in err.value.hint
    monkeypatch.setattr(models, "missing_engine_modules", lambda: [])
    monkeypatch.setenv("MM3_MODELS_DIR", str(tmp_path / "models"))
    with pytest.raises(MM3Error) as err:
        default_embedder(ctx)
    assert err.value.code == "E_MODEL_MISSING" and "mm3 models download" in err.value.hint
