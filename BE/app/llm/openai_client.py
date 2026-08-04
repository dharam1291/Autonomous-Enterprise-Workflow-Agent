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
        prompt = (
            "Classify whether this document is a supported insurance claim document. "
            "Return JSON with keys is_claim, reason, and matched_signals.\n\n"
            f"Signals: {config.document_signals}\n\nDocument:\n{text}"
        )
        payload = self._json_completion(prompt, config)
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
        prompt = (
            "Extract the requested insurance claim entities. Return strict JSON with keys "
            "entities, confidence, evidence, and conflicts. Use null for missing values.\n\n"
            f"Entities: {entity_names}\n\nDocument:\n{text}"
        )
        payload = EntityExtractionPayload.model_validate(self._json_completion(prompt, config))
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
        return self._text_completion(
            "Draft a concise professional claim {letter_type} letter from this workflow state:\n{state}".format(
                letter_type=letter_type,
                state=state.model_dump_json(),
            ),
            config,
        )

    def draft_exception_summary(self, state: WorkflowState, config: ProviderConfig) -> str:
        return self._text_completion(
            f"Draft a concise manual review exception summary from this workflow state:\n{state.model_dump_json()}",
            config,
        )

    def _json_completion(self, prompt: str, config: ProviderConfig) -> dict:
        response = self._client.chat.completions.create(
            model=config.llm.model,
            temperature=config.llm.temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "You extract and validate insurance claim data as JSON only."},
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
                {"role": "system", "content": "You draft clear, compliant insurance claim correspondence."},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content or ""
