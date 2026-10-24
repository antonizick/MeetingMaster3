"""Download one Grok share (Phase 15l): MeetingMaster3's only request to a non-LLM website.

One ``GET https://grok.com/rest/app-chat/share_links/<id>``, built here from a validated share id
(:func:`~meetingmaster3.importing.grok_share.parse_share_url`); the caller never passes a URL.
HTTPS with certificate verification, no cookies or credentials, no redirects (a redirect is an
error), a time limit, and the body read as a stream under the import size limit. ``HTTPS_PROXY``
is respected, as httpx does. 4xx answers are not retried; a 5xx or a timeout is retried once.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from meetingmaster3 import __version__
from meetingmaster3.errors import MM3Error
from meetingmaster3.importing.grok_share import SHARE_ID, unavailable
from meetingmaster3.importing.model import too_large

ENDPOINT = "https://grok.com/rest/app-chat/share_links/{id}"
TIMEOUT_SECONDS = 20.0
"""Per connect/read; the whole download also stops after :data:`DEADLINE_SECONDS`."""
DEADLINE_SECONDS = 60.0
RETRY_DELAY_SECONDS = 1.0
USER_AGENT = f"MeetingMaster3/{__version__} (Grok share import)"
HEADERS = {"Accept": "application/json", "User-Agent": USER_AGENT}

E_IMPORT_SHARE_NOT_FOUND = "E_IMPORT_SHARE_NOT_FOUND"
E_IMPORT_OFFLINE = "E_IMPORT_OFFLINE"

Sleep = Callable[[float], None]
"""Cancellable sleep (``StageContext.sleep``); raises to stop."""
Check = Callable[[], None]
"""Called between chunks; raises to cancel (``StageContext.check_cancelled``)."""


def share_url(share_id: str) -> str:
    if not SHARE_ID.fullmatch(share_id):
        raise ValueError("invalid share id")
    return ENDPOINT.format(id=share_id)


def not_found() -> MM3Error:
    return MM3Error(
        E_IMPORT_SHARE_NOT_FOUND,
        "This Grok conversation is not shared publicly, or it was deleted.",
        "Open the link in a browser to check it, or export the conversation to Markdown and "
        "upload the file instead.",
        status_code=404,
    )


def offline(reason: str) -> MM3Error:
    return MM3Error(
        E_IMPORT_OFFLINE,
        f"Cannot reach grok.com ({reason}). Are you offline?",
        "Check the internet connection (and HTTPS_PROXY, if you use a proxy), or export the "
        "conversation to Markdown and upload the file instead.",
        status_code=502,
    )


class _Retry(Exception):
    def __init__(self, error: MM3Error) -> None:
        self.error = error


def _download(
    client: httpx.Client, url: str, max_bytes: int, check: Check, deadline: float
) -> bytes:
    try:
        with client.stream("GET", url) as resp:
            if resp.is_redirect or 300 <= resp.status_code < 400:
                raise unavailable(f"Grok answered with a redirect (HTTP {resp.status_code}).")
            if resp.status_code in (401, 403, 404, 410):
                raise not_found()
            if resp.status_code >= 500:
                raise _Retry(unavailable(f"Grok is unavailable (HTTP {resp.status_code})."))
            if resp.status_code != 200:
                raise unavailable(f"Grok answered HTTP {resp.status_code}.")
            kind = resp.headers.get("content-type", "").split(";")[0].strip().lower()
            if kind and kind != "application/json" and not kind.endswith("+json"):
                raise unavailable("Grok did not answer with a conversation (not JSON).")
            declared = resp.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                raise too_large(max(1, max_bytes // (1024 * 1024)))
            body = bytearray()
            for chunk in resp.iter_bytes():
                check()
                body += chunk
                if len(body) > max_bytes:
                    raise too_large(max(1, max_bytes // (1024 * 1024)))
                if time.monotonic() > deadline:
                    raise _Retry(offline("the download took too long"))
            return bytes(body)
    except httpx.TimeoutException as exc:
        raise _Retry(offline("no answer in time")) from exc
    except httpx.TransportError as exc:
        raise offline(type(exc).__name__) from exc


def fetch_share(
    share_id: str,
    *,
    max_bytes: int,
    check: Check = lambda: None,
    sleep: Sleep = time.sleep,
    transport: httpx.BaseTransport | None = None,
) -> bytes:
    """The share's JSON bytes. Raises :class:`MM3Error` (not found, unavailable, offline,
    too large); ``check`` and ``sleep`` may raise to cancel."""
    url = share_url(share_id)
    client = httpx.Client(
        headers=HEADERS,
        timeout=httpx.Timeout(TIMEOUT_SECONDS),
        follow_redirects=False,
        verify=True,
        trust_env=True,
        transport=transport,
    )
    with client:
        for attempt in (1, 2):
            check()
            try:
                return _download(client, url, max_bytes, check, time.monotonic() + DEADLINE_SECONDS)
            except _Retry as retry:
                if attempt == 2:
                    raise retry.error from None
                sleep(RETRY_DELAY_SECONDS)
            finally:
                client.cookies.clear()  # never send back anything grok.com set
    raise AssertionError("unreachable")  # pragma: no cover
