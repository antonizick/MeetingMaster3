from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from meetingmaster3.app import create_app
from meetingmaster3.config.settings import BackendConfig, Settings, load_settings
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm import registry as reg_mod
from meetingmaster3.llm.base import (
    ConnectionStatus,
    GenerateRequest,
    GenerateResult,
    LLMBackend,
    ModelInfo,
)
from meetingmaster3.llm.bedrock import BedrockBackend
from meetingmaster3.llm.consent import enforce_consent, requires_consent
from meetingmaster3.llm.doctor import check_backends_async
from meetingmaster3.llm.ollama import OllamaBackend
from meetingmaster3.llm.openai_compat import OpenAICompatBackend
from meetingmaster3.llm.registry import BackendRegistry

KEY = "sk-or-v1-supersecretvalue1234567890"


def settings_with(**backends: BackendConfig) -> Settings:
    s = Settings()
    s.llm.backends = dict(backends)
    s.register_secrets()
    return s


def test_default_is_implicit_local_ollama() -> None:
    reg = BackendRegistry(Settings())
    backend = reg.get()
    assert isinstance(backend, OllamaBackend) and backend.base_url == "http://127.0.0.1:11434"
    assert backend.is_local and not requires_consent(backend)


def test_factories_build_each_kind_and_cache() -> None:
    s = settings_with(
        local=BackendConfig(kind="ollama", base_url="http://gpu-box:11434"),
        or_=BackendConfig(kind="openrouter", api_key=KEY, default_model="x/y"),  # type: ignore[arg-type]
        lm=BackendConfig(kind="openai_compat", base_url="http://localhost:1234/v1"),
        aws=BackendConfig(kind="bedrock", region="eu-west-1", profile="p"),
    )
    reg = BackendRegistry(s)
    assert not reg.get("local").is_local  # remote Ollama
    assert reg.get("or_").is_local is False and isinstance(reg.get("or_"), OpenAICompatBackend)
    assert reg.get("lm").is_local
    aws = reg.get("aws")
    assert isinstance(aws, BedrockBackend) and aws.region == "eu-west-1" and not aws.is_local
    assert reg.get("or_") is reg.get("or_")
    s.llm.backends["or_"].default_model = "other"
    assert reg.get("or_").default_model == "other"  # type: ignore[attr-defined]


def test_errors_for_unknown_name_kind_and_missing_url() -> None:
    reg = BackendRegistry(
        settings_with(x=BackendConfig(kind="nope"), y=BackendConfig(kind="openai_compat"))
    )
    for name, code in (
        ("zzz", "E_LLM_UNKNOWN_BACKEND"),
        ("x", "E_LLM_CONFIG"),
        ("y", "E_LLM_CONFIG"),
    ):
        with pytest.raises(MM3Error) as exc:
            reg.get(name)
        assert exc.value.code == code


def test_preset_key_falls_back_to_secrets_section() -> None:
    s = Settings()
    s.secrets.openrouter_api_key = SecretStr(KEY)
    s.llm.backends = {"or": BackendConfig(kind="openrouter")}
    backend = BackendRegistry(s).get("or")
    assert backend._headers["Authorization"] == f"Bearer {KEY}"  # type: ignore[attr-defined]


# -- a fourth backend needs only a class and a registry entry ---------------------------------


class EchoBackend:
    kind, is_local = "echo", True

    def __init__(self, id: str) -> None:
        self.id = id

    async def generate(self, req: GenerateRequest) -> GenerateResult:
        return GenerateResult(text=f"echo:{req.chat()[-1].content}", model=req.model)

    async def stream(self, req: GenerateRequest) -> AsyncIterator[str]:
        yield "echo"

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo("e")]

    async def test_connection(self) -> ConnectionStatus:
        return ConnectionStatus(True, "fine")

    def context_window(self, model: str) -> int | None:
        return 1000

    async def warm(self, model: str) -> None:
        return None


async def test_fourth_backend_plugs_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(reg_mod._FACTORIES, "echo", lambda name, cfg, s: EchoBackend(name))
    reg = BackendRegistry(settings_with(e=BackendConfig(kind="echo")))
    backend: LLMBackend = reg.get("e")
    assert isinstance(backend, LLMBackend)
    assert (await backend.generate(GenerateRequest(model="m", prompt="yo"))).text == "echo:yo"
    assert reg.describe("e")["badge"] == "local"


# -- consent ------------------------------------------------------------------------------------


