from __future__ import annotations

import stat
from pathlib import Path

import pytest
from pydantic import SecretStr

from meetingmaster3.config.paths import resolve_paths
from meetingmaster3.config.settings import MASK, Settings, load_settings


def test_defaults() -> None:
    s = Settings()
    assert s.server.host == "127.0.0.1"
    assert s.server.port == 8765
    assert s.privacy.audio_retention_days == 90
    assert s.privacy.voiceprints_enabled is False
    assert s.vault.output_subfolder == "Meetings/{yyyy}/"


def test_precedence_defaults_yaml_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("server:\n  port: 9000\n  host: localhost\n")
    s = load_settings(cfg)
    assert (s.server.port, s.server.host) == (9000, "localhost")  # yaml beats default

    monkeypatch.setenv("MM3_SERVER__PORT", "9100")
    s = load_settings(cfg)
    assert s.server.port == 9100  # env beats yaml
    assert s.server.host == "localhost"  # untouched yaml value survives


def test_missing_config_file_uses_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "nope.yaml").server.port == 8765


def test_save_is_0600_and_roundtrips(tmp_path: Path) -> None:
    s = Settings()
    s.secrets.hf_token = SecretStr("hf_abcdefghijklmnop")
    target = s.save(tmp_path / "sub" / "config.yaml")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    again = load_settings(target)
    assert again.secrets.hf_token is not None
    assert again.secrets.hf_token.get_secret_value() == "hf_abcdefghijklmnop"
    assert not list(target.parent.glob(".config-*.tmp"))


def test_secrets_masked_on_dump() -> None:
    s = Settings()
    s.secrets.hf_token = SecretStr("hf_abcdefghijklmnop")
    dumped = s.dump_masked()
    assert dumped["secrets"]["hf_token"] == MASK
    assert dumped["secrets"]["openai_api_key"] is None
    assert "hf_abcdefghijklmnop" not in repr(s)
    assert "hf_abcdefghijklmnop" not in str(dumped)


def test_backend_headers_and_url_credentials_are_masked_and_redacted() -> None:
    """Phase 15 finding: proxy credentials in headers or the base URL were dumped in clear."""
    from meetingmaster3.config.settings import BackendConfig
    from meetingmaster3.logging import redact

    s = Settings()
    s.llm.backends["proxy"] = BackendConfig(
        kind="openai",
        base_url="https://user:pr0xy-pass@llm.example/v1",
        headers={"Authorization": "Bearer tok-SECRET-1234", "X-Title": "MeetingMaster3"},
    )
    s.register_secrets()
    dumped = s.dump_masked()["llm"]["backends"]["proxy"]
    assert dumped["headers"] == {"Authorization": MASK, "X-Title": "MeetingMaster3"}
    assert dumped["base_url"] == f"https://user:{MASK}@llm.example/v1"
    assert "tok-SECRET-1234" not in str(s.dump_masked()) and "pr0xy-pass" not in str(dumped)
    line = redact("sent Bearer tok-SECRET-1234 via pr0xy-pass")
    assert "tok-SECRET-1234" not in line and "pr0xy-pass" not in line


def test_paths_xdg_and_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = resolve_paths()
    assert p.config_file == tmp_path / "cfg" / "meetingmaster3" / "config.yaml"
    assert p.models_dir == tmp_path / "cache" / "meetingmaster3" / "models"
    monkeypatch.setenv("MM3_DATA_DIR", str(tmp_path / "elsewhere"))
    assert resolve_paths().data_dir == tmp_path / "elsewhere"
    p = resolve_paths()
    p.ensure()
    assert stat.S_IMODE(p.data_dir.stat().st_mode) == 0o700
    assert p.jobs_dir.is_dir() and p.logs_dir.is_dir()
