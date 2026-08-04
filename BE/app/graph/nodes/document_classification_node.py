from __future__ import annotations

from app.domain.models import ValidationOutcome, WorkflowStatus
from app.graph.state import ClaimGraphState
from app.llm.clients.base_client import LLMClient


class DocumentClassificationNode:
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def __call__(self, state: ClaimGraphState) -> ClaimGraphState:
        workflow = state["workflow"]
        config = state["provider_config"]
        workflow.current_step = "document_classification"
        workflow.add_audit("Document classification started.")

        finding = self._llm_client.classify_document(workflow.document_text, config)
        workflow.add_findings([finding])

        if finding.outcome == ValidationOutcome.FAILED:
            workflow.status = WorkflowStatus.INVALID_DOCUMENT
            workflow.recommendation = "invalid_document"
            workflow.current_step = "completed"
            workflow.generated_letter = "The uploaded document does not appear to be a supported claim document."
            workflow.add_audit("Workflow stopped because document classification failed.")

        return state
