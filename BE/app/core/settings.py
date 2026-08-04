from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_UI_ORIGINS = ("http://127.0.0.1:5173", "http://localhost:5173")


@dataclass(frozen=True)
class AppSettings:
    base_dir: Path
    config_dir: Path
    workflow_dir: Path
    ui_origins: tuple[str, ...] = field(default_factory=lambda: DEFAULT_UI_ORIGINS)

    @classmethod
    def from_project_root(cls) -> "AppSettings":
        base_dir = Path(__file__).resolve().parents[2]
        origins_env = os.environ.get("UI_ORIGINS")
        ui_origins = tuple(origins_env.split(",")) if origins_env else DEFAULT_UI_ORIGINS
        return cls(
            base_dir=base_dir,
            config_dir=base_dir / "config",
            workflow_dir=base_dir.parent / "data" / "workflows",
            ui_origins=ui_origins,
        )
