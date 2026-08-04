from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from app.domain.models import ProviderConfig


class ConfigLoadError(RuntimeError):
    """Raised when workflow configuration cannot be loaded."""


class WorkflowConfigLoader:
    # Shared defaults every tenant inherits. Business and HITL rules are NOT
    # here: they are tenant-specific and must be declared in each
    # tenants/<id>.yaml file.
    REQUIRED_FILES = (
        "document_types.yaml",
        "entity_schema.yaml",
        "hitl_policy.yaml",
        "letter_templates.yaml",
    )

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._tenant_dir = config_dir / "tenants"

    def list_tenant_configs(self, tenant_id: str = "default") -> list[ProviderConfig]:
        return [
            self.load_tenant_config(tenant_id=tenant_id, provider_id=path.stem)
            for path in sorted(self._tenant_dir.glob("*.yaml"))
        ]

    def load_tenant_config(self, tenant_id: str, provider_id: str) -> ProviderConfig:
        base = self._load_base_config()
        tenant_path = self._tenant_dir / f"{provider_id}.yaml"
        if not tenant_path.exists():
            if provider_id != "default":
                raise ConfigLoadError(f"Missing tenant override: {tenant_path}")
            tenant_path = self._tenant_dir / "default.yaml"

        merged = self._deep_merge(base, self._read_yaml(tenant_path))
        merged["tenant_id"] = tenant_id
        merged["provider_id"] = provider_id
        return ProviderConfig.model_validate(merged)

    def _load_base_config(self) -> dict[str, Any]:
        missing = [name for name in self.REQUIRED_FILES if not (self._config_dir / name).exists()]
        if missing:
            raise ConfigLoadError(f"Missing required config files: {', '.join(missing)}")

        merged: dict[str, Any] = {}
        for file_name in self.REQUIRED_FILES:
            merged = self._deep_merge(merged, self._read_yaml(self._config_dir / file_name))
        return merged

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigLoadError(f"Invalid YAML config at {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigLoadError(f"Config file must contain a mapping: {path}")
        return data

    @classmethod
    def _deep_merge(cls, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(base)
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = cls._deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged
