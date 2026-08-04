from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_UI_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_SERVICE_NAME = "aewa-backend"

_TRUTHY = {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


@dataclass(frozen=True)
class AppSettings:
    base_dir: Path
    config_dir: Path
    workflow_dir: Path
    log_dir: Path
    log_level: str
    ui_origins: tuple[str, ...] = field(default_factory=lambda: DEFAULT_UI_ORIGINS)
    # Observability feature flags (off by default).
    enable_tracing: bool = False
    enable_metrics: bool = False
    service_name: str = DEFAULT_SERVICE_NAME
    otlp_endpoint: str | None = None

    @classmethod
    def from_project_root(cls) -> "AppSettings":
        base_dir = Path(__file__).resolve().parents[2]
        load_dotenv(dotenv_path=base_dir / ".env")

        origins_env = os.environ.get("UI_ORIGINS")
        ui_origins = tuple(origins_env.split(",")) if origins_env else DEFAULT_UI_ORIGINS

        log_dir_env = os.environ.get("LOG_DIR")
        log_dir = Path(log_dir_env) if log_dir_env else base_dir / "logs"

        return cls(
            base_dir=base_dir,
            config_dir=base_dir / "config",
            workflow_dir=base_dir.parent / "data" / "workflows",
            log_dir=log_dir,
            log_level=os.environ.get("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper(),
            ui_origins=ui_origins,
            enable_tracing=_env_bool("ENABLE_TRACING"),
            enable_metrics=_env_bool("ENABLE_METRICS"),
            service_name=os.environ.get("OTEL_SERVICE_NAME", DEFAULT_SERVICE_NAME),
            otlp_endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None,
        )
