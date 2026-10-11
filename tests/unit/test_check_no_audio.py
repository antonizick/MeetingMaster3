from __future__ import annotations

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_no_audio", Path(__file__).parents[2] / "scripts" / "check_no_audio.py"
)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_blocks_audio_elsewhere() -> None:
    assert mod.is_blocked("recordings/meeting.wav")
    assert mod.is_blocked("tests/fixtures/audio/real.wav")
    assert mod.is_blocked("tests/fixtures/audio/sub/x.fixture.wav")
    assert mod.is_blocked("MEETING.MP3")


def test_allows_fixtures_and_non_audio() -> None:
    assert not mod.is_blocked("tests/fixtures/audio/sample.fixture.opus")
    assert not mod.is_blocked("README.md")
    assert not mod.is_blocked("src/meetingmaster3/cli.py")


def test_main_exit_codes() -> None:
    assert mod.main(["a.wav"]) == 1
    assert mod.main(["a.py"]) == 0
