"""A tiny notification hook: "a file in the vault was written, moved or removed".

Writers call :func:`vault_changed` (``vault.io.atomic_write_text`` does it for every vault
write); listeners, such as the search index (Phase 15i), react, usually by scheduling an
incremental update. Calling it is cheap and safe from any thread, and it never raises: a broken
listener must not fail a save.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

Listener = Callable[[Path | None], None]
_listeners: list[Listener] = []


def subscribe(listener: Listener) -> None:
    if listener not in _listeners:
        _listeners.append(listener)


def unsubscribe(listener: Listener) -> None:
    if listener in _listeners:
        _listeners.remove(listener)


def vault_changed(path: Path | None = None) -> None:
    """Tell the listeners that ``path`` (or, with ``None``, something in the vault) changed."""
    for listener in list(_listeners):
        try:
            listener(path)
        except Exception:  # a listener's bug must never break the write that called it
            log.exception("A vault change listener failed")
