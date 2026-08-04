from __future__ import annotations

from app.domain.models import ClaimEntities, ProviderConfig, ValidationFinding, WorkflowState
from app.services.document_classifier import DocumentClassifier
from app.services.entity_extractor import ConfigDrivenEntityExtractor
from app.services.letter_generator import LetterGenerator


class DeterministicLLMClient:
    """Offline implementation that preserves demo determinism and test stability."""

    def __init__(
        self,
        classifier: DocumentClassifier | None = None,
        extractor: ConfigDrivenEntityExtractor | None = None,
        letter_generator: LetterGenerator | None = None,
    ) -> None:
        self._classifier = classifier or DocumentClassifier()
        self._extractor = extractor or ConfigDrivenEntityExtractor()
        self._letter_generator = letter_generator or LetterGenerator()

    def classify_document(self, text: str, config: ProviderConfig) -> ValidationFinding:
        return self._classifier.classify(text, config)

    def extract_entities(self, text: str, config: ProviderConfig) -> ClaimEntities:
        return self._extractor.extract(text, config)

    def draft_letter(self, state: WorkflowState, config: ProviderConfig, letter_type: str) -> str:
        if letter_type == "approval":
            return self._letter_generator.approval_letter(
                state,
                human_approved=state.status == "APPROVED_BY_HUMAN",
            )
        if letter_type == "rejection":
            return self._letter_generator.rejection_letter(
                state,
                human_rejected=state.status == "REJECTED_BY_HUMAN",
            )
        return self._letter_generator.more_info_letter(state)

    def draft_exception_summary(self, state: WorkflowState, config: ProviderConfig) -> str:
        return self._letter_generator.exception_summary(state)
