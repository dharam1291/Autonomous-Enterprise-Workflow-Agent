from __future__ import annotations

from typing import Protocol

from app.domain.models import ClaimEntities, ProviderConfig, ValidationFinding, WorkflowState


class LLMProviderError(RuntimeError):
    """Raised when an LLM provider cannot complete a workflow operation."""


class LLMClient(Protocol):
    def classify_document(self, text: str, config: ProviderConfig) -> ValidationFinding:
        ...

    def extract_entities(self, text: str, config: ProviderConfig) -> ClaimEntities:
        ...

    def draft_letter(self, state: WorkflowState, config: ProviderConfig, letter_type: str) -> str:
        ...

    def draft_exception_summary(self, state: WorkflowState, config: ProviderConfig) -> str:
        ...
