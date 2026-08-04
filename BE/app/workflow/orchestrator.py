from __future__ import annotations

import time
from datetime import UTC, datetime

from app.config.tenant_config import TenantConfigRepository
from app.domain.models import (
    HumanReviewAction,
    WorkflowState,
    WorkflowStatus,
)
from app.graph.builder import ClaimWorkflowGraph
from app.llm.factory.provider_factory import LLMProviderFactory
from app.observability import record_claim_result, workflow_span
from app.services.rule_engine import RuleEngine
from app.storage.state_store import WorkflowStateStore


class WorkflowNotFoundError(RuntimeError):
    """Raised when a workflow id cannot be found."""


class InvalidWorkflowTransitionError(RuntimeError):
    """Raised when a requested workflow transition is not allowed."""


class ClaimWorkflowOrchestrator:
    def __init__(
        self,
        config_repository: TenantConfigRepository,
        state_store: WorkflowStateStore,
        rule_engine: RuleEngine | None = None,
        llm_provider_factory: LLMProviderFactory | None = None,
    ) -> None:
        self._config_repository = config_repository
        self._state_store = state_store
        self._llm_provider_factory = llm_provider_factory or LLMProviderFactory()
        self._rule_engine = rule_engine or RuleEngine()

    def start(self, tenant_id: str, provider_id: str, source_name: str, document_text: str) -> WorkflowState:
        started = time.perf_counter()
        with workflow_span(
            "claim.process",
            **{"claim.tenant": tenant_id, "claim.provider": provider_id, "claim.source": source_name},
        ) as span:
            state = WorkflowState(
                tenant_id=tenant_id,
                provider_id=provider_id,
                source_name=source_name,
                document_text=document_text,
            )
            state.add_audit("Workflow received.")
            self._state_store.create(state)
            config = self._config_repository.get(tenant_id=tenant_id, provider_id=provider_id)
            llm_client = self._llm_provider_factory.create(config)
            graph = ClaimWorkflowGraph(llm_client=llm_client, rule_engine=self._rule_engine)
            result = graph.run({"workflow": state, "provider_config": config})
            final = self._state_store.update(result["workflow"])
            self._observe(span, final, tenant_id, provider_id, started)
            return final

    def get(self, workflow_id: str) -> WorkflowState:
        state = self._state_store.get(workflow_id)
        if state is None:
            raise WorkflowNotFoundError(workflow_id)
        return state

    def list(self, status: WorkflowStatus | None = None) -> list[WorkflowState]:
        return self._state_store.list_by_status(status)

    def resume_after_human_review(
        self,
        workflow_id: str,
        action: HumanReviewAction,
        reviewer: str,
        notes: str,
    ) -> WorkflowState:
        action = HumanReviewAction(action)
        state = self.get(workflow_id)
        if state.status != WorkflowStatus.WAITING_FOR_HUMAN_REVIEW or state.review_task is None:
            raise InvalidWorkflowTransitionError(
                f"Workflow {workflow_id} is not waiting for human review."
            )

        state.review_task.status = "COMPLETED"
        state.review_task.reviewer = reviewer
        state.review_task.action = action
        state.review_task.notes = notes
        state.review_task.completed_at = datetime.now(UTC)
        state.add_audit(f"Human review completed by {reviewer} with action '{action}'.")

        started = time.perf_counter()
        with workflow_span(
            "claim.resume",
            **{
                "claim.workflow_id": workflow_id,
                "claim.tenant": state.tenant_id,
                "claim.provider": state.provider_id,
                "review.action": str(action.value),
            },
        ) as span:
            config = self._config_repository.get(tenant_id=state.tenant_id, provider_id=state.provider_id)
            llm_client = self._llm_provider_factory.create(config)
            graph = ClaimWorkflowGraph(llm_client=llm_client, rule_engine=self._rule_engine)
            result = graph.resume_after_review({"workflow": state, "provider_config": config})
            final = self._state_store.update(result["workflow"])
            self._observe(span, final, state.tenant_id, state.provider_id, started)
            return final

    @staticmethod
    def _observe(span, state: WorkflowState, tenant_id: str, provider_id: str, started: float) -> None:
        status = getattr(state.status, "value", str(state.status))
        if span is not None:
            span.set_attribute("claim.workflow_id", state.workflow_id)
            span.set_attribute("claim.status", status)
        record_claim_result(tenant_id, provider_id, status, time.perf_counter() - started)
