"""End-to-end checks of the S1, S5 and S6 controls (SPEC §15.3) that no narrower test covers.

The full control → test map is in SECURITY.md; the threat model is docs/THREAT_MODEL.md.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from meetingmaster3.cli import app
from meetingmaster3.config.paths import resolve_paths
from meetingmaster3.config.settings import BackendConfig, Settings
from meetingmaster3.headless import ProcessRequest, build_options, process
from tests.unit.jobs.helpers import make_tone, requires_ffmpeg

HF = "hf_S5CONTROLTOKEN123456"
KEY = "sk-S5CONTROLKEY-abcdefghij"
HEADER = "Bearer S5-PROXY-HEADER-9876"


def test_s1_default_bind_is_loopback_and_other_hosts_warn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().server.host == "127.0.0.1"
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr("uvicorn.run", lambda *a, **kw: calls.append(kw))
    quiet = CliRunner().invoke(app, ["serve"])
    assert quiet.exit_code == 0 and "WARNING" not in quiet.output
    loud = CliRunner().invoke(app, ["serve", "--host", "0.0.0.0"])  # noqa: S104 - the point
    assert loud.exit_code == 0 and "no authentication" in loud.output
    assert calls[0]["host"] == "127.0.0.1"


def _is_local(address: object) -> bool:
    if isinstance(address, tuple) and address:
        host = str(address[0])
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return host == "localhost"
    return True  # AF_UNIX and friends


@requires_ffmpeg
def test_s5_s6_a_whole_job_leaks_no_secret_and_contacts_no_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Upload → transcript → speakers → note with every secret configured: no secret reaches
    the vault, the job folder or the logs (S5), and nothing but loopback is contacted (S6)."""
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    vault = tmp_path / "vault"
    (vault / ".obsidian").mkdir(parents=True)
    settings = Settings()
    settings.vault.path = vault
    settings.secrets.hf_token = SecretStr(HF)
    settings.llm.backends["cloud"] = BackendConfig(
        kind="openrouter", api_key=SecretStr(KEY), headers={"Authorization": HEADER}
    )
    settings.register_secrets()

    contacted: list[object] = []
    real_connect = socket.socket.connect

    def audit(self: socket.socket, address: Any) -> Any:
        contacted.append(address)
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", audit)
    audio = make_tone(tmp_path / "2026-10-11 Security Review.wav", 2.0)
    request = ProcessRequest(
        audio,
        build_options(audio, title=None, date=None),
        {"SPEAKER_00": "Ann", "SPEAKER_01": "Ben"},
    )
    paths = resolve_paths()
    with caplog.at_level(logging.DEBUG):
        result = asyncio.run(process(settings, paths, request, echo=lambda _: None))
    assert result.status.value == "written", result.error

    assert not [a for a in contacted if not _is_local(a)], contacted
    written = [p for p in vault.rglob("*") if p.is_file()]
    assert any(p.name.endswith(".transcript.md") for p in written)
    folders = [*written, *(p for p in paths.data_dir.rglob("*") if p.is_file())]
    blobs = [p.read_bytes() for p in folders if p.suffix not in {".db", ".wal", ".shm"}]
    for secret in (HF, KEY, HEADER):
        assert all(secret.encode() not in b for b in blobs), secret
        assert secret not in caplog.text
