"""Validating and applying a settings patch, and the config.yaml round-trip."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from meetingmaster3.config import editing
from meetingmaster3.config.settings import BackendConfig, Settings, load_settings


def test_valid_patch_is_applied_in_place() -> None:
    s = Settings()
    section = s.transcription
    errors = editing.apply_patch(s, {"transcription.batch_size": 4, "transcription.diarize": False})
    assert errors == {}
    assert s.transcription.batch_size == 4 and s.transcription.diarize is False
    assert s.transcription is not section  # replaced by a validated copy


def test_invalid_value_applies_nothing() -> None:
    s = Settings()
    errors = editing.apply_patch(
        s,
        {"transcription.batch_size": 999, "transcription.diarize": False, "jobs.max_concurrent": 3},
    )
    assert "transcription.batch_size" in errors
    assert s.transcription.batch_size is None and s.transcription.diarize is True
    assert s.jobs.max_concurrent == 2  # an unrelated valid field is not applied either


def test_pattern_error_names_the_field() -> None:
    errors = editing.validate_patch(Settings(), {"transcription.language": "english!"})
    assert list(errors) == ["transcription.language"]


def test_secret_set_and_clear_round_trip(tmp_path: Path) -> None:
    s = Settings()
    assert editing.apply_patch(s, {"secrets.hf_token": "hf_abc123"}) == {}
    assert isinstance(s.secrets.hf_token, SecretStr)
    target = tmp_path / "config.yaml"
    editing.save_settings(s, target)
    assert oct(target.stat().st_mode & 0o777) == "0o600"
    assert load_settings(target).secrets.hf_token.get_secret_value() == "hf_abc123"  # type: ignore[union-attr]
    editing.apply_patch(s, {"secrets.hf_token": None})
    editing.save_settings(s, target)
    assert load_settings(target).secrets.hf_token is None


def test_backend_validation() -> None:
    cfg, errors = editing.validate_backend({"kind": "ollama", "context_window": 10})
    assert cfg is None and "context_window" in errors
    cfg, errors = editing.validate_backend({"kind": "ollama", "base_url": "http://x:1"})
    assert errors == {} and isinstance(cfg, BackendConfig)
