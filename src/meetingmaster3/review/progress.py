"""Long-running review actions as background tasks with honest progress (Phase 15c, R27).

A template switch (and a section regeneration) can take minutes with a local model. Instead of
one blocking request, the action runs as an in-memory :class:`LongTask`; the page polls its
snapshot (fraction, step, elapsed, time left) and fetches the result when it is done. A task
survives a page reload (the page reattaches to it) but not a server restart: state is small,
per note, and never written to disk.

The time-left figure comes from :func:`eta`: the hardware profile's estimate until the generator
has finished enough of the work to measure its own rate, then the measured rate, smoothed so it
does not jump about. It never shows 0:00 while work remains: past the estimate it says so.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

from meetingmaster3.errors import MM3Error

MIN_FRACTION = 0.05
"""Below this the measured rate (elapsed / fraction) is too noisy to use."""
SMOOTHING = 0.4
"""Weight of the newest measurement in the smoothed total."""
OVERRUN_GRACE_S = 1.0
KEEP_FINISHED_S = 3600.0

EtaKind = Literal["none", "estimate", "measured", "overrun"]


class TaskState(StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


def smooth_total(previous: float | None, elapsed: float, fraction: float) -> float | None:
    """The new smoothed estimate of the total run time, given the work done so far."""
    if fraction < MIN_FRACTION:
        return previous
    measured = elapsed / min(fraction, 1.0)
    if previous is None:
        return measured
    return (1 - SMOOTHING) * previous + SMOOTHING * measured


@dataclass(frozen=True)
class Eta:
    kind: EtaKind
    remaining_s: float | None


def eta(elapsed: float, fraction: float, expected_s: float | None, smoothed: float | None) -> Eta:
    """Time left. ``estimate`` (from the hardware profile) before the rate can be measured,
    ``measured`` after, ``overrun`` once the estimate has been passed with work remaining, and
    ``none`` when there is nothing to base a figure on (for example a cloud backend)."""
    if fraction >= 1.0:
        return Eta("measured", 0.0)
    if smoothed is not None:
        total, kind = smoothed, "measured"
    elif expected_s is not None:
        total, kind = expected_s, "estimate"
    else:
        return Eta("none", None)
    remaining = total - elapsed
    if remaining <= OVERRUN_GRACE_S:
        return Eta("overrun", None)
    return Eta(kind, remaining)  # type: ignore[arg-type]


def expected_seconds(window: tuple[float, float] | None) -> float | None:
    """The middle of a (low, high) estimate in seconds, or ``None`` if there is none."""
    return None if window is None else (window[0] + window[1]) / 2


@dataclass
class LongTask:
    id: str
    kind: str
    mm3_id: str
    clock: Callable[[], float] = time.monotonic
    started: float = 0.0
    finished: float | None = None
    state: TaskState = TaskState.RUNNING
    fraction: float = 0.0
    message: str = "Starting"
    step: int | None = None
    steps: int | None = None
    step_title: str | None = None
    expected_s: float | None = None
    smoothed_total: float | None = None
    result: Any = None
    error: MM3Error | None = None
    runner: asyncio.Task[None] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.started = self.clock()

    # -- reported by the generator -----------------------------------------------------------

    def update(self, fraction: float, message: str) -> None:
        self.fraction = max(self.fraction, min(fraction, 1.0))  # never goes backwards
        self.message = message
        self.smoothed_total = smooth_total(self.smoothed_total, self.elapsed(), self.fraction)

    def set_step(self, position: int, total: int, title: str) -> None:
        self.step, self.steps, self.step_title = position, total, title

    # -- reading ------------------------------------------------------------------------------

    def elapsed(self) -> float:
        return (self.finished if self.finished is not None else self.clock()) - self.started

    def snapshot(self) -> dict[str, Any]:
        elapsed = self.elapsed()
        left = (
            eta(elapsed, self.fraction, self.expected_s, self.smoothed_total)
            if self.state is TaskState.RUNNING
            else Eta("none", None)
        )
        error = None
        if self.error is not None:
            error = {
                "code": self.error.code,
                "message": self.error.message,
                "hint": self.error.hint,
            }
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state.value,
            "fraction": round(self.fraction, 4),
            "message": self.message,
            "step": self.step,
            "steps": self.steps,
            "step_title": self.step_title,
            "elapsed_s": round(elapsed, 1),
            "eta": left.kind,
            "remaining_s": None if left.remaining_s is None else round(left.remaining_s, 1),
            "error": error,
        }

    def finish(self, state: TaskState) -> None:
        self.state = state
        self.finished = self.clock()


Work = Callable[[LongTask], Awaitable[Any]]


class TaskRegistry:
    """The long tasks of this server process: at most one running per note, and the last
    finished one is kept (until replaced or dismissed) so the page can still fetch its result."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._tasks: dict[str, LongTask] = {}
        self._by_note: dict[str, str] = {}
        self._clock = clock

    def start(self, mm3_id: str, kind: str, work: Work) -> LongTask:
        self._prune()
        current = self.for_note(mm3_id)
        if current is not None and current.state is TaskState.RUNNING:
            raise MM3Error(
                "E_TASK_RUNNING",
                "Another long action is already running for this note.",
                "Wait for it to finish, or cancel it first.",
                status_code=409,
            )
        if current is not None:
            self._tasks.pop(current.id, None)
        task = LongTask(secrets.token_hex(8), kind, mm3_id, clock=self._clock)
        self._tasks[task.id] = task
        self._by_note[mm3_id] = task.id
        task.runner = asyncio.get_running_loop().create_task(self._run(task, work))
        return task

    async def _run(self, task: LongTask, work: Work) -> None:
        try:
            task.result = await work(task)
        except asyncio.CancelledError:
            task.finish(TaskState.CANCELLED)
            return
        except MM3Error as exc:
            task.error = exc
            task.finish(TaskState.FAILED)
            return
        except Exception as exc:
            task.error = MM3Error("E_TASK_FAILED", f"The action failed: {exc}", "Try again.")
            task.finish(TaskState.FAILED)
            return
        task.update(1.0, "Done")
        task.finish(TaskState.DONE)

    def get(self, task_id: str) -> LongTask | None:
        return self._tasks.get(task_id)

    def for_note(self, mm3_id: str) -> LongTask | None:
        task_id = self._by_note.get(mm3_id)
        return self._tasks.get(task_id) if task_id else None

    async def cancel(self, task: LongTask) -> None:
        """Stop a running task (the model call is interrupted), or forget a finished one."""
        if task.state is TaskState.RUNNING and task.runner is not None:
            task.runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task.runner
            if task.state is TaskState.RUNNING:
                task.finish(TaskState.CANCELLED)
            return
        self.discard(task)

    def discard(self, task: LongTask) -> None:
        self._tasks.pop(task.id, None)
        if self._by_note.get(task.mm3_id) == task.id:
            del self._by_note[task.mm3_id]

    def _prune(self) -> None:
        now = self._clock()
        for task in list(self._tasks.values()):
            if task.finished is not None and now - task.finished > KEEP_FINISHED_S:
                self.discard(task)
