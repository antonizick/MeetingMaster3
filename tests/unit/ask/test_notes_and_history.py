"""Answer notes in the vault, the scanners that must ignore them, renames, and the answer history
(Phase 15j)."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from meetingmaster3.ask import notes
from meetingmaster3.ask.pipeline import AskResult
from meetingmaster3.ask.service import AskService
from meetingmaster3.ask.store import AnswerRecord
from meetingmaster3.errors import MM3Error
from meetingmaster3.llm.fake import FakeLLMBackend
from meetingmaster3.markdown.frontmatter import render_frontmatter, split_frontmatter
from meetingmaster3.review.retitle import apply_retitle, plan_retitle
from meetingmaster3.search.index import indexable
from meetingmaster3.search.service import SearchService
from meetingmaster3.storage.db import Database
from meetingmaster3.vault.picker import browse, read_identity
from meetingmaster3.vault.relink import index_vault
from tests import ask_corpus as ac
from tests.search_corpus import MEETINGS_DIR
from tests.unit.ask.conftest import Script, plan_reply, read_by_title

FOUND: dict[str, dict[str, Any]] = {
    "Q3 Finance Review": {
        "relevant": "yes",
        "finding": "A 12 percent budget overrun | contractor fees.",
        "people": [{"name": "Dana Whitfield", "role": "CFO | <i>finance</i>"}],
        "quotes": [{"text": "We are twelve percent over budget this quarter."}],
    },
    "Platform Weekly": {"relevant": "partly", "finding": "Hosting costs.", "people": []},
}


async def _answer(
    ask: AskService, llm: FakeLLMBackend, question: str = "Budget overrun?"
) -> tuple[AskResult, AnswerRecord]:
    llm.responder = Script(
        plan=plan_reply("budget overrun", "spending more than planned"),
        read=read_by_title(FOUND),
        answer=lambda p: "Two meetings: [[2026-09-02 - Q3 Finance Review]].",
    )
    result, record = await ask.ask(question)
    assert record is not None and record.vault_path is not None
    return result, record


async def test_the_answer_note(ask: AskService, llm: FakeLLMBackend, ask_vault: Path) -> None:
    result, record = await _answer(ask, llm, 'How did the "budget" go: over/under? <b>x</b>')
    path = ask_vault / str(record.vault_path)
    assert str(record.vault_path).startswith("MM3 Answers/")
    assert (
        path.name
        == f"{result.started_at:%Y-%m-%d %H%M} - How did the budget go over under b x b.md"
    )
    fm, body = split_frontmatter(path.read_text(encoding="utf-8"))
    assert fm is not None
    data = fm.data
    assert data["mm3-kind"] == "answer" and data["mm3-answer-id"] == record.id
    assert "mm3-id" not in data
    assert data["question"] == 'How did the "budget" go: over/under? <b>x</b>'
    assert data["mm3-sources"] == [
        "[[2026-09-02 - Q3 Finance Review]]",
        "[[2026-09-09 - Platform Weekly]]",
    ]
    assert data["tags"] == ["mm3/answer"] and data["mm3-model"] == "fake-model"
    assert dt.datetime.fromisoformat(str(data["asked"])).tzinfo is not None
    assert "## Answer" in body and "## Meetings" in body and "## Sources" in body
    assert (
        "| 2026-09-02 | [[2026-09-02 - Q3 Finance Review]] | Dana Whitfield, Raj Patel, Mei Lin"
        in body
    )
    assert "[[2026-09-09 - Platform Weekly]] (briefly)" in body
    assert "Dana Whitfield: CFO \\| &lt;i>finance&lt;/i> |" in body  # no broken table, no HTML
    assert '# How did the "budget" go: over/under? &lt;b>x&lt;/b>' in body
    finance = ac.by_key("finance")
    assert f"](http://127.0.0.1:8765/meetings/{finance.id}?path=" in body and "#t=0)" in body
    assert "## How this was answered" in body and "“budget overrun”" in body
    assert os.stat(path).st_mode & 0o777 != 0  # written


async def test_collisions_get_a_counter_and_nothing_is_overwritten(
    ask: AskService, llm: FakeLLMBackend, ask_vault: Path
) -> None:
    result, first = await _answer(ask, llm)
    before = (ask_vault / str(first.vault_path)).read_bytes()
    second = ask.save(result)
    third = ask.save(result)
    assert str(second.vault_path).endswith(" (2).md")
    assert str(third.vault_path).endswith(" (3).md")
    assert (ask_vault / str(first.vault_path)).read_bytes() == before


def test_the_answers_folder_is_confined(tmp_path: Path) -> None:
    root = tmp_path / "v"
    root.mkdir()
    with pytest.raises(MM3Error):
        notes.answers_folder(root.resolve(), "../outside")
    assert not (tmp_path / "outside").exists()


async def test_scanners_and_the_index_ignore_answer_notes(
    ask: AskService, llm: FakeLLMBackend, ask_vault: Path, search: SearchService
) -> None:
    _, record = await _answer(ask, llm)
    path = ask_vault / str(record.vault_path)
    assert read_identity(path) is None
    assert indexable(read_identity(path), path.name, transcripts=True) is None
    listing = browse(ask_vault, "MM3 Answers")
    assert [e for e in listing.entries if e.kind == "note"] == []
    vault = index_vault(ask_vault)
    live = [str(p) for paths in (*vault.notes.values(), *vault.transcripts.values()) for p in paths]
    assert not any("MM3 Answers" in p for p in live)
    report = await search.update_now()
    assert report is not None and report.added == 0  # the answer was not indexed
    assert search.status()["meetings"] == len(ac.MEETINGS)


async def test_renaming_a_meeting_keeps_the_citations_valid(
    ask: AskService, llm: FakeLLMBackend, ask_vault: Path, tmp_path: Path, db: Database
) -> None:
    _, record = await _answer(ask, llm)
    note = ask_vault / MEETINGS_DIR / f"{ac.by_key('finance').stem}.md"
    plan = plan_retitle(ask_vault, note, title="Q3 Spending Review")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    apply_retitle(plan, data_dir=tmp_path / "data", db=db, jobs_root=jobs)
    text = (ask_vault / str(record.vault_path)).read_text(encoding="utf-8")
    assert "[[2026-09-02 - Q3 Finance Review]]" not in text
    assert text.count("[[2026-09-02 - Q3 Spending Review]]") >= 3  # sources, table, list
    fm, _ = split_frontmatter(text)
    assert fm is not None and "[[2026-09-02 - Q3 Spending Review]]" in fm.data["mm3-sources"]


async def test_history_lists_cites_moves_and_deletes(
    ask: AskService, llm: FakeLLMBackend, ask_vault: Path
) -> None:
    _, record = await _answer(ask, llm)
    assert ask.store.count() == 1
    assert [r.id for r in ask.store.recent()] == [record.id]
    finance, release = ac.by_key("finance"), ac.by_key("release")
    assert [r.id for r in ask.citing(str(finance.id))] == [record.id]
    assert ask.citing(str(release.id)) == []
    got = ask.store.get(record.id)
    assert got is not None and got.relevant == 2 and got.sources[0].finding

    # moved in Obsidian: re-found by its answer id, and the history follows it
    old = ask_vault / str(record.vault_path)
    moved = ask_vault / "Elsewhere" / "renamed answer.md"
    moved.parent.mkdir()
    old.rename(moved)
    located = ask.locate(record.id)
    assert located.path == moved and located.moved
    assert ask.store.get(record.id).vault_path == "Elsewhere/renamed answer.md"  # type: ignore[union-attr]

    # delete removes the note and the row
    assert ask.delete(record.id) is True
    assert not moved.exists() and ask.store.get(record.id) is None
    assert ask.citing(str(finance.id)) == []


async def test_a_missing_note_is_reported_and_can_be_forgotten(
    ask: AskService, llm: FakeLLMBackend, ask_vault: Path
) -> None:
    _, record = await _answer(ask, llm)
    (ask_vault / str(record.vault_path)).unlink()
    located = ask.locate(record.id)
    assert located.path is None
    ask.forget(record.id)
    assert ask.store.get(record.id) is None


async def test_delete_refuses_a_file_that_is_not_the_answer(
    ask: AskService, llm: FakeLLMBackend, ask_vault: Path
) -> None:
    _, record = await _answer(ask, llm)
    path = ask_vault / str(record.vault_path)
    text = path.read_text(encoding="utf-8").replace(
        record.id, "00000000-0000-4000-8000-0000000000ff"
    )
    path.write_text(text, encoding="utf-8")
    with pytest.raises(MM3Error):
        notes.delete_answer_note(ask_vault, path, record.id)
    assert path.exists()


async def test_keep_history_off_saves_nothing(
    ask: AskService, llm: FakeLLMBackend, ask_vault: Path
) -> None:
    ask.settings.ask.keep_history = False
    llm.responder = Script(plan=plan_reply("budget overrun"), read=read_by_title(FOUND))
    result, record = await ask.ask("Budget overrun?")
    assert record is None and result.count == 2
    assert not (ask_vault / "MM3 Answers").exists() and ask.store.count() == 0


async def test_a_follow_up_carries_the_earlier_findings(
    ask: AskService, llm: FakeLLMBackend
) -> None:
    _, first = await _answer(ask, llm)
    llm.calls.clear()
    _, second = await ask.ask("And who should fix it?", previous_id=first.id)
    plan_prompt = "\n".join(m.content for m in llm.calls[0].chat())
    assert "This question follows an earlier one: Budget overrun?" in plan_prompt
    assert "A 12 percent budget overrun" in plan_prompt
    assert second is not None and second.parent_id == first.id


def test_frontmatter_of_a_question_with_yaml_specials_round_trips(tmp_path: Path) -> None:
    question = "key: value - [x] #tag 'quote' \"dq\" {a: b}"
    text = render_frontmatter({"question": question}).strip()
    assert yaml.safe_load(text.strip("-\n"))["question"] == question
