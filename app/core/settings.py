from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    base_dir: Path
    config_dir: Path
    workflow_dir: Path
    static_dir: Path

    @classmethod
    def from_project_root(cls) -> "AppSettings":
        base_dir = Path(__file__).resolve().parents[2]
        return cls(
            base_dir=base_dir,
            config_dir=base_dir / "config",
            workflow_dir=base_dir / "data" / "workflows",
            static_dir=base_dir / "app" / "static",
        )
