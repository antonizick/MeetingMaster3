"""Edit live settings from the UI: validate a patch per section, apply it, write ``config.yaml``.

The patch keys are dotted paths (``transcription.model``). Nothing is applied unless every value
in the patch is valid, so a bad form never leaves the app half-changed. Validation runs on the
section models alone (never through ``Settings(...)``), so environment overrides are not copied
into the file by the validation step. The write itself dumps the live settings (see
``docs/user-guide/settings.md`` about environment overrides).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from meetingmaster3.config.settings import BackendConfig, Settings


def get_path(settings: Settings, path: str) -> Any:
    value: Any = settings
    for part in path.split("."):
        value = getattr(value, part)
    return value


def _message(error: Mapping[str, Any]) -> str:
    msg = str(error.get("msg", "invalid value"))
    return msg.removeprefix("Value error, ")


def validate_patch(settings: Settings, patch: Mapping[str, Any]) -> dict[str, str]:
    """Error message per dotted path; empty when the whole patch is valid."""
    errors: dict[str, str] = {}
    for section, values in _by_section(patch).items():
        model = getattr(settings, section)
        try:
            type(model).model_validate({**dict(model), **values})
        except ValidationError as exc:
            for err in exc.errors():
                field = str(err["loc"][0]) if err["loc"] else ""
                key = f"{section}.{field}" if field in values else f"{section}.{next(iter(values))}"
                errors.setdefault(key, _message(err))
    return errors


def _by_section(patch: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path, value in patch.items():
        section, _, field = path.partition(".")
        out.setdefault(section, {})[field] = value
    return out


def apply_patch(settings: Settings, patch: Mapping[str, Any]) -> dict[str, str]:
    """Validate and apply ``patch`` to the live settings. Returns the errors (nothing applied
    when there are any)."""
    errors = validate_patch(settings, patch)
    if errors:
        return errors
    for section, values in _by_section(patch).items():
        model: BaseModel = getattr(settings, section)
        setattr(settings, section, type(model).model_validate({**dict(model), **values}))
    return {}


def save_settings(settings: Settings, config_file: Path) -> None:
    """Write ``config.yaml`` (atomic, 0600) and refresh the log redaction list."""
    settings.save(config_file)
    settings.register_secrets()


# -- LLM backends ---------------------------------------------------------------------------


def validate_backend(data: Mapping[str, Any]) -> tuple[BackendConfig | None, dict[str, str]]:
    try:
        return BackendConfig.model_validate(dict(data)), {}
    except ValidationError as exc:
        return None, {str(e["loc"][0]) if e["loc"] else "kind": _message(e) for e in exc.errors()}