def test_consent_enforcement() -> None:
    cloud = OpenAICompatBackend("or", "https://openrouter.ai/api/v1")
    local = OllamaBackend("o")
    enforce_consent(local, cloud_consent=False)
    with pytest.raises(MM3Error) as exc:
        enforce_consent(cloud, cloud_consent=False)
    assert exc.value.code == "E_CONSENT_REQUIRED" and exc.value.status_code == 403
    enforce_consent(cloud, cloud_consent=True)
    enforce_consent(cloud, cloud_consent=False, remembered=True)
    with pytest.raises(MM3Error):
        enforce_consent(BedrockBackend("b"), cloud_consent=False)


# -- secrets & API ---------------------------------------------------------------------------


@pytest.fixture
def api() -> TestClient:
    s = settings_with(
        or_=BackendConfig(kind="openrouter", api_key=KEY, default_model="v/m"),  # type: ignore[arg-type]
    )
    return TestClient(create_app(s), base_url="http://localhost")


def test_backends_listing_masks_keys(api: TestClient) -> None:
    r = api.get("/api/llm/backends")
    assert r.status_code == 200
    assert KEY not in r.text
    by_name = {b["name"]: b for b in r.json()["backends"]}
    assert (
        by_name["or_"]["api_key"] == "********" and by_name["or_"]["badge"] == "cloud: openrouter"
    )
    assert by_name["or_"]["requires_consent"] is True
    assert by_name["ollama"]["is_local"] is True and by_name["ollama"]["is_default"] is True


@respx.mock
def test_test_and_models_endpoints(api: TestClient) -> None:
    respx.get("https://openrouter.ai/api/v1/models").respond(
        json={"data": [{"id": "v/m", "context_length": 32000}]}
    )
    token = api.get("/healthz").cookies["mm3_csrf"]
    r = api.post(
        "/api/llm/backends/or_/test", headers={"X-CSRF-Token": token, "Origin": "http://localhost"}
    )
    assert r.status_code == 200 and r.json()["ok"] and r.json()["default_model_present"] is True
    models = api.get("/api/llm/backends/or_/models").json()["models"]
    assert len(models) == 1
    assert {k: models[0][k] for k in ("id", "context_window", "size_bytes", "can_generate")} == {
        "id": "v/m",
        "context_window": 32000,
        "size_bytes": None,
        "can_generate": None,
    }
    assert models[0]["usable"] is True and models[0]["price_in"] is None


def test_unknown_backend_is_404_with_code(api: TestClient) -> None:
    r = api.get("/api/llm/backends/nope/models")
    assert r.status_code == 404 and r.json()["code"] == "E_LLM_UNKNOWN_BACKEND"


def test_test_endpoint_requires_csrf(api: TestClient) -> None:
    assert api.post("/api/llm/backends/or_/test").status_code == 403


def test_recommendations_have_cloud_entries_without_prices_in_the_generic_list(
    api: TestClient,
) -> None:
    data = api.get("/api/llm/recommendations").json()
    assert data["cloud"] and all(
        {"capability", "cost_tier", "privacy_note", "pricing_url"} <= set(c) for c in data["cloud"]
    )
    assert "$" not in json.dumps(data["cloud"])
    assert data["local"] is None or "models" in data["local"]


def test_config_round_trip_keeps_key_but_masks_dump(tmp_path: Path) -> None:
    s = settings_with(or_=BackendConfig(kind="openrouter", api_key=KEY))  # type: ignore[arg-type]
    assert KEY not in json.dumps(s.dump_masked())
    path = s.save(tmp_path / "config.yaml")
    assert path.stat().st_mode & 0o777 == 0o600
    assert KEY in path.read_text()
    again = load_settings(path)
    assert again.llm.backends["or_"].api_key.get_secret_value() == KEY  # type: ignore[union-attr]


def test_key_is_redacted_from_logs(caplog: pytest.LogCaptureFixture) -> None:
    from meetingmaster3.logging import redact

    settings_with(or_=BackendConfig(kind="openrouter", api_key=KEY))  # type: ignore[arg-type]
    assert KEY not in redact(f"request failed with key {KEY}")


# -- doctor -------------------------------------------------------------------------------------


@respx.mock
async def test_doctor_checks_each_backend() -> None:
    respx.get("http://127.0.0.1:11434/api/tags").respond(json={"models": [{"name": "qwen3:4b"}]})
    respx.get("https://openrouter.ai/api/v1/models").respond(401)
    s = settings_with(
        ollama=BackendConfig(kind="ollama", default_model="gone:1"),
        or_=BackendConfig(kind="openrouter", api_key=KEY),  # type: ignore[arg-type]
    )
    checks = {c.name: c for c in await check_backends_async(s)}
    assert (
        checks["LLM ollama (local)"].status == "warn"
        and "ollama pull" in checks["LLM ollama (local)"].hint
    )
    assert checks["LLM or_ (cloud)"].status == "warn"
