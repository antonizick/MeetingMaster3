from __future__ import annotations

import logging
import logging.handlers

from meetingmaster3.logging import REDACTED, RedactionFilter, redact, register_secret


def test_known_patterns_redacted() -> None:
    for secret in ("hf_abcdefghij1234567890", "sk-abcdefghijklmnop1234", "AKIAABCDEFGHIJKLMNOP"):
        assert secret not in redact(f"token={secret} end")


def test_registered_secret_redacted() -> None:
    register_secret("correct-horse-battery")
    assert redact("pw correct-horse-battery!") == f"pw {REDACTED}!"


def test_filter_redacts_formatted_args() -> None:
    record = logging.LogRecord(
        "t", logging.INFO, "f", 1, "key %s", ("hf_abcdefghij1234567890",), None
    )
    assert RedactionFilter().filter(record)
    assert "hf_abcdefghij" not in record.getMessage()


def test_blocked_output_never_blocks_the_caller() -> None:
    """A stalled terminal must not freeze the thread that logs (the web app's event loop)."""
    import queue
    import threading
    import time

    from meetingmaster3.logging import NonBlockingQueueHandler, _ReportingStreamHandler

    gate = threading.Event()

    class StalledStream:
        def write(self, _text: str) -> None:
            gate.wait()

        def flush(self) -> None:
            pass

    q: queue.Queue[logging.LogRecord] = queue.Queue(5)
    front = NonBlockingQueueHandler(q)
    back = _ReportingStreamHandler(front)
    back.setStream(StalledStream())  # type: ignore[arg-type]
    listener = logging.handlers.QueueListener(q, back)
    listener.start()
    log = logging.getLogger("stall-test")
    log.propagate = False
    log.addHandler(front)
    try:
        started = time.monotonic()
        for i in range(50):
            log.warning("line %d", i)
        assert time.monotonic() - started < 1.0
        assert front.dropped > 0
    finally:
        gate.set()
        deadline = time.monotonic() + 5
        while not q.empty() and time.monotonic() < deadline:
            time.sleep(0.01)
        listener.stop()
        log.removeHandler(front)
