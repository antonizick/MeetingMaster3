"""The R5 VRAM handoff: ask a local Ollama to unload before transcription."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
import respx

from meetingmaster3.config.settings import Settings
from meetingmaster3.transcription.handoff import release_local_llm as real_release

BASE = "http://127.0.0.1:11434"


@pytest.fixture
def release() -> Callable[..., list[str]]:
    # The package conftest replaces release_local_llm for the stage tests; this is the real one,
    # imported when the module was collected.
    return real_release


@respx.mock
def test_unloads_a_local_ollama(release) -> None:  # type: ignore[no-untyped-def]
    ps = respx.get(f"{BASE}/api/ps").mock(
        side_effect=[
            httpx.Response(200, json={"models": [{"name": "qwen3:4b"}]}),
            httpx.Response(200, json={"models": []}),
        ]
    )
    unload = respx.post(f"{BASE}/api/generate").respond(json={"done": True})
    settings = Settings(llm={"backends": {"ollama": {"kind": "ollama", "base_url": BASE}}})  # type: ignore[arg-type]
    assert release(settings, None) == ["qwen3:4b"]
    assert unload.calls[0].request.read() == b'{"model":"qwen3:4b","keep_alive":0}'
    assert ps.call_count == 2


@respx.mock
def test_skips_remote_and_cloud_backends(release) -> None:  # type: ignore[no-untyped-def]
    route = respx.route().respond(500)
    remote = Settings(
        llm={
            "default_backend": "lab",
            "backends": {"lab": {"kind": "ollama", "base_url": "http://10.0.0.5:11434"}},
        }  # type: ignore[arg-type]
    )
    assert release(remote, None) == []
    cloud = Settings(
        llm={"default_backend": "or", "backends": {"or": {"kind": "openrouter"}}}  # type: ignore[arg-type]
    )
    assert release(cloud, "or") == []
    assert route.call_count == 0


def test_disabled_by_setting(release) -> None:  # type: ignore[no-untyped-def]
    off = Settings(transcription={"unload_ollama": False})  # type: ignore[arg-type]
    assert release(off, None) == []


@respx.mock
def test_unreachable_ollama_is_not_an_error(release) -> None:  # type: ignore[no-untyped-def]
    respx.get(f"{BASE}/api/ps").mock(side_effect=httpx.ConnectError("refused"))
    settings = Settings(llm={"backends": {"ollama": {"kind": "ollama", "base_url": BASE}}})  # type: ignore[arg-type]
    assert release(settings, None) == []
    assert release(settings, "missing-backend") == []
