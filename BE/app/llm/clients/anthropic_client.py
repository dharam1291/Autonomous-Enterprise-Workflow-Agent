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


class AnthropicClient:
    def __init__(self) -> None:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise LLMProviderError("Anthropic SDK is not installed.") from exc
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise LLMProviderError("ANTHROPIC_API_KEY is required for the Anthropic provider.")
        self._client = Anthropic()

    def classify_document(self, text: str, config: ProviderConfig) -> ValidationFinding:
        payload = self._json_message(classification_prompt(text, config), config)
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
            self._json_message(entity_extraction_prompt(text, config), config)
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
        return self._text_message(letter_prompt(state, letter_type), config)

    def draft_exception_summary(self, state: WorkflowState, config: ProviderConfig) -> str:
        return self._text_message(exception_summary_prompt(state), config)

    def _json_message(self, prompt: str, config: ProviderConfig) -> dict:
        response = self._client.messages.create(
            model=config.llm.model,
            max_tokens=config.llm.max_tokens,
            temperature=config.llm.temperature,
            system=JSON_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMProviderError(f"Anthropic returned malformed JSON: {text[:200]}") from exc

    def _text_message(self, prompt: str, config: ProviderConfig) -> str:
        response = self._client.messages.create(
            model=config.llm.model,
            max_tokens=config.llm.max_tokens,
            temperature=0.2,
            system=LETTER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
