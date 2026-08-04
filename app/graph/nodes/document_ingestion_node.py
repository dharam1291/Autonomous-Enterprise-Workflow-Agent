from __future__ import annotations

from app.domain.models import WorkflowStatus
from app.graph.state import ClaimGraphState


class DocumentIngestionNode:
    def __call__(self, state: ClaimGraphState) -> ClaimGraphState:
        workflow = state["workflow"]
        config = state["provider_config"]
        workflow.current_step = "document_ingestion"

        if not config.enabled or not config.features.get("auto_processing", True):
            workflow.status = WorkflowStatus.UNSUPPORTED_PROVIDER
            workflow.recommendation = "unsupported_provider"
            workflow.generated_letter = (
                f"Claims for provider '{workflow.provider_id}' are currently not enabled for automated processing."
            )
            workflow.add_audit("Provider is disabled by feature flag.")
            return state

        workflow.status = WorkflowStatus.PROCESSING
        workflow.add_audit("Document ingestion completed.")
        return state
