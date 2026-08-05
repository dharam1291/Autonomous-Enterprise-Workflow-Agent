from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class EntityExtractionPayload(BaseModel):
    entities: dict[str, str | None] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    evidence: dict[str, str | None] = Field(default_factory=dict)
    conflicts: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _normalise_llm_output(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        entities = data.get("entities") or {}
        for key, value in entities.items():
            if value is not None and not isinstance(value, str):
                entities[key] = str(value)

        conf_raw = data.get("confidence")
        if isinstance(conf_raw, (int, float)):
            data["confidence"] = {k: float(conf_raw) for k in entities}
        elif conf_raw is None:
            data["confidence"] = {}

        if data.get("conflicts") is None:
            data["conflicts"] = {}

        return data
