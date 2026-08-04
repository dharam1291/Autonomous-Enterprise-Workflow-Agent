from __future__ import annotations

import re
from collections import defaultdict

from app.domain.models import ClaimEntities, ExtractedEntity, ProviderConfig


class ConfigDrivenEntityExtractor:
    def extract(self, text: str, config: ProviderConfig) -> ClaimEntities:
        values: dict[str, ExtractedEntity] = {}
        conflicts: dict[str, list[str]] = {}

        for definition in config.entity_definitions:
            candidates = self._extract_candidates(text, definition.patterns)
            unique_candidates = self._unique_preserving_order(candidates)
            selected = unique_candidates[0] if unique_candidates else None
            confidence = 0.92 if selected else 0.0

            if len(unique_candidates) > 1:
                conflicts[definition.name] = unique_candidates
                confidence = 0.65

            values[definition.name] = ExtractedEntity(
                name=definition.name,
                value=selected,
                confidence=confidence,
                evidence=selected,
            )

        return ClaimEntities(values=values, conflicts=conflicts)

    @staticmethod
    def _extract_candidates(text: str, patterns: list[str]) -> list[str]:
        candidates: list[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
                if match.groupdict().get("value"):
                    candidates.append(match.group("value").strip())
                elif match.groups():
                    candidates.append(match.group(1).strip())
                else:
                    candidates.append(match.group(0).strip())
        return candidates

    @staticmethod
    def _unique_preserving_order(values: list[str]) -> list[str]:
        seen: set[str] = set()
        unique_values: list[str] = []
        for value in values:
            normalized = re.sub(r"\s+", " ", value).strip().lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_values.append(value)
        return unique_values

