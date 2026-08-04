from __future__ import annotations

import json
import os

from app.domain.models import (
    ClaimEntities,
    ExtractedEntity,
    ProviderConfig,
    ValidationFinding,
    ValidationLayer,
    ValidationOutcome,
    ValidationSeverity,
    WorkflowState,
)
from app.llm.clients.base_client import LLMProviderError
from app.llm.prompts import (
    JSON_SYSTEM_PROMPT,
    LETTER_SYSTEM_PROMPT,
    classification_prompt,
    entity_extraction_prompt,
    exception_summary_prompt,
    letter_prompt,
)
from app.llm.schemas import EntityExtractionPayload


class OpenAIClient:
    def __init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMProviderError("OpenAI SDK is not installed.") from exc
        if not os.getenv("OPENAI_API_KEY"):
            raise LLMProviderError("OPENAI_API_KEY is required for the OpenAI provider.")
        self._client = OpenAI()

    def classify_document(self, text: str, config: ProviderConfig) -> ValidationFinding:
        payload = self._json_completion(classification_prompt(text, config), config)
        passed = bool(payload.get("is_claim"))
        return ValidationFinding(
            rule_id="LLM_DOCUMENT_CLASSIFICATION",
            layer=ValidationLayer.DOCUMENT,
            outcome=ValidationOutcome.PASSED if passed else ValidationOutcome.FAILED,
            severity=ValidationSeverity.BLOCKER,
            message=str(payload.get("reason") or "Document classification completed."),
            details={"matched_signals": payload.get("matched_signals", [])},
        )

    def extract_entities(self, text: str, config: ProviderConfig) -> ClaimEntities:
        entity_names = [definition.name for definition in config.entity_definitions]
        payload = EntityExtractionPayload.model_validate(
            self._json_completion(entity_extraction_prompt(text, config), config)
        )
        values = {
            name: ExtractedEntity(
                name=name,
                value=payload.entities.get(name),
                confidence=payload.confidence.get(name, 0.0),
                evidence=payload.evidence.get(name),
            )
            for name in entity_names
        }
        return ClaimEntities(values=values, conflicts=payload.conflicts)

    def draft_letter(self, state: WorkflowState, config: ProviderConfig, letter_type: str) -> str:
        return self._text_completion(letter_prompt(state, letter_type), config)

    def draft_exception_summary(self, state: WorkflowState, config: ProviderConfig) -> str:
        return self._text_completion(exception_summary_prompt(state), config)

    def _json_completion(self, prompt: str, config: ProviderConfig) -> dict:
        response = self._client.chat.completions.create(
            model=config.llm.model,
            temperature=config.llm.temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": JSON_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(f"OpenAI returned malformed JSON: {content[:200]}") from exc

    def _text_completion(self, prompt: str, config: ProviderConfig) -> str:
        response = self._client.chat.completions.create(
            model=config.llm.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": LETTER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""
