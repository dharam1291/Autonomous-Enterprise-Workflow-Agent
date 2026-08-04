from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SampleDocument:
    id: str
    label: str
    tenant_id: str
    provider_id: str
    source_name: str
    document_text: str


class SampleRepository:
    def __init__(self, samples_dir: Path) -> None:
        self._samples_dir = samples_dir

    def list(self) -> list[SampleDocument]:
        if not self._samples_dir.exists():
            return []
        return [self._load(path) for path in sorted(self._samples_dir.glob("*.json"))]

    @staticmethod
    def _load(path: Path) -> SampleDocument:
        payload = json.loads(path.read_text(encoding="utf-8"))
        label = path.stem.replace("_", " ").title()
        return SampleDocument(
            id=path.stem,
            label=label,
            tenant_id=payload.get("tenant_id", "default"),
            provider_id=payload.get("provider_id", "default"),
            source_name=payload.get("source_name", path.name),
            document_text=payload["document_text"],
        )
