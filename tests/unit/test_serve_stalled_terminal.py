"""The web app keeps answering when the terminal it logs to stops accepting output."""

from __future__ import annotations

import os
import pty
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="needs a Linux pty")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _get(port: int) -> int:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as resp:
        return int(resp.status)


def test_server_survives_a_frozen_terminal(tmp_path: Path) -> None:
    port = _free_port()
    master, slave = pty.openpty()
    env = {
        **os.environ,
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }
    proc = subprocess.Popen(  # noqa: S603 - fixed argv, our own interpreter
        [sys.executable, "-m", "meetingmaster3", "serve", "--port", str(port)],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
    )
    os.close(slave)
    try:
        for _ in range(100):
            try:
                if _get(port) == 200:
                    break
            except OSError:
                time.sleep(0.2)
        else:
            pytest.fail("server did not start")
        # Ctrl+S (XOFF) stops output, and nothing reads the master end, so writes would block.
        os.write(master, b"\x13")
        time.sleep(0.3)
        for _ in range(400):  # far more log output than a tty buffer holds
            assert _get(port) == 200
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        os.close(master)
