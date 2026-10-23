from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from meetingmaster3.ask.prompts import STEP_MARK
from meetingmaster3.ask.service import AskService
from meetingmaster3.config.settings import BackendConfig, Settings
from meetingmaster3.llm.base import GenerateRequest
from meetingmaster3.llm.fake import FakeLLMBackend, _ask
from meetingmaster3.search.service import SearchService
from meetingmaster3.storage.db import Database
from tests import ask_corpus
from tests.unit.jobs.helpers import make_paths

Reply = Callable[[str], str]


def step_of(req: GenerateRequest) -> str:
    system = req.system_text() or ""
    return system[len(STEP_MARK) :].split("\n", 1)[0] if system.startswith(STEP_MARK) else ""


def prompt_of(req: GenerateRequest) -> str:
    return "\n".join(m.content for m in req.chat())


def meeting_title(prompt: str) -> str:
    return prompt.split("Title: ", 1)[1].split("\n", 1)[0] if "Title: " in prompt else ""


@dataclass
class Script:
    """A responder for the fake backend: per step, a function of the prompt (default: the fake
    model's own Ask-AI answers). Records every call's step."""

    plan: Reply | None = None
    read: Reply | None = None
    answer: Reply | None = None
    steps: list[str] = field(default_factory=list)

    def __call__(self, req: GenerateRequest) -> str:
        step = step_of(req)
        self.steps.append(step)
        prompt = prompt_of(req)
        fn = {"plan": self.plan, "read": self.read, "answer": self.answer}.get(step)
        return fn(prompt) if fn is not None else _ask(step, prompt)


def plan_reply(*queries: str, **extra: Any) -> Reply:
    return lambda prompt: json.dumps({"queries": list(queries), **extra})


def read_by_title(found: dict[str, dict[str, Any]]) -> Reply:
    """Read replies by meeting title; meetings not listed are not relevant."""

    def reply(prompt: str) -> str:
        data = found.get(meeting_title(prompt))
        return json.dumps(data or {"relevant": "no", "finding": "", "people": [], "quotes": []})

    return reply


@pytest.fixture
def ask_vault(tmp_path: Path) -> Path:
    return ask_corpus.write_vault(tmp_path / "vault")


@pytest.fixture
def ask_settings(ask_vault: Path) -> Settings:
    s = Settings()
    s.vault.path = ask_vault
    s.search.enabled = True
    s.llm.backends["ollama"] = BackendConfig(kind="ollama", default_model="fake-model")
    s.llm.backends["router"] = BackendConfig(kind="openrouter", default_model="cloud-model")
    return s


@pytest.fixture
def embed_fake() -> FakeLLMBackend:
    return FakeLLMBackend(id="ollama", kind="ollama")


@pytest.fixture
def llm() -> FakeLLMBackend:
    return FakeLLMBackend(id="ollama", kind="ollama", window=16384)


@pytest.fixture
def cloud_llm() -> FakeLLMBackend:
    return FakeLLMBackend(id="router", kind="openrouter", is_local=False, window=200_000)


@pytest.fixture
async def search(
    ask_settings: Settings, tmp_path: Path, embed_fake: FakeLLMBackend
) -> AsyncIterator[SearchService]:
    paths = make_paths(tmp_path / "data")
    paths.ensure()
    service = SearchService(ask_settings, paths, lambda: ["ollama"], lambda n: embed_fake)
    await service.update_now()
    yield service
    await service.stop()


@pytest.fixture
def db(tmp_path: Path) -> Database:
    return Database.open(tmp_path / "data" / "mm3.db")


@pytest.fixture
def ask(
    ask_settings: Settings,
    db: Database,
    search: SearchService,
    llm: FakeLLMBackend,
    cloud_llm: FakeLLMBackend,
) -> AskService:
    backends = {"ollama": llm, "router": cloud_llm}
    return AskService(ask_settings, db, search, backends.__getitem__, lambda: list(backends))
