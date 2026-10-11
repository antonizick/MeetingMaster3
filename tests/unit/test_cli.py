from __future__ import annotations

from typer.testing import CliRunner

from meetingmaster3 import __version__
from meetingmaster3.cli import app

runner = CliRunner()


def test_version() -> None:
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0 and r.stdout.strip() == __version__


def test_config_path() -> None:
    r = runner.invoke(app, ["config", "path"])
    assert r.exit_code == 0
    assert "config.yaml" in r.stdout and "meetingmaster3" in r.stdout


def test_config_show_masks_secrets(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MM3_SECRETS__HF_TOKEN", "hf_abcdefghij1234567890")
    r = runner.invoke(app, ["config", "show"])
    assert r.exit_code == 0
    assert "hf_abcdefghij" not in r.stdout and "********" in r.stdout
