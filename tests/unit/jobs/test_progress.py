from __future__ import annotations

import asyncio
import threading

from meetingmaster3.jobs.models import ProgressEvent
from meetingmaster3.jobs.progress import EtaEstimator, ProgressBus


def test_eta_estimator() -> None:
    now = [100.0]
    eta = EtaEstimator(clock=lambda: now[0])
    assert eta.estimate("j", "s", 0.5) is None  # not started
    eta.start("j", "s")
    now[0] = 100.5
    assert eta.estimate("j", "s", 0.5) is None  # too early
    now[0] = 110.0
    assert eta.estimate("j", "s", 0.01) is None  # too little progress
    assert eta.estimate("j", "s", None) is None
    assert eta.estimate("j", "s", 0.25) == 30.0  # 10 s for 25 % -> 30 s left
    assert eta.estimate("j", "s", 1.0) == 0.0
    eta.stop("j", "s")
    assert eta.estimate("j", "s", 0.5) is None


async def test_bus_orders_numbers_and_replays() -> None:
    bus = ProgressBus()
    bus.bind(asyncio.get_running_loop())
    bus.publish(ProgressEvent("j", "a", "running", 0.1))  # before anyone subscribes
    await asyncio.sleep(0)  # dispatch happens on the loop
    async with bus.subscribe("j") as q:
        threads = [
            threading.Thread(
                target=lambda i=i: bus.publish(ProgressEvent("j", "a", "running", i / 100))
            )
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        bus.publish(ProgressEvent("other", "a", "running"))
        bus.publish(ProgressEvent("j", None, "written", kind="job"))
        got = [await asyncio.wait_for(q.get(), 1) for _ in range(21)]
    seqs = [e.seq for e in got]
    assert seqs == list(range(2, 23))
    assert got[-1].kind == "job"
    latest = bus.latest("j")
    assert set(latest) == {"a", "_job"} and latest["_job"].status == "written"
    assert bus.last_seq("j") == 22 and bus.last_seq("other") == 1
    bus.forget("j")
    assert bus.latest("j") == {}


async def test_slow_subscriber_drops_oldest(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from meetingmaster3.jobs import progress

    monkeypatch.setattr(progress, "QUEUE_SIZE", 3)
    bus = ProgressBus()
    bus.bind(asyncio.get_running_loop())
    async with bus.subscribe("j") as q:
        for i in range(5):
            bus.publish(ProgressEvent("j", "a", "running", i / 10))
        await asyncio.sleep(0)
        got = [q.get_nowait().seq for _ in range(q.qsize())]
    assert got == [3, 4, 5]


def test_publish_without_loop_is_synchronous() -> None:
    bus = ProgressBus()
    bus.publish(ProgressEvent("j", "a", "running", 0.5))
    assert bus.latest("j")["a"].fraction == 0.5
