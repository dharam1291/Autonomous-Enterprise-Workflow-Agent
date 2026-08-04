from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.domain.models import (
    HumanReviewAction,
    HumanReviewTask,
    ValidationOutcome,
    ValidationSeverity,
    WorkflowStatus,
)
from app.graph.state import ClaimGraphState
from app.llm.base import LLMClient
from app.services.rule_engine import RuleEngine


class HitlDecisionNode:
    def __init__(self, rule_engine: RuleEngine, llm_client: LLMClient) -> None:
        self._rule_engine = rule_engine
        self._llm_client = llm_client

    def __call__(self, state: ClaimGraphState) -> ClaimGraphState:
        workflow = state["workflow"]
        config = state["provider_config"]
        workflow.current_step = "hitl_decision"

        if workflow.review_task and workflow.review_task.status == "COMPLETED":
            self._apply_completed_review(workflow)
            return state

        workflow.add_findings(self._rule_engine.validate_hitl(workflow, config))
        workflow.add_audit("HITL policy validation completed.")

        hitl_failed = any(
            finding.layer == "HITL" and finding.outcome == ValidationOutcome.FAILED
            for finding in workflow.validation_findings
        )
        blocking_failures = [
            finding
            for finding in workflow.validation_findings
            if finding.outcome == ValidationOutcome.FAILED
            and finding.severity in {ValidationSeverity.ERROR, ValidationSeverity.BLOCKER}
            and finding.layer != "HITL"
        ]

        if hitl_failed or blocking_failures:
            if config.features.get("hitl_review", True) and (
                hitl_failed or any(finding.layer == "EXTRACTION" for finding in blocking_failures)
            ):
                workflow.status = WorkflowStatus.WAITING_FOR_HUMAN_REVIEW
                workflow.recommendation = "manual_review"
                workflow.current_step = "hitl_waiting"
                workflow.review_task = HumanReviewTask(
                    assigned_role=config.hitl_policy.escalation_role,
                    due_at=datetime.now(UTC) + timedelta(minutes=config.hitl_policy.review_timeout_minutes),
                )
                workflow.exception_summary = self._llm_client.draft_exception_summary(workflow, config)
                workflow.add_audit("Workflow checkpointed and paused for human review.")
                return state

            workflow.status = WorkflowStatus.REJECTED
            workflow.recommendation = "reject"
            workflow.current_step = "letter_or_summary_generation"
            workflow.add_audit("Workflow routed to rejection letter generation.")
            return state

        workflow.status = WorkflowStatus.APPROVED
        workflow.recommendation = "approve"
        workflow.current_step = "letter_or_summary_generation"
        workflow.add_audit("Workflow routed to approval letter generation.")
        return state

    @staticmethod
    def _apply_completed_review(workflow) -> None:
        action = HumanReviewAction(workflow.review_task.action)
        if action == HumanReviewAction.APPROVE:
            workflow.status = WorkflowStatus.APPROVED_BY_HUMAN
            workflow.recommendation = "approve_after_review"
        elif action == HumanReviewAction.REJECT:
            workflow.status = WorkflowStatus.REJECTED_BY_HUMAN
            workflow.recommendation = "reject_after_review"
        else:
            workflow.status = WorkflowStatus.NEEDS_MORE_INFO
            workflow.recommendation = "request_more_information"
        workflow.current_step = "letter_or_summary_generation"
        workflow.add_audit("Workflow resumed after human review.")
