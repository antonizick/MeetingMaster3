"""Backend registry: maps config entries to backend instances.

Adding a backend kind means one module plus one ``register_kind`` call below.
"""

from __future__ import annotations

from collections.abc import Callable

from meetingmaster3.config.settings import MASK, BackendConfig, Settings
from meetingmaster3.llm.base import E_LLM_CONFIG, E_LLM_UNKNOWN_BACKEND, LLMBackend, llm_error
from meetingmaster3.llm.bedrock import BedrockBackend
from meetingmaster3.llm.ollama import DEFAULT_BASE_URL, OllamaBackend
from meetingmaster3.llm.openai_compat import PRESET_BASE_URLS, OpenAICompatBackend

Factory = Callable[[str, BackendConfig, Settings], LLMBackend]
_FACTORIES: dict[str, Factory] = {}

DEFAULT_BACKEND_NAME = "ollama"


def register_kind(kind: str, factory: Factory) -> None:
    _FACTORIES[kind] = factory


def kinds() -> list[str]:
    return sorted(_FACTORIES)


def _secret(cfg: BackendConfig, fallback: object = None) -> str | None:
    for candidate in (cfg.api_key, fallback):
        if candidate is not None and hasattr(candidate, "get_secret_value"):
            value: str = candidate.get_secret_value()
            if value:
                return value
    return None


def _ollama(name: str, cfg: BackendConfig, settings: Settings) -> LLMBackend:
    return OllamaBackend(
        id=name,
        base_url=cfg.base_url or DEFAULT_BASE_URL,
        default_model=cfg.default_model,
        params=cfg.params,
        api_key=_secret(cfg),
        headers=cfg.headers,
        context_window=cfg.context_window,
    )


def _openai_like(kind: str) -> Factory:
    def build(name: str, cfg: BackendConfig, settings: Settings) -> LLMBackend:
        base_url = cfg.base_url or PRESET_BASE_URLS.get(kind)
        if not base_url:
            raise llm_error(
                E_LLM_CONFIG,
                f"Backend '{name}' needs a base_url.",
                "Set llm.backends.<name>.base_url, e.g. http://127.0.0.1:1234/v1 for LM Studio.",
                status_code=400,
            )
        fallback = {
            "openrouter": settings.secrets.openrouter_api_key,
            "openai": settings.secrets.openai_api_key,
        }.get(kind)
        return OpenAICompatBackend(
            id=name,
            base_url=base_url,
            api_key=_secret(cfg, fallback),
            default_model=cfg.default_model,
            params=cfg.params,
            headers=cfg.headers,
            context_window=cfg.context_window,
            kind=kind,
        )

    return build


def _bedrock(name: str, cfg: BackendConfig, settings: Settings) -> LLMBackend:
    key, secret = settings.secrets.aws_access_key_id, settings.secrets.aws_secret_access_key
    return BedrockBackend(
        id=name,
        region=cfg.region,
        profile=cfg.profile,
        default_model=cfg.default_model,
        params=cfg.params,
        access_key_id=_secret(BackendConfig(kind="bedrock"), key),
        secret_access_key=_secret(BackendConfig(kind="bedrock"), secret),
        context_window=cfg.context_window,
    )


register_kind("ollama", _ollama)
register_kind("openai_compat", _openai_like("openai_compat"))
register_kind("openrouter", _openai_like("openrouter"))
register_kind("openai", _openai_like("openai"))
register_kind("bedrock", _bedrock)


class BackendRegistry:
    """Builds backends from ``settings.llm`` and caches them until their config changes."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._cache: dict[str, tuple[str, LLMBackend]] = {}

    def configs(self) -> dict[str, BackendConfig]:
        """Configured backends, plus the implicit local Ollama when none is configured."""
        configs = dict(self.settings.llm.backends)
        if DEFAULT_BACKEND_NAME not in configs and self.settings.llm.default_backend == "ollama":
            configs[DEFAULT_BACKEND_NAME] = BackendConfig(kind="ollama", base_url=DEFAULT_BASE_URL)
        return configs

    def names(self) -> list[str]:
        return list(self.configs())

    @property
    def default_name(self) -> str:
        return self.settings.llm.default_backend

    def config(self, name: str | None = None) -> BackendConfig:
        name = name or self.default_name
        try:
            return self.configs()[name]
        except KeyError:
            raise llm_error(
                E_LLM_UNKNOWN_BACKEND,
                f"No LLM backend named '{name}'.",
                f"Configured backends: {', '.join(self.names()) or 'none'}.",
                status_code=404,
            ) from None

    def get(self, name: str | None = None) -> LLMBackend:
        name = name or self.default_name
        cfg = self.config(name)
        fingerprint = cfg.model_dump_json() + repr(cfg.api_key and cfg.api_key.get_secret_value())
        cached = self._cache.get(name)
        if cached and cached[0] == fingerprint:
            return cached[1]
        factory = _FACTORIES.get(cfg.kind)
        if factory is None:
            raise llm_error(
                E_LLM_CONFIG,
                f"Unknown backend kind '{cfg.kind}' for '{name}'.",
                f"Known kinds: {', '.join(kinds())}.",
                status_code=400,
            )
        backend = factory(name, cfg, self.settings)
        self._cache[name] = (fingerprint, backend)
        return backend

    def invalidate(self) -> None:
        self._cache.clear()

    def describe(self, name: str) -> dict[str, object]:
        """Config plus derived facts for the API/UI. Secrets are masked."""
        cfg, backend = self.config(name), self.get(name)
        return {
            "name": name,
            "kind": cfg.kind,
            "is_local": backend.is_local,
            "requires_consent": not backend.is_local,
            "consent_remembered": cfg.consent_remembered,
            "cloud_embedding_consent": cfg.cloud_embedding_consent,
            "is_default": name == self.default_name,
            "base_url": cfg.base_url or getattr(backend, "base_url", None),
            "region": cfg.region,
            "profile": cfg.profile,
            "default_model": cfg.default_model,
            "api_key": MASK if cfg.api_key else None,
            "badge": "local" if backend.is_local else f"cloud: {cfg.kind}",
        }
