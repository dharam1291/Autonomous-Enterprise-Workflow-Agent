from __future__ import annotations

from pathlib import Path

from app.config.loader import ConfigLoadError, WorkflowConfigLoader
from app.domain.models import ProviderConfig


class ProviderConfigError(RuntimeError):
    """Raised when a provider configuration cannot be loaded."""


class ProviderConfigRepository:
    def __init__(self, config_dir: Path) -> None:
        root_dir = config_dir.parent if config_dir.name == "providers" else config_dir
        self._loader = WorkflowConfigLoader(root_dir)

    def list(self) -> list[ProviderConfig]:
        try:
            return self._loader.list_provider_configs()
        except ConfigLoadError as exc:
            raise ProviderConfigError(str(exc)) from exc

    def get(self, tenant_id: str, provider_id: str) -> ProviderConfig:
        try:
            return self._loader.load_provider_config(tenant_id=tenant_id, provider_id=provider_id)
        except ConfigLoadError as exc:
            raise ProviderConfigError(str(exc)) from exc
