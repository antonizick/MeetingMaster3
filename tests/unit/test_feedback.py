"""Feedback ratings: storage, API, export and the widget."""

from __future__ import annotations

import csv
import io
import json

import pytest
from fastapi.testclient import TestClient

from meetingmaster3.errors import MM3Error
from meetingmaster3.feedback.store import FeedbackStore, to_csv
from meetingmaster3.storage.db import Database

MM3 = "5f1f7b6e-0000-4000-8000-000000000001"


@pytest.fixture
def store() -> FeedbackStore:
    return FeedbackStore(Database.open(":memory:"))


def test_add_and_read_back(store: FeedbackStore) -> None:
    fb = store.add(MM3, rating_kind="stars", value=4, comment="  good  ", template_id="t",
                   backend="ollama", model="qwen3:8b")  # fmt: skip
    assert fb.comment == "good" and fb.section_id is None and fb.created_at.endswith("+00:00")
    assert store.latest(MM3) == fb
    assert store.for_meeting(MM3) == [fb]


def test_a_new_rating_replaces_the_old_one_per_section(store: FeedbackStore) -> None:
    store.add(MM3, rating_kind="stars", value=2)
    store.add(MM3, rating_kind="stars", value=5)
    store.add(MM3, rating_kind="thumbs", value=1, section_id="summary")
    store.add(MM3, rating_kind="thumbs", value=-1, section_id="summary")
    store.add(MM3, rating_kind="thumbs", value=1, section_id="decisions")
    rows = store.for_meeting(MM3)
    assert sorted((r.section_id or "", r.value) for r in rows) == [
        ("", 5), ("decisions", 1), ("summary", -1),
    ]  # fmt: skip
    latest = store.latest(MM3, "summary")
    assert latest is not None and latest.value == -1


@pytest.mark.parametrize(
    ("kind", "value"), [("stars", 0), ("stars", 6), ("thumbs", 2), ("thumbs", 0), ("mood", 1)]
)
def test_invalid_ratings_are_rejected(store: FeedbackStore, kind: str, value: int) -> None:
    with pytest.raises(MM3Error) as err:
        store.add(MM3, rating_kind=kind, value=value)
    assert err.value.code == "E_FEEDBACK_INVALID"
    assert store.all() == []


def test_comment_is_capped(store: FeedbackStore) -> None:
    assert len(store.add(MM3, rating_kind="stars", value=1, comment="x" * 5000).comment) == 2000


def test_csv_export_neutralises_formulas(store: FeedbackStore) -> None:
    store.add(MM3, rating_kind="stars", value=3, comment='=HYPERLINK("http://x")')
    rows = list(csv.DictReader(io.StringIO(to_csv(store.all()))))
    assert rows[0]["comment"].startswith("'=") and rows[0]["value"] == "3"
    assert list(rows[0]) == [
        "id", "mm3_id", "template_id", "backend", "model", "section_id", "rating_kind",
        "value", "comment", "created_at",
    ]  # fmt: skip


def test_api_round_trip_and_export(ui: TestClient) -> None:
    r = ui.post(
        "/api/feedback",
        json={"mm3_id": MM3, "rating_kind": "stars", "value": 5, "comment": "great",
              "template_id": "executive-summary"},
    )  # fmt: skip
    assert r.status_code == 201 and r.json()["value"] == 5
    ui.post("/api/feedback", json={"mm3_id": MM3, "rating_kind": "thumbs", "value": -1,
                                   "section_id": "summary"})  # fmt: skip
    assert len(ui.get("/api/feedback", params={"mm3_id": MM3}).json()["feedback"]) == 2

    exported = ui.get("/api/feedback/export")
    assert exported.headers["content-disposition"].startswith("attachment")
    assert len(exported.json()["feedback"]) == 2
    csv_text = ui.get("/api/feedback/export", params={"format": "csv"}).text
    assert csv_text.splitlines()[0].startswith("id,mm3_id") and "great" in csv_text
    assert ui.get("/api/feedback/export", params={"format": "xml"}).status_code == 422

    bad = ui.post("/api/feedback", json={"mm3_id": MM3, "rating_kind": "stars", "value": 9})
    assert bad.status_code == 422
    unknown = ui.post("/api/feedback", json={"mm3_id": MM3, "rating_kind": "stars", "value": 1,
                                             "extra": 1})  # fmt: skip
    assert unknown.status_code == 422


def test_widget_saves_and_shows_the_current_rating(ui: TestClient) -> None:
    form = {"mm3_id": MM3, "kind": "stars", "template_id": "t", "backend": "ollama",
            "model": "m", "section_id": "", "comment": "ok"}  # fmt: skip
    r = ui.post("/ui/feedback", data={**form, "value": "4"})
    assert "Thanks, saved on this computer." in r.text
    assert r.text.count('aria-pressed="true"') == 4
    assert ">ok</textarea>" in r.text
    section = ui.post("/ui/feedback", data={**form, "section_id": "summary", "value": "-1"})
    assert 'name="section_id" value="summary"' in section.text
    stored = ui.get("/api/feedback", params={"mm3_id": MM3}).json()["feedback"]
    assert {(f["section_id"], f["rating_kind"], f["value"]) for f in stored} == {
        (None, "stars", 4), ("summary", "thumbs", -1),
    }  # fmt: skip
    assert ui.post("/ui/feedback", data={**form, "value": "x"}).status_code == 422
    assert json.dumps(stored)  # serialisable


def test_feedback_table_exists_after_migration() -> None:
    db = Database.open(":memory:")
    cols = {r["name"] for r in db.fetchall("PRAGMA table_info(feedback)")}
    assert {"mm3_id", "template_id", "backend", "model", "section_id", "rating_kind", "value",
            "comment", "created_at"} <= cols  # fmt: skip
