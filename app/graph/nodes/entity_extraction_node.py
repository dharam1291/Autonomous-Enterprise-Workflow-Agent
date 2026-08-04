from __future__ import annotations

from app.graph.state import ClaimGraphState
from app.llm.base import LLMClient


class EntityExtractionNode:
    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def __call__(self, state: ClaimGraphState) -> ClaimGraphState:
        workflow = state["workflow"]
        config = state["provider_config"]
        workflow.current_step = "entity_extraction"
        workflow.extracted_entities = self._llm_client.extract_entities(workflow.document_text, config)
        workflow.add_audit("Entity extraction completed.")
        return state
