"""Progress and time-left maths, and the long-task registry (Phase 15c, R27)."""

from __future__ import annotations

import asyncio

import pytest

from meetingmaster3.errors import MM3Error
from meetingmaster3.review import progress as p
from meetingmaster3.web import views


def test_estimate_is_used_before_the_rate_can_be_measured() -> None:
    e = p.eta(elapsed=10, fraction=0.0, expected_s=120, smoothed=None)
    assert (e.kind, e.remaining_s) == ("estimate", 110)
    # One early section is still too little to measure from.
    assert p.smooth_total(None, elapsed=3, fraction=0.02) is None


def test_measured_rate_replaces_the_estimate() -> None:
    total = p.smooth_total(None, elapsed=60, fraction=0.25)
    assert total == 240
    e = p.eta(elapsed=60, fraction=0.25, expected_s=120, smoothed=total)
    assert (e.kind, e.remaining_s) == ("measured", 180)


def test_smoothing_does_not_jump_about() -> None:
    total: float | None = 200.0
    total = p.smooth_total(total, elapsed=100, fraction=0.25)  # measured 400
    assert total == pytest.approx(0.6 * 200 + 0.4 * 400)
    assert total is not None and 200 < total < 400


def test_never_zero_while_work_remains() -> None:
    late = p.eta(elapsed=130, fraction=0.5, expected_s=120, smoothed=None)
    assert (late.kind, late.remaining_s) == ("overrun", None)
    almost = p.eta(elapsed=99.5, fraction=0.9, expected_s=None, smoothed=100)
    assert almost.kind == "overrun"
    assert p.eta(elapsed=5, fraction=1.0, expected_s=None, smoothed=None).kind == "measured"


def test_no_figure_without_an_estimate_or_measurement() -> None:
    assert p.eta(elapsed=4, fraction=0.0, expected_s=None, smoothed=None) == p.Eta("none", None)
    assert p.expected_seconds(None) is None
    assert p.expected_seconds((60, 180)) == 120


def test_snapshot_reports_step_elapsed_and_eta() -> None:
    now = [100.0]
    task = p.LongTask("t", "switch", "m", clock=lambda: now[0])
    task.expected_s = 90
    task.set_step(3, 9, "Summary Detailed")
    now[0] = 130.0
    task.update(1 / 3, "Writing Summary Detailed")
    snap = task.snapshot()
    assert (snap["step"], snap["steps"], snap["step_title"]) == (3, 9, "Summary Detailed")
    assert snap["elapsed_s"] == 30 and snap["fraction"] == pytest.approx(0.3333, abs=1e-4)
    assert snap["eta"] == "measured" and snap["remaining_s"] == pytest.approx(60, abs=0.5)
    task.update(0.1, "late message")  # a lower fraction never moves the bar backwards
    assert task.fraction == pytest.approx(1 / 3)


@pytest.mark.parametrize(
    ("size", "text"),
    [(0, "0 B"), (999, "999 B"), (1000, "1.0 kB"), (12_400_000, "12.4 MB"), (41_234_567, "41.2 MB"),
     (3_100_000_000, "3.1 GB")],
)  # fmt: skip
def test_format_size_decimal_units(size: int, text: str) -> None:
    assert views.format_size(size) == text


def test_download_name_uses_the_note_stem_safely() -> None:
    assert views.audio_download_name("2026-10-11 - Product Sync", ".opus") == (
        "2026-10-11 - Product Sync.opus"
    )
    assert views.audio_download_name("2026-10-11 - Café ☕ Q&A", ".wav") == (
        "2026-10-11 - Café ☕ Q&A.wav"
    )
    bad = views.audio_download_name('a/b\\c:d*e?"f<g>h|i\r\nX', ".opus")
    assert not any(c in bad for c in '/\\:*?"<>|\r\n') and bad.endswith(".opus")
    assert len(views.audio_download_name("x" * 1000, ".opus").encode()) < 260
    assert views.audio_download_name("note", ".o/../x") == "note"  # a hostile suffix is dropped


# -- the registry ----------------------------------------------------------------------------------


async def test_a_task_runs_finishes_and_keeps_its_result() -> None:
    registry = p.TaskRegistry()

    async def work(task: p.LongTask) -> str:
        task.update(0.5, "half")
        return "result"

    task = registry.start("m1", "switch", work)
    assert registry.for_note("m1") is task
    assert task.runner is not None
    await task.runner
    assert (task.state, task.result, task.fraction) == (p.TaskState.DONE, "result", 1.0)
    assert registry.get(task.id) is task  # still there for a reloaded page


async def test_second_start_while_running_is_refused_then_allowed() -> None:
    registry = p.TaskRegistry()
    gate = asyncio.Event()

    async def work(task: p.LongTask) -> None:
        await gate.wait()

    first = registry.start("m1", "switch", work)
    with pytest.raises(MM3Error) as exc:
        registry.start("m1", "regenerate", work)
    assert exc.value.code == "E_TASK_RUNNING" and exc.value.status_code == 409
    registry.start("m2", "switch", work)  # another note is independent
    gate.set()
    assert first.runner is not None
    await first.runner
    again = registry.start("m1", "switch", work)
    assert registry.get(first.id) is None and registry.for_note("m1") is again
    await asyncio.sleep(0)


async def test_cancel_interrupts_a_running_task() -> None:
    registry = p.TaskRegistry()

    async def work(task: p.LongTask) -> None:
        await asyncio.sleep(60)

    task = registry.start("m1", "switch", work)
    await asyncio.sleep(0)
    await registry.cancel(task)
    assert task.state is p.TaskState.CANCELLED and task.snapshot()["eta"] == "none"
    await registry.cancel(task)  # a finished task is dismissed
    assert registry.get(task.id) is None


async def test_failures_are_kept_with_code_and_hint() -> None:
    registry = p.TaskRegistry()

    async def mm3(task: p.LongTask) -> None:
        raise MM3Error("E_X", "nope", "try y")

    async def boom(task: p.LongTask) -> None:
        raise RuntimeError("kaput")

    one = registry.start("m1", "switch", mm3)
    assert one.runner is not None
    await one.runner
    assert one.state is p.TaskState.FAILED
    assert one.snapshot()["error"] == {"code": "E_X", "message": "nope", "hint": "try y"}
    two = registry.start("m2", "switch", boom)
    assert two.runner is not None
    await two.runner
    assert two.error is not None and two.error.code == "E_TASK_FAILED"


async def test_old_finished_tasks_are_pruned() -> None:
    now = [0.0]
    registry = p.TaskRegistry(clock=lambda: now[0])

    async def work(task: p.LongTask) -> None:
        return None

    old = registry.start("m1", "switch", work)
    assert old.runner is not None
    await old.runner
    now[0] += p.KEEP_FINISHED_S + 1
    registry.start("m2", "switch", work)
    assert registry.get(old.id) is None
