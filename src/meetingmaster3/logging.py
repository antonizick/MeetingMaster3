"""Logging setup with a secret-redaction filter.

Transcript content must not be logged at INFO; this module only guarantees that secrets
(registered values plus well-known token shapes) never reach a log handler.
"""

from __future__ import annotations

import logging
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


def configure_logging(level: int | str = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    if not any(getattr(h, "_mm3", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler._mm3 = True  # type: ignore[attr-defined]
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.addFilter(RedactionFilter())
        root.addHandler(handler)
