from __future__ import annotations

import datetime as dt

from meetingmaster3.jobs.retention import RetentionStatus
from meetingmaster3.review.retention_view import describe

T = dt.datetime(2027, 1, 13, 12, tzinfo=dt.UTC)


def test_pinned_offers_allow_deletion() -> None:
    undo = RetentionStatus("expires", T, 23)
    view = describe(RetentionStatus("kept_pinned"), undo=undo)
    assert view and view.text == "Recording kept forever."
    assert view.action == "release" and view.button == "Allow deletion"
    assert view.undo_text.startswith("The recording will be deleted in 23 days (")


def test_days_singular_and_plural_and_date() -> None:
    one = describe(RetentionStatus("expires", T, 1))
    many = describe(RetentionStatus("expires", T, 23))
    assert one and "in 1 day (" in one.text and "1 days" not in one.text
    assert many and "in 23 days (" in many.text and "2027" in many.text
    assert many.action == "keep" and many.button == "Keep forever" and many.settings_link


def test_due_and_undo_when_already_late() -> None:
    due = describe(RetentionStatus("due", T, 0))
    assert due and "at the next check" in due.text and due.action == "keep"
    pinned = describe(RetentionStatus("kept_pinned"), undo=RetentionStatus("due", T, 0))
    assert pinned and "at the next check" in pinned.undo_text


def test_forever_setting_still_offers_keep() -> None:
    view = describe(RetentionStatus("kept_setting"))
    assert view and "retention setting keeps recordings forever" in view.text
    assert view.action == "keep"


def test_nothing_to_show_without_audio() -> None:
    assert describe(RetentionStatus("none")) is None
