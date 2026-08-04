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
from app.llm.base import LLMProviderError
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
        payload = self._json_message(
            (
                "Classify whether this is a supported insurance claim document. "
                "Return JSON with keys is_claim, reason, and matched_signals.\n\n"
                f"Signals: {config.document_signals}\n\nDocument:\n{text}"
            ),
            config,
        )
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
            self._json_message(
                (
                    "Extract the requested insurance claim entities. Return JSON with keys "
                    "entities, confidence, evidence, and conflicts. Use null for missing values.\n\n"
                    f"Entities: {entity_names}\n\nDocument:\n{text}"
                ),
                config,
            )
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
        return self._text_message(
            "Draft a concise professional claim {letter_type} letter from this workflow state:\n{state}".format(
                letter_type=letter_type,
                state=state.model_dump_json(),
            ),
            config,
        )

    def draft_exception_summary(self, state: WorkflowState, config: ProviderConfig) -> str:
        return self._text_message(
            f"Draft a concise manual review exception summary from this workflow state:\n{state.model_dump_json()}",
            config,
        )

    def _json_message(self, prompt: str, config: ProviderConfig) -> dict:
        response = self._client.messages.create(
            model=config.llm.model,
            max_tokens=config.llm.max_tokens,
            temperature=config.llm.temperature,
            system="You extract and validate insurance claim data. Return JSON only.",
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
            system="You draft clear, compliant insurance claim correspondence.",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
