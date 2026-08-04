from __future__ import annotations

from app.domain.models import ProviderConfig, ValidationFinding, ValidationLayer, ValidationOutcome, ValidationSeverity


class DocumentClassifier:
    def classify(self, text: str, config: ProviderConfig) -> ValidationFinding:
        normalized = text.lower()
        matches = [signal for signal in config.document_signals if signal.lower() in normalized]
        passed = len(matches) >= config.minimum_signal_match
        return ValidationFinding(
            rule_id="DOCUMENT_TYPE_SIGNAL_MATCH",
            layer=ValidationLayer.DOCUMENT,
            outcome=ValidationOutcome.PASSED if passed else ValidationOutcome.FAILED,
            severity=ValidationSeverity.BLOCKER,
            message=(
                "Document appears to be a claim document."
                if passed
                else "Document does not contain enough claim-specific signals."
            ),
            details={
                "matched_signals": matches,
                "minimum_signal_match": config.minimum_signal_match,
            },
        )

