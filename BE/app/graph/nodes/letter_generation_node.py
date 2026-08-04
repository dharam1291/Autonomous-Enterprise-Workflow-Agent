from __future__ import annotations

from app.domain.models import WorkflowStatus
from app.graph.state import ClaimGraphState
from app.llm.base import LLMClient


class LetterGenerationNode:
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def __call__(self, state: ClaimGraphState) -> ClaimGraphState:
        workflow = state["workflow"]
        config = state["provider_config"]
        workflow.current_step = "letter_or_summary_generation"

        if workflow.status in {WorkflowStatus.APPROVED, WorkflowStatus.APPROVED_BY_HUMAN}:
            workflow.generated_letter = self._llm_client.draft_letter(workflow, config, "approval")
        elif workflow.status in {WorkflowStatus.REJECTED, WorkflowStatus.REJECTED_BY_HUMAN}:
            workflow.generated_letter = self._llm_client.draft_letter(workflow, config, "rejection")
        elif workflow.status == WorkflowStatus.NEEDS_MORE_INFO:
            workflow.generated_letter = self._llm_client.draft_letter(workflow, config, "more_info")

        workflow.add_audit("Letter or summary generation completed.")
        return state
