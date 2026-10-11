"""In-process progress pub/sub with per-stage ETA estimates and a replay cache.

Publishers may be worker threads; every event is handed to the event loop, which numbers it
(``seq``, increasing per job) and fans it out, so subscribers see events in publication order.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from dataclasses import replace

from meetingmaster3.jobs.models import ProgressEvent

QUEUE_SIZE = 1000
MIN_FRACTION_FOR_ETA = 0.02
MIN_SECONDS_FOR_ETA = 1.0


class EtaEstimator:
    """Linear rate estimate: ``elapsed * (1 - f) / f`` once there is enough signal."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock: Callable[[], float] = clock or time.monotonic
        self._started: dict[tuple[str, str], float] = {}

    def start(self, job_id: str, stage: str) -> None:
        self._started[(job_id, stage)] = self._clock()

    def stop(self, job_id: str, stage: str) -> None:
        self._started.pop((job_id, stage), None)

    def estimate(self, job_id: str, stage: str, fraction: float | None) -> float | None:
        started = self._started.get((job_id, stage))
        if started is None or fraction is None or fraction < MIN_FRACTION_FOR_ETA:
            return None
        elapsed = self._clock() - started
        if elapsed < MIN_SECONDS_FOR_ETA:
            return None
        return round(elapsed * (1.0 - fraction) / fraction, 1)


class ProgressBus:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: dict[str, set[asyncio.Queue[ProgressEvent]]] = defaultdict(set)
        self._seq: dict[str, int] = defaultdict(int)
        self._latest: dict[str, dict[str, ProgressEvent]] = defaultdict(dict)
        self._lock = threading.Lock()
        self.eta = EtaEstimator()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, event: ProgressEvent) -> None:
        """Publish from any thread. Events always pass through the loop's FIFO callback queue,
        so an event published on the loop never overtakes one queued earlier by a worker."""
        loop = self._loop
        if loop is None or loop.is_closed():
            self._dispatch(event)
            return
        with contextlib.suppress(RuntimeError):  # loop closed during shutdown
            loop.call_soon_threadsafe(self._dispatch, event)

    def _dispatch(self, event: ProgressEvent) -> None:
        with self._lock:
            self._seq[event.job_id] += 1
            event = replace(event, seq=self._seq[event.job_id])
            key = event.stage if event.kind == "stage" and event.stage else "_job"
            self._latest[event.job_id][key] = event
            queues = list(self._subscribers.get(event.job_id, ()))
        for q in queues:
            if q.full():  # a stalled client; drop its oldest event rather than block
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(event)

    def latest(self, job_id: str) -> dict[str, ProgressEvent]:
        """The most recent event per stage (key ``_job`` for the job-level event)."""
        with self._lock:
            return dict(self._latest.get(job_id, {}))

    def last_seq(self, job_id: str) -> int:
        with self._lock:
            return self._seq.get(job_id, 0)

    def forget(self, job_id: str) -> None:
        with self._lock:
            self._latest.pop(job_id, None)

    @contextlib.asynccontextmanager
    async def subscribe(self, job_id: str) -> AsyncIterator[asyncio.Queue[ProgressEvent]]:
        q: asyncio.Queue[ProgressEvent] = asyncio.Queue(maxsize=QUEUE_SIZE)
        with self._lock:
            self._subscribers[job_id].add(q)
        try:
            yield q
        finally:
            with self._lock:
                self._subscribers[job_id].discard(q)
                if not self._subscribers[job_id]:
                    del self._subscribers[job_id]
