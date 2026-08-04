from __future__ import annotations

from pydantic import BaseModel, Field


class EntityExtractionPayload(BaseModel):
    entities: dict[str, str | None] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    evidence: dict[str, str | None] = Field(default_factory=dict)
    conflicts: dict[str, list[str]] = Field(default_factory=dict)
