"""Cloud egress policy (spec S6): non-local backends need explicit consent."""

from __future__ import annotations

from meetingmaster3.llm.base import E_CONSENT_REQUIRED, LLMBackend, llm_error


def requires_consent(backend: LLMBackend) -> bool:
    """True when using ``backend`` sends transcript text off this machine."""
    return not backend.is_local


def enforce_consent(backend: LLMBackend, *, cloud_consent: bool, remembered: bool = False) -> None:
    """Raise ``E_CONSENT_REQUIRED`` unless the backend is local or consent was given.

    ``cloud_consent`` is the per-job flag; ``remembered`` is the backend's stored
    ``consent_remembered`` setting. The generation stage (Phase 09) calls this before any call.
    """
    if requires_consent(backend) and not (cloud_consent or remembered):
        raise llm_error(
            E_CONSENT_REQUIRED,
            f"The backend '{backend.id}' sends your transcript to a cloud service.",
            "Confirm cloud use for this job, or choose a local backend such as Ollama.",
            status_code=403,
        )
