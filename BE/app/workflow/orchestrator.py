from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from app.config.tenant_config import TenantConfigRepository
from app.domain.models import (
    HumanReviewAction,
    ValidationFinding,
    ValidationLayer,
    ValidationOutcome,
    ValidationSeverity,
    WorkflowState,
    WorkflowStatus,
)
from app.graph.builder import ClaimWorkflowGraph
from app.llm.factory.provider_factory import LLMProviderFactory
from app.observability import record_claim_result, workflow_span
from app.services.rule_engine import RuleEngine
from app.storage.state_store import WorkflowStateStore

logger = logging.getLogger(__name__)


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

    def start(self, tenant_id: str, source_name: str, document_text: str) -> WorkflowState:
        # Resolve the tenant first: an unknown tenant_id is a client error and
        # should surface as such, not as a persisted FAILED claim. provider_id
        # is derived from the tenant's own config, never passed by the caller.
        config = self._config_repository.get(tenant_id)
        provider_id = config.provider_id

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
            try:
                llm_client = self._llm_provider_factory.create(config)
                graph = ClaimWorkflowGraph(llm_client=llm_client, rule_engine=self._rule_engine)
                result = graph.run({"workflow": state, "provider_config": config})
                final = self._state_store.update(result["workflow"])
                self._observe(span, final, tenant_id, provider_id, started)
                return final
            except Exception as exc:  # noqa: BLE001 - pipeline must fail safe
                return self._fail(state, exc, tenant_id, provider_id, started, span)

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
            try:
                config = self._config_repository.get(state.tenant_id)
                llm_client = self._llm_provider_factory.create(config)
                graph = ClaimWorkflowGraph(llm_client=llm_client, rule_engine=self._rule_engine)
                result = graph.resume_after_review({"workflow": state, "provider_config": config})
                final = self._state_store.update(result["workflow"])
                self._observe(span, final, state.tenant_id, state.provider_id, started)
                return final
            except Exception as exc:  # noqa: BLE001 - pipeline must fail safe
                return self._fail(state, exc, state.tenant_id, state.provider_id, started, span)

    @staticmethod
    def _observe(span, state: WorkflowState, tenant_id: str, provider_id: str, started: float) -> None:
        status = getattr(state.status, "value", str(state.status))
        if span is not None:
            span.set_attribute("claim.workflow_id", state.workflow_id)
            span.set_attribute("claim.status", status)
        record_claim_result(tenant_id, provider_id, status, time.perf_counter() - started)

    def _fail(
        self,
        state: WorkflowState,
        exc: Exception,
        tenant_id: str,
        provider_id: str,
        started: float,
        span,
    ) -> WorkflowState:
        """Fail-safe terminal handling for an unexpected pipeline error.

        Marks the workflow FAILED, records where it failed and the error *type*
        (never the raw message, which could carry document content), persists it,
        and surfaces the failure to logs/metrics/trace. The full traceback goes to
        the server log only.
        """
        failed_step = state.current_step or "unknown"
        logger.exception("Workflow %s failed during '%s'", state.workflow_id, failed_step)

        state.status = WorkflowStatus.FAILED
        state.recommendation = "processing_error"
        state.generated_letter = (
            "This claim could not be processed due to an internal error. Please retry or contact support."
        )
        state.add_findings(
            [
                ValidationFinding(
                    rule_id="PROCESSING_ERROR",
                    layer=ValidationLayer.FINAL_DECISION,
                    outcome=ValidationOutcome.FAILED,
                    severity=ValidationSeverity.BLOCKER,
                    message=f"Processing failed during '{failed_step}'.",
                    details={"error_type": type(exc).__name__, "step": failed_step},
                )
            ]
        )
        state.add_audit(f"Workflow failed during '{failed_step}' ({type(exc).__name__}).")

        persisted = self._safe_persist_failure(state)
        if span is not None:
            span.record_exception(exc)
        record_claim_result(tenant_id, provider_id, WorkflowStatus.FAILED.value, time.perf_counter() - started)
        return persisted

    def _safe_persist_failure(self, state: WorkflowState) -> WorkflowState:
        try:
            return self._state_store.update(state)
        except Exception:  # noqa: BLE001 - never let persistence failure mask the original error
            logger.exception("Failed to persist FAILED state for workflow %s", state.workflow_id)
            return state
