"""Check a Hugging Face token from Settings: is it valid, and may it fetch the gated model?

Two requests to ``huggingface.co`` over HTTPS, made only when the user presses *Test*. The token
is sent as a bearer header and never appears in the result or in logs.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from meetingmaster3.transcription.models import DIARIZATION_TERMS_URL, HF_TOKEN_URL

HF = "https://huggingface.co"
TIMEOUT = httpx.Timeout(10.0)
_ACCESS_OK = {200, 302, 307}
_DENIED = {401, 403}


@dataclass(frozen=True)
class TokenCheck:
    ok: bool
    message: str
    hint: str = ""
    user: str | None = None
    model_access: bool | None = None
    """``True``: the token may download the model. ``False``: terms not accepted. ``None``: not
    verified."""


def check_token(token: str | None, model: str, *, offline: bool = False) -> TokenCheck:
    if not token:
        return TokenCheck(
            False,
            "No token is saved.",
            f"Create a read token at {HF_TOKEN_URL}, paste it here and save, then test again.",
        )
    if offline:
        return TokenCheck(
            False,
            "Offline mode is on, so Hugging Face was not contacted.",
            "Turn off “offline” to test the token.",
        )
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "MeetingMaster3"}
    try:
        with httpx.Client(timeout=TIMEOUT, headers=headers, follow_redirects=False) as client:
            who = client.get(f"{HF}/api/whoami-v2")
            if who.status_code in _DENIED:
                return TokenCheck(
                    False,
                    "Hugging Face rejected this token.",
                    f"Create a new read token at {HF_TOKEN_URL} and save it.",
                    model_access=None,
                )
            if who.status_code != 200:
                return TokenCheck(
                    False,
                    f"Hugging Face answered HTTP {who.status_code}.",
                    "Try again later.",
                )
            user = str(who.json().get("name") or "") or None
            probe = client.head(f"{HF}/{model}/resolve/main/config.yaml")
    except (httpx.HTTPError, ValueError) as exc:
        return TokenCheck(
            False,
            f"Could not reach Hugging Face ({type(exc).__name__}).",
            "Check the network connection, or download the models on another machine.",
        )
    if probe.status_code in _ACCESS_OK:
        return TokenCheck(True, "The token is valid and may download the model.", "", user, True)
    if probe.status_code in _DENIED:
        return TokenCheck(
            False,
            "The token is valid, but this account has not accepted the model's terms.",
            f"Open {DIARIZATION_TERMS_URL}, accept the terms while signed in as "
            f"{user or 'this user'}, then test again.",
            user,
            False,
        )
    return TokenCheck(
        True,
        "The token is valid. Access to the model could not be verified.",
        f"If a download is refused, accept the terms at {DIARIZATION_TERMS_URL}.",
        user,
        None,
    )
