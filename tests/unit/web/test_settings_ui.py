"""The Settings screen: rendering, saving, validation, secrets, backends, privacy tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from meetingmaster3.config.settings import Settings, load_settings
from meetingmaster3.llm.base import ConnectionStatus
from meetingmaster3.speakers.store import VoiceprintStore
from meetingmaster3.web import model_downloads, settings_ui
from tests.unit.conftest import config_file

TABS = ["vault", "transcription", "notes", "llm", "privacy", "about"]


def reloaded(client: TestClient) -> Settings:
    return load_settings(config_file(client))


@pytest.mark.parametrize("tab", TABS)
def test_every_tab_renders(ui: TestClient, tab: str) -> None:
    r = ui.get(f"/settings/{tab}")
    assert r.status_code == 200 and "<h1>Settings</h1>" in r.text
    assert 'aria-current="page"' in r.text


def test_settings_root_redirects_and_unknown_tab_is_404(ui: TestClient) -> None:
    assert ui.get("/settings", follow_redirects=False).headers["location"] == "/settings/vault"
    assert ui.get("/settings/nope").status_code == 404


def test_save_without_csrf_header_is_refused(ui: TestClient) -> None:
    ui.headers["X-CSRF-Token"] = ""
    assert ui.post("/settings/notes", data={}).status_code == 403


def test_save_persists_and_survives_a_restart(ui: TestClient) -> None:
    r = ui.post(
        "/settings/transcription",
        data={
            "hardware.profile": "vram8",
            "transcription.model": "medium",
            "transcription.compute_type": "int8",
            "transcription.batch_size": "4",
            "transcription.device": "cpu",
            "transcription.language": "en",
            "transcription.on_non_english": "proceed",
            "transcription.offline": "1",
            "transcription.diarization_model": "pyannote/speaker-diarization-community-1",
        },
    )
    assert r.status_code == 200 and "✓ Saved." in r.text
    s = reloaded(ui)
    assert s.transcription.model == "medium" and s.transcription.batch_size == 4
    assert s.transcription.language == "en" and s.transcription.offline is True
    assert s.transcription.diarize is False  # an unchecked box is false
    assert s.hardware.profile == "vram8"
    live = ui.app.state.settings  # type: ignore[attr-defined]
    assert live.transcription.compute_type == "int8"  # applied at once, no restart


def test_empty_optional_values_become_none(ui: TestClient) -> None:
    ui.post("/settings/transcription", data={"transcription.batch_size": "6"})
    ui.post(
        "/settings/transcription",
        data={"transcription.batch_size": "", "transcription.language": ""},
    )
    s = reloaded(ui)
    assert s.transcription.batch_size is None and s.transcription.language is None


def test_validation_errors_are_inline_and_nothing_is_saved(ui: TestClient) -> None:
    r = ui.post(
        "/settings/notes",
        data={
            "generation.max_context": "10",
            "audio.max_upload_mb": "abc",
            "jobs.max_concurrent": "3",
        },
    )
    assert r.status_code == 200
    assert "Some values need fixing" in r.text and "Enter a whole number." in r.text
    assert 'value="10"' in r.text  # what the user typed is kept
    assert not config_file(ui).exists()
    assert ui.app.state.settings.jobs.max_concurrent == 2  # type: ignore[attr-defined]


def test_vault_tab_validates_the_path_and_subfolders(
    ui: TestClient, tmp_path: Path, vault: Path
) -> None:
    bad = ui.post(
        "/settings/vault",
        data={"vault.path": str(tmp_path / "missing"), "vault.output_subfolder": "Meetings/"},
    )
    assert "Some values need fixing" in bad.text
    escape = ui.post(
        "/settings/vault",
        data={
            "vault.path": str(vault),
            "vault.output_subfolder": "Meetings/{yyyy}/",
            "vault.templates_subfolder": "../outside",
            "vault.attachments_subfolder": "Meetings/attachments/",
        },
    )
    assert "outside the vault" in escape.text
    ok = ui.post(
        "/settings/vault",
        data={
            "vault.path": str(vault),
            "vault.output_subfolder": "Notes/{yyyy}/{mm}/",
            "vault.templates_subfolder": "MM3/templates/",
            "vault.attachments_subfolder": "MM3/audio/",
            "privacy.copy_audio_to_vault": "1",
        },
    )
    assert "✓ Saved." in ok.text
    s = reloaded(ui)
    assert s.vault.output_subfolder == "Notes/{yyyy}/{mm}/"
    assert s.privacy.copy_audio_to_vault is True and s.vault.path == vault


# -- secrets ----------


def test_secrets_are_write_only_empty_means_unchanged_and_clear_removes(ui: TestClient) -> None:
    ui.post("/settings/transcription", data={"secrets.hf_token": "hf_SECRETVALUE"})
    assert reloaded(ui).secrets.hf_token.get_secret_value() == "hf_SECRETVALUE"  # type: ignore[union-attr]
    page = ui.get("/settings/transcription").text
    assert "hf_SECRETVALUE" not in page and "Saved. Type a new value" in page
    ui.post("/settings/transcription", data={"secrets.hf_token": ""})  # empty = unchanged
    assert reloaded(ui).secrets.hf_token.get_secret_value() == "hf_SECRETVALUE"  # type: ignore[union-attr]
    ui.post("/settings/transcription", data={"secrets.hf_token": "", "clear:secrets.hf_token": "1"})
    assert reloaded(ui).secrets.hf_token is None


def test_no_secret_appears_in_any_rendered_page(ui: TestClient) -> None:
    ui.post("/settings/transcription", data={"secrets.hf_token": "hf_TOPSECRET1"})
    ui.post(
        "/settings/llm/save",
        data={"orig_name": "", "name": "cloud", "kind": "openrouter", "api_key": "sk-TOPSECRET2"},
    )
    ui.app.state.settings.secrets.openai_api_key = "sk-TOPSECRET3"  # type: ignore[attr-defined]
    pages = [f"/settings/{t}" for t in TABS] + [
        "/settings/llm/cloud/edit", "/templates", "/", "/meetings", "/setup",
        "/settings/transcription/models",
    ]  # fmt: skip
    for url in pages:
        text = ui.get(url).text
        for secret in ("hf_TOPSECRET1", "sk-TOPSECRET2", "sk-TOPSECRET3"):
            assert secret not in text, f"{secret} leaked into {url}"
    assert "sk-TOPSECRET2" in config_file(ui).read_text()  # but it is stored (0600)


def test_env_overridden_field_is_flagged(ui: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MM3_TRANSCRIPTION__MODEL", "small")
    assert "MM3_TRANSCRIPTION__MODEL" in ui.get("/settings/transcription").text


# -- LLM backends --------------------------------------------------------------------------------


def add_backend(ui: TestClient, **over: str) -> Any:
    data = {"orig_name": "", "name": "cloud", "kind": "openrouter", "api_key": "sk-x"}
    return ui.post("/settings/llm/save", data={**data, **over})


def test_backend_add_edit_default_remove(ui: TestClient) -> None:
    r = add_backend(ui, default_model="some/model", consent_remembered="1")
    assert r.headers["HX-Retarget"] == "#tab-body" and "cloud" in r.text
    cfg = reloaded(ui).llm.backends["cloud"]
    assert cfg.kind == "openrouter" and cfg.default_model == "some/model"
    assert cfg.consent_remembered and cfg.api_key.get_secret_value() == "sk-x"  # type: ignore[union-attr]

    edit = ui.get("/settings/llm/cloud/edit").text
    assert "Saved. Type a new key to replace it." in edit and "sk-x" not in edit

    ui.post(  # no new key typed: the stored one stays
        "/settings/llm/save",
        data={"orig_name": "cloud", "name": "cloud", "kind": "openrouter", "default_model": "m2"},
    )
    cfg = reloaded(ui).llm.backends["cloud"]
    assert cfg.default_model == "m2" and cfg.api_key.get_secret_value() == "sk-x"  # type: ignore[union-attr]
    assert cfg.consent_remembered is False  # the box was left unchecked

    ui.post("/settings/llm/default", data={"default_backend": "cloud"})
    assert reloaded(ui).llm.default_backend == "cloud"
    assert ui.post("/settings/llm/cloud/delete").status_code == 409  # it is the default
    ui.post("/settings/llm/default", data={"default_backend": "ollama"})
    ui.post("/settings/llm/cloud/delete")
    assert "cloud" not in reloaded(ui).llm.backends


def test_backend_form_errors_stay_in_the_form(ui: TestClient) -> None:
    r = add_backend(ui, name="Bad Name!")
    assert "backend-form" in r.text and "lowercase" in r.text.lower()
    assert (
        "cloud" not in load_settings(config_file(ui)).llm.backends
        if config_file(ui).exists()
        else True
    )
    dup = add_backend(ui, name="ollama")
    assert "already exists" in dup.text


def test_backend_rename_keeps_the_default(ui: TestClient) -> None:
    add_backend(ui)
    ui.post("/settings/llm/default", data={"default_backend": "cloud"})
    ui.post(
        "/settings/llm/save",
        data={"orig_name": "cloud", "name": "router", "kind": "openrouter"},
    )
    s = reloaded(ui)
    assert s.llm.default_backend == "router" and "cloud" not in s.llm.backends


def test_revoke_remembered_consent(ui: TestClient) -> None:
    add_backend(ui, consent_remembered="1")
    ui.post("/settings/llm/cloud/revoke-consent")
    assert reloaded(ui).llm.backends["cloud"].consent_remembered is False


def test_backend_test_and_models(ui: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class Fake:
        async def test_connection(self) -> ConnectionStatus:
            return ConnectionStatus(True, "Connected (12 ms)")

        async def list_models(self) -> list[Any]:
            from meetingmaster3.llm.base import ModelInfo

            return [ModelInfo(id="m-1", name="Model One")]

    registry = ui.app.state.llm_registry  # type: ignore[attr-defined]
    monkeypatch.setattr(registry, "get", lambda name=None: Fake())
    assert "Connected (12 ms)" in ui.post("/settings/llm/ollama/test").text
    assert 'value="m-1"' in ui.get("/settings/llm/ollama/models").text


def test_save_invalidates_the_backend_cache(ui: TestClient) -> None:
    add_backend(ui, base_url="http://one.example/v1", kind="openai_compat", api_key="")
    registry = ui.app.state.llm_registry  # type: ignore[attr-defined]
    first = registry.get("cloud")
    ui.post(
        "/settings/llm/save",
        data={"orig_name": "cloud", "name": "cloud", "kind": "openai_compat",
              "base_url": "http://two.example/v1"},
    )  # fmt: skip
    assert registry.get("cloud") is not first


# -- transcription tools ----------


@respx.mock
def test_hf_token_test_reports_without_leaking(ui: TestClient) -> None:
    ui.post("/settings/transcription", data={"secrets.hf_token": "hf_LEAKCHECK"})
    respx.get("https://huggingface.co/api/whoami-v2").mock(
        return_value=httpx.Response(200, json={"name": "nick"})
    )
    respx.head(url__regex=r"https://huggingface\.co/.*/resolve/main/config\.yaml").mock(
        return_value=httpx.Response(403)
    )
    r = ui.post("/settings/transcription/hf-test")
    assert "has not accepted the model" in r.text and "hf_LEAKCHECK" not in r.text
    assert respx.calls.last.request.headers["authorization"] == "Bearer hf_LEAKCHECK"


def test_hf_token_test_without_token(ui: TestClient) -> None:
    assert "No token is saved" in ui.post("/settings/transcription/hf-test").text


def test_model_download_runs_in_the_background(
    ui: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    done: list[str] = []

    def fake_plan(*_a: Any, **kw: Any) -> Any:
        plan = [
            (model_downloads.Item(kw["whisper"], "whisper"), lambda: done.append("whisper")),
            (model_downloads.Item("pyannote/x", "diarization"), lambda: done.append("diar")),
        ]
        return plan, lambda: None

    monkeypatch.setattr(settings_ui, "build_plan", fake_plan)
    r = ui.post(
        "/settings/transcription/models/download",
        data={"whisper": "small", "align_language": "en", "diarization": "1"},
    )
    assert r.status_code == 200
    manager = ui.app.state.model_downloads  # type: ignore[attr-defined]
    manager.wait(5)
    assert done == ["whisper", "diar"]
    page = ui.get("/settings/transcription/models").text
    assert "done" in page and "every 2s" not in page
    bad = ui.post("/settings/transcription/models/download", data={"whisper": "../etc"})
    assert bad.status_code == 422


def test_download_failure_is_reported_and_not_fatal() -> None:
    from meetingmaster3.errors import MM3Error

    manager = model_downloads.DownloadManager()

    def boom() -> None:
        raise MM3Error("E_HF_TOKEN_MISSING", "No token.", "Add one.")

    plan = [(model_downloads.Item("x", "diarization"), boom)]
    assert manager.start(plan, setup=lambda: None)
    manager.wait(5)
    snap = manager.snapshot()
    assert not snap["running"] and snap["steps"][0]["state"] == "failed"
    assert "No token." in snap["steps"][0]["message"]


# -- privacy ----------


def test_privacy_save_and_bind_host_warning(ui: TestClient) -> None:
    r = ui.post(
        "/settings/privacy",
        data={
            "privacy.audio_retention": "days",
            "privacy.audio_retention_days": "30",
            "privacy.voiceprints_enabled": "1",
            "speakers.match_threshold": "0.7",
            "speakers.match_margin": "0.05",
            "speakers.max_embeddings_per_person": "10",
        },
    )
    assert "✓ Saved." in r.text
    s = reloaded(ui)
    assert s.privacy.audio_retention_days == 30 and s.privacy.voiceprints_enabled
    assert s.speakers.match_threshold == 0.7
    assert "Only this computer can reach" in r.text
    ui.app.state.settings.server.host = "0.0.0.0"  # type: ignore[attr-defined]  # noqa: S104
    assert "non-loopback" in ui.get("/settings/privacy").text


def test_voiceprint_delete_and_two_step_wipe(ui: TestClient) -> None:
    store = VoiceprintStore(ui.app.state.db, enabled=True)  # type: ignore[attr-defined]
    ana = store.create_person("Ana")
    store.create_person("Ben")
    page = ui.get("/settings/privacy").text
    assert "Ana" in page and "Ben" in page

    ui.post(f"/settings/privacy/voiceprints/{ana.person_id}/delete")
    assert [p.display_name for p in store.list_people()] == ["Ben"]

    ask = ui.post("/settings/privacy/voiceprints/wipe")
    assert "Delete every voiceprint?" in ask.text
    assert [p.display_name for p in store.list_people()] == ["Ben"]  # asking deletes nothing
    token = ask.text.split('name="confirm_token" value="')[1].split('"')[0]
    wrong = ui.post("/settings/privacy/voiceprints/wipe/confirm", data={"confirm_token": "nope"})
    assert wrong.status_code == 428 and store.list_people()
    ok = ui.post("/settings/privacy/voiceprints/wipe/confirm", data={"confirm_token": token})
    assert "Deleted all voiceprints" in ok.text and store.list_people() == []
    again = ui.post("/settings/privacy/voiceprints/wipe/confirm", data={"confirm_token": token})
    assert again.status_code == 428  # single use


def test_retention_preview_and_prune(ui: TestClient) -> None:
    from meetingmaster3.jobs import retention

    runner = ui.app.state.runner  # type: ignore[attr-defined]
    called: list[bool] = []
    runner.prune = lambda dry_run=False: [] if dry_run else called.append(True) or []
    assert "Nothing is due for deletion" in ui.get("/settings/privacy").text
    item = retention.PruneItem(
        "j1", "Old standup", __import__("datetime").datetime.now(), ["a"], 2_097_152
    )
    runner.prune = lambda dry_run=False: [item] if dry_run else called.append(True) or [item]
    page = ui.get("/settings/privacy").text
    assert "Old standup" in page and "2.0 MB" in page
    assert "Deleted the audio of 1 meeting" in ui.post("/settings/privacy/prune").text
    assert called


# -- about ----------


def test_about_shows_diagnostics_paths_and_exports(ui: TestClient) -> None:
    text = ui.get("/settings/about").text
    assert "config.yaml" in text and "data-copy=" in text
    assert "Python" in text and "ffmpeg" in text
    assert "/api/export/all" in text


def test_open_folder_is_refused_when_unavailable(
    ui: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_ui, "_can_open_folders", lambda: False)
    assert ui.post("/settings/about/open").status_code == 409
    launched: list[list[str]] = []
    monkeypatch.setattr(settings_ui, "_can_open_folders", lambda: True)
    monkeypatch.setattr(settings_ui.subprocess, "Popen", lambda cmd: launched.append(cmd))
    assert ui.post("/settings/about/open").status_code == 200
    assert launched[0][0] == "xdg-open"


def test_every_documented_setting_is_in_the_ui() -> None:
    """Each user-editable setting in configuration.md appears in a settings tab (the rest are
    structural: server.*, llm.backends, secrets for other providers)."""
    from meetingmaster3.web.settings_fields import TABS

    shown = {f.path for _label, fields in TABS.values() for f in fields}
    expected = {
        "vault.path", "vault.output_subfolder", "vault.templates_subfolder",
        "transcription.model", "transcription.compute_type", "transcription.batch_size",
        "transcription.device", "transcription.language", "transcription.on_non_english",
        "transcription.diarize", "transcription.diarization_model", "transcription.offline",
        "transcription.unload_ollama", "hardware.profile", "generation.default_template",
        "generation.write_companion", "generation.max_context", "generation.think",
        "generation.install_templates", "audio.max_upload_mb", "audio.opus_bitrate_kbps",
        "jobs.max_concurrent", "jobs.prune_interval_hours", "privacy.audio_retention",
        "privacy.audio_retention_days", "privacy.voiceprints_enabled", "speakers.match_threshold",
        "speakers.match_margin", "speakers.max_embeddings_per_person", "secrets.hf_token",
    }  # fmt: skip
    assert expected <= shown
