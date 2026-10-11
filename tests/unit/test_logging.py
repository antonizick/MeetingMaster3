from __future__ import annotations

import logging

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
