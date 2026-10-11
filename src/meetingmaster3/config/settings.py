"""Application settings. Load order: defaults < config.yaml < environment variables.

Environment variables use the ``MM3_`` prefix and ``__`` for nesting, e.g.
``MM3_SERVER__PORT=9000`` or ``MM3_SECRETS__HF_TOKEN=hf_...``.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from meetingmaster3.config.paths import AppPaths, resolve_paths
from meetingmaster3.logging import register_secret

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MASK = "********"


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    allowed_hosts: list[str] = Field(default_factory=list)


class VaultSettings(BaseModel):
    path: Path | None = None
    output_subfolder: str = "Meetings/{yyyy}/"
    templates_subfolder: str = "MeetingMaster3/templates/"


class TranscriptionSettings(BaseModel):
    """Placeholder; populated in Phase 06."""

    model: str = "auto"
    diarize: bool = True


class HardwareSettings(BaseModel):
    """``auto`` detects the GPU; any other value declares the hardware profile."""

    profile: Literal["auto", "cpu", "vram8", "vram16", "vram24plus"] = "auto"


class BackendConfig(BaseModel):
    """One configured LLM backend (``llm.backends.<name>``)."""

    kind: str
    base_url: str | None = None
    api_key: SecretStr | None = None
    region: str | None = None  # Bedrock
    profile: str | None = None  # Bedrock (AWS named profile)
    default_model: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)  # extra sampling/model options
    headers: dict[str, str] = Field(default_factory=dict)  # e.g. OpenRouter HTTP-Referer
    context_window: int | None = Field(default=None, ge=512)  # override when unknown
    consent_remembered: bool = False  # cloud egress consent remembered for this backend (S6)


class LLMSettings(BaseModel):
    default_backend: str = "ollama"
    backends: dict[str, BackendConfig] = Field(default_factory=dict)


class AudioSettings(BaseModel):
    max_upload_mb: int = Field(default=2048, ge=1)  # R7
    opus_bitrate_kbps: int = Field(default=24, ge=6, le=128)  # retained audio (R8)


class JobsSettings(BaseModel):
    max_concurrent: int = Field(default=2, ge=1, le=8)  # jobs in flight; GPU stages are serial
    prune_interval_hours: float = Field(default=24.0, gt=0)  # audio retention pruner (R8)


class PrivacySettings(BaseModel):
    audio_retention: Literal["forever", "days", "delete_after_write"] = "days"
    audio_retention_days: int = Field(default=90, ge=1)
    voiceprints_enabled: bool = False


class SecretsSettings(BaseModel):
    hf_token: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    aws_access_key_id: SecretStr | None = None
    aws_secret_access_key: SecretStr | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MM3_", env_nested_delimiter="__", extra="ignore")

    server: ServerSettings = Field(default_factory=ServerSettings)
    vault: VaultSettings = Field(default_factory=VaultSettings)
    transcription: TranscriptionSettings = Field(default_factory=TranscriptionSettings)
    hardware: HardwareSettings = Field(default_factory=HardwareSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    jobs: JobsSettings = Field(default_factory=JobsSettings)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)
    secrets: SecretsSettings = Field(default_factory=SecretsSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # init kwargs carry the YAML values, so env must outrank them.
        return (env_settings, init_settings)

    # -- helpers -----------------------------------------------------------------------

    @property
    def is_loopback(self) -> bool:
        return self.server.host in LOOPBACK_HOSTS

    @property
    def trusted_hosts(self) -> list[str]:
        return ["127.0.0.1", "localhost", *self.server.allowed_hosts]

    def register_secrets(self) -> None:
        """Teach the log redaction filter every configured secret value."""
        for value in vars(self.secrets).values():
            if isinstance(value, SecretStr):
                register_secret(value.get_secret_value())
        for backend in self.llm.backends.values():
            if backend.api_key:
                register_secret(backend.api_key.get_secret_value())

    def dump_masked(self) -> dict[str, Any]:
        """Settings as plain data with every secret replaced by a mask (safe for the API)."""
        data = self.model_dump(mode="json")
        data["secrets"] = {k: (MASK if v else None) for k, v in vars(self.secrets).items()}
        for name, backend in self.llm.backends.items():
            data["llm"]["backends"][name]["api_key"] = MASK if backend.api_key else None
        return data

    def _dump_for_save(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", exclude={"secrets"})
        secrets = {
            k: v.get_secret_value()
            for k, v in vars(self.secrets).items()
            if isinstance(v, SecretStr)
        }
        if secrets:
            data["secrets"] = secrets
        for name, backend in self.llm.backends.items():
            key = backend.api_key.get_secret_value() if backend.api_key else None
            data["llm"]["backends"][name]["api_key"] = key
        return data

    def save(self, path: Path | None = None) -> Path:
        """Atomically write the config as YAML with mode 0600."""
        target = path or resolve_paths().config_file
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".config-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                os.fchmod(fh.fileno(), 0o600)
                yaml.safe_dump(self._dump_for_save(), fh, sort_keys=False)
            os.replace(tmp, target)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)
            raise
        return target


def load_settings(path: Path | None = None, paths: AppPaths | None = None) -> Settings:
    """Load settings from ``path`` (default: the XDG config file), then apply env overrides."""
    config_file = path or (paths or resolve_paths()).config_file
    data: dict[str, Any] = {}
    if config_file.is_file():
        loaded = yaml.safe_load(config_file.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    settings = Settings(**data)
    settings.register_secrets()
    return settings
