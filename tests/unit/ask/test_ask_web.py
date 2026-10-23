"""The Ask-AI page, answer views, the review page's answers and the consent switch (Phase 15j)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from meetingmaster3.app import create_app
from meetingmaster3.ask.store import AnswerRecord
from meetingmaster3.config.settings import BackendConfig, Settings
from meetingmaster3.llm import fake as fake_module
from meetingmaster3.llm.base import GenerateRequest, GenerateResult
from tests import ask_corpus as ac
from tests.search_corpus import MEETINGS_DIR

SENT: list[GenerateRequest] = []


@pytest.fixture
def aui(ask_vault: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MM3_FAKE_PIPELINE", "1")
    monkeypatch.setenv("MM3_FAKE_STAGE_SECONDS", "0")
    monkeypatch.delenv("MM3_SEARCH__ENABLED", raising=False)
    monkeypatch.setattr("meetingmaster3.search.service.DEBOUNCE_S", 0.01)
    SENT.clear()
    original = fake_module.FakeLLMBackend.generate

    async def recording(self: Any, req: GenerateRequest) -> GenerateResult:
        SENT.append(req)
        return await original(self, req)

    monkeypatch.setattr(fake_module.FakeLLMBackend, "generate", recording)
    settings = Settings()
    settings.vault.path = ask_vault
    settings.llm.backends["ollama"] = BackendConfig(kind="ollama", default_model="fake-model")
    settings.llm.backends["router"] = BackendConfig(
        kind="openrouter", api_key="sk-or-test", default_model="cloud-model"
    )
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        client.get("/healthz")
        client.headers["X-CSRF-Token"] = client.cookies["mm3_csrf"]
        _wait_indexed(client, len(ac.MEETINGS))
        yield client


def _wait_indexed(client: TestClient, meetings: int, timeout: float = 15.0) -> None:
    service = client.app.state.search  # type: ignore[attr-defined]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = service.status()
        if not st["running"] and st["meetings"] >= meetings and st["vectors_complete"]:
            return
        time.sleep(0.05)
    raise AssertionError(f"index not ready: {service.status()}")


def _wait_task(client: TestClient, task_id: str, timeout: float = 20.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = client.get(f"/ask/task/{task_id}").json()["task"]
        if snap["state"] != "running":
            return snap  # type: ignore[no-any-return]
        time.sleep(0.05)
    raise AssertionError("the question did not finish")


def _ask(client: TestClient, question: str, **body: Any) -> dict[str, Any]:
    r = client.post("/ask/start", json={"question": question, **body})
    assert r.status_code == 200, r.text
    snap = _wait_task(client, r.json()["task"]["id"])
    assert snap["state"] == "done", snap
    return client.get(f"/ask/task/{snap['id']}/result").json()  # type: ignore[no-any-return]


def test_ask_is_in_the_navigation_and_the_page_renders(aui: TestClient) -> None:
    page = aui.get("/ask")
    assert page.status_code == 200
    assert '<a href="/ask" aria-current="page">Ask-AI</a>' in page.text
    assert 'id="ask-q"' in page.text and "No answers yet" in page.text
    assert "Up to 25 meetings are read per question" in page.text
    assert '/static/js/ask.js"' in page.text


def test_the_consent_box_follows_the_backend(aui: TestClient) -> None:
    local = aui.get("/ask/consent", params={"backend": "ollama"})
    assert "Runs on this computer" in local.text and "cloud_consent" not in local.text
    cloud = aui.get("/ask/consent", params={"backend": "router"})
    assert (
        'name="cloud_consent"' in cloud.text and "up to <strong>25 meetings</strong>" in cloud.text
    )
    cfg = aui.app.state.settings.llm.backends["router"]  # type: ignore[attr-defined]
    cfg.consent_remembered = True  # note writing's consent does not cover Ask-AI
    assert 'name="cloud_consent"' in aui.get("/ask/consent", params={"backend": "router"}).text
    cfg.ask_consent_remembered = True
    sticky = aui.get("/ask/consent", params={"backend": "router"})
    assert 'name="cloud_consent"' not in sticky.text and "without asking" in sticky.text


def test_a_cloud_question_without_consent_sends_nothing(aui: TestClient) -> None:
    cfg = aui.app.state.settings.llm.backends["router"]  # type: ignore[attr-defined]
    cfg.consent_remembered = True
    r = aui.post("/ask/start", json={"question": "budget?", "backend": "router"})
    assert r.status_code == 403 and r.json()["code"] == "E_CONSENT_REQUIRED"
    assert SENT == [] and aui.get("/ask/task").json()["task"] is None
    out = _ask(aui, "budget overrun?", backend="router", cloud_consent=True)
    assert out["answer_id"] and SENT
    assert all(req.model == "cloud-model" for req in SENT)


def test_ask_saves_an_answer_and_the_view_links_the_meetings(aui: TestClient) -> None:
    out = _ask(aui, "What did we say about the budget overrun and spending?")
    assert out["url"] == f"/ask/{out['answer_id']}"
    view = aui.get(out["url"])
    assert view.status_code == 200
    finance = ac.by_key("finance")
    note = quote(f"{MEETINGS_DIR}/{finance.stem}.md", safe="")
    assert f'href="/meetings/{finance.id}?path={note}"' in view.text
    assert f'href="/meetings/{finance.id}?path={note}" target="_blank"' not in view.text
    assert "<table>" in view.text and "Open in Obsidian" in view.text
    assert "[[" not in view.text  # every wikilink became a link or plain text
    assert 'href="http://127.0.0.1:8765' not in view.text  # moments link into this app
    page = aui.get("/ask")
    assert out["url"] in page.text and "No answers yet" not in page.text
    # the cited meeting's review page lists the answer
    review = aui.get(
        f"/meetings/{finance.id}", params={"path": f"{MEETINGS_DIR}/{finance.stem}.md"}
    )
    assert "Answers that cite this meeting (1)" in review.text and out["url"] in review.text


def test_a_question_can_be_cancelled(aui: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MM3_FAKE_LLM_SECONDS", "0.3")
    r = aui.post("/ask/start", json={"question": "budget overrun?"})
    task_id = r.json()["task"]["id"]
    again = aui.post("/ask/start", json={"question": "another"})
    assert again.status_code == 409 and again.json()["code"] == "E_ASK_RUNNING"
    snap = aui.post(f"/ask/task/{task_id}/cancel").json()["task"]
    assert snap["state"] == "cancelled"
    assert aui.app.state.ask.store.count() == 0  # type: ignore[attr-defined]


def test_progress_reports_the_steps(aui: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MM3_FAKE_LLM_SECONDS", "0.15")
    task_id = aui.post("/ask/start", json={"question": "budget overrun?"}).json()["task"]["id"]
    seen: set[str] = set()
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        snap = aui.get(f"/ask/task/{task_id}").json()["task"]
        seen.add(snap["message"].split(":")[0])
        if snap["state"] != "running":
            break
        time.sleep(0.03)
    assert any(m.startswith("Reading meeting 1 of") for m in seen), seen
    assert "elapsed_s" in snap and snap["state"] == "done"


def test_the_answer_view_is_sanitised(aui: TestClient, ask_vault: Path) -> None:
    ask = aui.app.state.ask  # type: ignore[attr-defined]
    path = ask_vault / "MM3 Answers" / "evil.md"
    path.parent.mkdir(exist_ok=True)
    answer_id = "11111111-1111-4111-8111-111111111111"
    path.write_text(
        f"---\nmm3-kind: answer\nmm3-answer-id: {answer_id}\n---\n# Q\n\n"
        "<script>alert(1)</script>\n\n[click](javascript:alert(1)) <img src=x onerror=alert(1)>\n",
        encoding="utf-8",
    )
    import datetime as dt

    ask.store.add(
        AnswerRecord(
            answer_id,
            "Q",
            dt.datetime.now().astimezone(),
            "ollama",
            "m",
            "MM3 Answers/evil.md",
            "done",
            1.0,
            None,
            None,
            0,
            None,
            (),
        )
    )
    view = aui.get(f"/ask/{answer_id}")
    assert view.status_code == 200
    assert "<script>alert" not in view.text and "&lt;script&gt;" in view.text
    assert 'href="javascript' not in view.text and "<img src=x" not in view.text


def test_delete_needs_csrf_and_removes_note_and_row(aui: TestClient, ask_vault: Path) -> None:
    out = _ask(aui, "budget overrun?")
    ask = aui.app.state.ask  # type: ignore[attr-defined]
    record = ask.store.get(out["answer_id"])
    note = ask_vault / record.vault_path
    token = aui.headers.pop("X-CSRF-Token")
    assert aui.post(f"/ask/{record.id}/delete").status_code == 403
    assert note.exists()
    aui.headers["X-CSRF-Token"] = token
    r = aui.post(f"/ask/{record.id}/delete")
    assert r.status_code == 204 and r.headers["HX-Redirect"] == "/ask?deleted=1"
    assert not note.exists() and ask.store.get(record.id) is None
    assert aui.get(f"/ask/{record.id}").status_code == 404


def test_a_missing_note_offers_forget(aui: TestClient, ask_vault: Path) -> None:
    out = _ask(aui, "budget overrun?")
    ask = aui.app.state.ask  # type: ignore[attr-defined]
    record = ask.store.get(out["answer_id"])
    (ask_vault / record.vault_path).unlink()
    view = aui.get(out["url"])
    assert "File not found." in view.text and f"/ask/{record.id}/forget" in view.text
    assert aui.post(f"/ask/{record.id}/forget").status_code == 204
    assert ask.store.get(record.id) is None


def test_ask_again_and_follow_up_prefill_the_form(aui: TestClient) -> None:
    out = _ask(aui, "budget overrun?")
    again = aui.get("/ask", params={"again": out["answer_id"]})
    assert ">budget overrun?</textarea>" in again.text
    follow = aui.get("/ask", params={"follow": out["answer_id"]})
    assert "Follow-up to:" in follow.text and f'value="{out["answer_id"]}"' in follow.text


def test_search_off_refuses_to_start(aui: TestClient) -> None:
    aui.app.state.settings.search.enabled = False  # type: ignore[attr-defined]
    r = aui.post("/ask/start", json={"question": "budget?"})
    assert r.status_code == 409 and r.json()["code"] == "E_SEARCH_OFF"
    assert "Search is switched off" in aui.get("/ask").text


def test_backend_form_saves_and_revokes_the_ask_switch(aui: TestClient) -> None:
    form = {"orig_name": "router", "name": "router", "kind": "openrouter",
            "ask_consent_remembered": "1"}  # fmt: skip
    assert aui.post("/settings/llm/save", data=form).status_code == 200
    cfg = aui.app.state.settings.llm.backends["router"]  # type: ignore[attr-defined]
    assert cfg.ask_consent_remembered is True and cfg.consent_remembered is False
    edit = aui.get("/settings/llm/router/edit")
    assert "Always allow Ask-AI to send meeting excerpts to this backend" in edit.text
    aui.post("/settings/llm/router/revoke-consent")
    assert cfg.ask_consent_remembered is False


def test_the_settings_tab_saves_the_ask_section(aui: TestClient) -> None:
    form = {
        "search.enabled": "1", "search.embedding_backend": "auto",
        "search.embedding_model": "nomic-embed-text", "search.index_transcripts": "1",
        "search.chunk_tokens": "350", "search.chunk_overlap": "50", "search.rescan_minutes": "10",
        "ask.default_backend": "router", "ask.default_model": "", "ask.max_meetings": "7",
        "ask.answers_subfolder": "Answers/AI/",
    }  # fmt: skip
    page = aui.post("/settings/search", data=form)
    assert "Saved" in page.text
    s = aui.app.state.settings  # type: ignore[attr-defined]
    assert s.ask.default_backend == "router" and s.ask.max_meetings == 7
    assert s.ask.keep_history is False and s.ask.answers_subfolder == "Answers/AI/"
    form["ask.answers_subfolder"] = "../outside"
    bad = aui.post("/settings/search", data=form)
    assert "outside" in bad.text and s.ask.answers_subfolder == "Answers/AI/"


def test_unsaved_answers_are_shown_inline(aui: TestClient) -> None:
    aui.app.state.settings.ask.keep_history = False  # type: ignore[attr-defined]
    out = _ask(aui, "budget overrun?")
    assert out["answer_id"] is None and "<table>" in out["html"]
    assert aui.app.state.ask.store.count() == 0  # type: ignore[attr-defined]
