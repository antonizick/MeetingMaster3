"""Logging setup with a secret-redaction filter.

Transcript content must not be logged at INFO; this module only guarantees that secrets
(registered values plus well-known token shapes) never reach a log handler.
"""

from __future__ import annotations

import logging
import logging.handlers
import queue
import re
import threading

REDACTED = "[REDACTED]"

_PATTERNS = [
    re.compile(r"hf_[A-Za-z0-9]{10,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"(?i)(aws_secret_access_key\s*[=:]\s*)[A-Za-z0-9/+=]{30,}"),
    re.compile(r"(?i)(authorization:\s*bearer\s+)\S+"),
]

_lock = threading.Lock()
_secrets: set[str] = set()


def register_secret(value: str) -> None:
    """Remember a secret value so it is redacted verbatim from all log output."""
    if len(value) >= 4:
        with _lock:
            _secrets.add(value)


def clear_secrets() -> None:
    with _lock:
        _secrets.clear()


def redact(text: str) -> str:
    with _lock:
        known = sorted(_secrets, key=len, reverse=True)
    for secret in known:
        text = text.replace(secret, REDACTED)
    for pattern in _PATTERNS:
        if pattern.groups:
            text = pattern.sub(lambda m: m.group(1) + REDACTED, text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        if record.exc_info:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
        return True


_QUEUE_SIZE = 10_000


class NonBlockingQueueHandler(logging.handlers.QueueHandler):
    """Hand records to a writer thread and never block the caller.

    A terminal that has stopped accepting output (Ctrl+S flow control, a paused emulator, a full
    pipe) blocks writes to it. Writing from the event-loop thread would then freeze the whole web
    app, so records go through a bounded queue and are dropped, with a count, when it is full.
    """

    def __init__(self, target: queue.Queue[logging.LogRecord]) -> None:
        super().__init__(target)
        self.dropped = 0

    def enqueue(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            self.dropped += 1


class _ReportingStreamHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Writer-thread handler that reports log lines lost while the output was stalled."""

    def __init__(self, source: NonBlockingQueueHandler) -> None:
        super().__init__()
        self._source = source
        self._reported = 0

    def emit(self, record: logging.LogRecord) -> None:
        lost = self._source.dropped - self._reported
        if lost > 0:
            self._reported += lost
            super().emit(
                logging.makeLogRecord(
                    {
                        "name": "meetingmaster3.logging",
                        "levelno": logging.WARNING,
                        "levelname": "WARNING",
                        "msg": f"{lost} log line(s) were dropped while the terminal was not "
                        "accepting output (is it paused? try Ctrl+Q).",
                    }
                )
            )
        super().emit(record)


_listener: logging.handlers.QueueListener | None = None


def configure_logging(level: int | str = logging.INFO) -> None:
    """Send all logging, uvicorn's included, through a non-blocking queue to stderr."""
    global _listener
    root = logging.getLogger()
    root.setLevel(level)
    if any(getattr(h, "_mm3", False) for h in root.handlers):
        return
    log_queue: queue.Queue[logging.LogRecord] = queue.Queue(_QUEUE_SIZE)
    front = NonBlockingQueueHandler(log_queue)
    front._mm3 = True  # type: ignore[attr-defined]
    front.addFilter(RedactionFilter())  # redact before a record leaves the calling thread
    back = _ReportingStreamHandler(front)
    back.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    _listener = logging.handlers.QueueListener(log_queue, back)
    _listener.start()
    root.addHandler(front)
