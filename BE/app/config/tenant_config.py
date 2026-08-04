from __future__ import annotations

from pathlib import Path

from app.config.loader import ConfigLoadError, WorkflowConfigLoader
from app.domain.models import ProviderConfig


class TenantConfigError(RuntimeError):
    """Raised when a tenant configuration cannot be loaded."""


class TenantConfigRepository:
    """Loads self-contained tenant configs from config/tenants/*.yaml."""

    def __init__(self, config_dir: Path) -> None:
        self._loader = WorkflowConfigLoader(config_dir)

    def list(self) -> list[ProviderConfig]:
        try:
            return self._loader.list_tenant_configs()
        except ConfigLoadError as exc:
            raise TenantConfigError(str(exc)) from exc

    def get(self, tenant_id: str, provider_id: str) -> ProviderConfig:
        try:
            return self._loader.load_tenant_config(tenant_id=tenant_id, provider_id=provider_id)
        except ConfigLoadError as exc:
            raise TenantConfigError(str(exc)) from exc
