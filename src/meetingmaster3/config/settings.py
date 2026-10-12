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
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from meetingmaster3.config.paths import AppPaths, resolve_paths
from meetingmaster3.logging import register_secret

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MASK = "********"
#: Backend header names whose values are not secret (OpenRouter attribution); every other header
#: value (``Authorization``, ``x-api-key``, a proxy token...) is treated as a secret.
PUBLIC_HEADERS = frozenset({"http-referer", "referer", "x-title", "user-agent"})


def _url_password(url: str | None) -> str | None:
    """The password in ``https://user:password@host/`` (a proxy credential), if any."""
    if not url:
        return None
    try:
        return urlsplit(url).password
    except ValueError:
        return None


def _mask_url(url: str | None) -> str | None:
    password = _url_password(url)
    return url.replace(f":{password}@", f":{MASK}@", 1) if url and password else url


def _secret_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in headers.items() if k.lower() not in PUBLIC_HEADERS and v}


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    allowed_hosts: list[str] = Field(default_factory=list)


class VaultSettings(BaseModel):
    path: Path | None = None
    output_subfolder: str = "Meetings/{yyyy}/"
    templates_subfolder: str = "MeetingMaster3/templates/"
    attachments_subfolder: str = "Meetings/attachments/"
    """Where the optional audio copy goes (``privacy.copy_audio_to_vault``, R8)."""


MODEL_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$"
LANGUAGE_PATTERN = r"^[a-z]{2,3}$"


class TranscriptionSettings(BaseModel):
    """WhisperX transcription, alignment and diarization (Phase 06). ``auto`` and ``None`` mean
    "use the hardware recommendation" (``hardware/recommendations.yaml``)."""

    model: str = Field(default="auto", pattern=MODEL_NAME_PATTERN)
    compute_type: Literal["auto", "float16", "int8_float16", "int8", "float32"] = "auto"
    batch_size: int | None = Field(default=None, ge=1, le=64)
    device: Literal["auto", "cuda", "cpu"] = "auto"
    language: str | None = Field(default=None, pattern=LANGUAGE_PATTERN)
    """Force a language (ISO 639-1 code such as ``en``); ``None`` detects it."""
    on_non_english: Literal["ask", "proceed", "abort"] = "ask"
    diarize: bool = True
    diarization_model: str = Field(
        default="pyannote/speaker-diarization-community-1", pattern=MODEL_NAME_PATTERN
    )
    offline: bool = False
    """Never contact Hugging Face (sets ``HF_HUB_OFFLINE=1``); models must be downloaded."""
    unload_ollama: bool = True
    """Ask a local Ollama to unload its models before transcription starts (spec R5)."""


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


class GenerationSettings(BaseModel):
    """Note generation (Phase 09; templates in docs/dev-guide/template-format.md)."""

    default_template: str = Field(default="executive-summary", pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    write_companion: bool = True
    """Write the companion transcript next to the note (Q2). Without it, a note cannot be
    re-opened for regeneration or speaker renaming."""
    readable_transcript: bool = True
    """Also write a readable copy of the transcript, ``<note> (Transcript).md``, with coloured
    speaker names (R25). Needs the companion transcript, which it is made from."""
    max_context: int = Field(default=16384, ge=2048, le=1_048_576)
    """Largest context window (tokens) planned for a *local* model. Models advertise windows
    (e.g. 40k) that an 8 GB GPU cannot hold next to the weights; longer meetings use map-reduce."""
    think: bool = False
    """Let reasoning models (qwen3, deepseek-r1...) think before answering. Off by default: it
    multiplies generation time and can use up a section's token budget."""
    install_templates: bool = True
    """Copy the built-in templates into the vault's templates folder on first use."""


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
    copy_audio_to_vault: bool = False
    """Copy the retained Opus audio into ``vault.attachments_subfolder`` and link it from the
    note (``mm3-audio``). Off by default: it enlarges the vault, and a synced vault uploads it."""


class SpeakerSettings(BaseModel):
    """Voiceprint matching (Phase 07, ADR-0015). Only used when privacy.voiceprints_enabled."""

    match_threshold: float = Field(default=0.6, ge=0.0, le=1.0)  # cosine similarity
    match_margin: float = Field(default=0.1, ge=0.0, le=1.0)  # over the second-best person
    max_embeddings_per_person: int = Field(default=20, ge=1, le=200)  # newest kept per model


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
    generation: GenerationSettings = Field(default_factory=GenerationSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    jobs: JobsSettings = Field(default_factory=JobsSettings)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)
    speakers: SpeakerSettings = Field(default_factory=SpeakerSettings)
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
            for value in _secret_headers(backend.headers).values():
                register_secret(value)
            if password := _url_password(backend.base_url):
                register_secret(password)

    def dump_masked(self) -> dict[str, Any]:
        """Settings as plain data with every secret replaced by a mask (safe for the API)."""
        data = self.model_dump(mode="json")
        data["secrets"] = {k: (MASK if v else None) for k, v in vars(self.secrets).items()}
        for name, backend in self.llm.backends.items():
            entry = data["llm"]["backends"][name]
            entry["api_key"] = MASK if backend.api_key else None
            secret = _secret_headers(backend.headers)
            entry["headers"] = {k: (MASK if k in secret else v) for k, v in backend.headers.items()}
            entry["base_url"] = _mask_url(backend.base_url)
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
