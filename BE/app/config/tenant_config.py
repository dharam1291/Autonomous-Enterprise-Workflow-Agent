from __future__ import annotations

from pathlib import Path

from app.config.loader import ConfigLoadError, UnknownTenantError as _LoaderUnknownTenantError, WorkflowConfigLoader
from app.domain.models import ProviderConfig


class TenantConfigError(RuntimeError):
    """Raised when a tenant configuration cannot be loaded."""


class UnknownTenantError(TenantConfigError):
    """Raised when no tenant matches the requested tenant_id (a client error)."""


class TenantConfigRepository:
    """Loads self-contained tenant configs from config/tenants/*.yaml.

    Tenants are keyed by the `tenant_id` declared inside each file (e.g. de / ch
    / mb), not by the file name.
    """

    def __init__(self, config_dir: Path) -> None:
        self._loader = WorkflowConfigLoader(config_dir)

    def list(self) -> list[ProviderConfig]:
        try:
            return self._loader.list_tenant_configs()
        except ConfigLoadError as exc:
            raise TenantConfigError(str(exc)) from exc

    def get(self, tenant_id: str) -> ProviderConfig:
        try:
            return self._loader.load_tenant_config(tenant_id)
        except _LoaderUnknownTenantError as exc:
            raise UnknownTenantError(str(exc)) from exc
        except ConfigLoadError as exc:
            raise TenantConfigError(str(exc)) from exc
