from __future__ import annotations

from app.domain.models import ValidationFinding, ValidationLayer, ValidationOutcome, ValidationSeverity
from app.graph.state import ClaimGraphState
from app.services.input_guardrail import InputGuardrail


class GuardrailInputsNode:
    """Redacts contact PII from the claim text before any LLM node runs.

    Runs immediately after ingestion and before document classification (the
    first LLM touchpoint), so email/phone/etc. never leave the system to an
    external model regardless of the configured provider.
    """

    def __init__(self, guardrail: InputGuardrail | None = None) -> None:
        self._guardrail = guardrail or InputGuardrail()

    def __call__(self, state: ClaimGraphState) -> ClaimGraphState:
        workflow = state["workflow"]
        workflow.current_step = "guardrail_inputs"

        result = self._guardrail.redact(workflow.document_text)
        workflow.document_text = result.text

        if result.total:
            workflow.add_findings(
                [
                    ValidationFinding(
                        rule_id="INPUT_PII_REDACTION",
                        layer=ValidationLayer.GUARDRAIL,
                        outcome=ValidationOutcome.PASSED,
                        severity=ValidationSeverity.INFO,
                        message=f"Redacted {result.total} PII value(s) before LLM processing.",
                        details={"redacted_counts": result.counts},
                    )
                ]
            )
            workflow.add_audit(f"Input guardrail redacted PII before LLM: {result.counts}.")
        else:
            workflow.add_audit("Input guardrail found no contact PII to redact.")

        return state
