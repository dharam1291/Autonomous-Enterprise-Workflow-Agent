from __future__ import annotations

from pathlib import Path

from app.config.tenant_config import TenantConfigRepository
from app.domain.models import ProviderConfig, WorkflowState
from app.graph.nodes.document_ingestion_node import DocumentIngestionNode
from app.services.rule_engine import RuleEngine
from app.storage.state_store import JsonWorkflowStateStore
from app.workflow.orchestrator import ClaimWorkflowOrchestrator


def build_orchestrator(tmp_path: Path) -> ClaimWorkflowOrchestrator:
    return ClaimWorkflowOrchestrator(
        config_repository=TenantConfigRepository(Path("config")),
        state_store=JsonWorkflowStateStore(tmp_path),
        rule_engine=RuleEngine(),
    )


def test_high_value_claim_pauses_for_human_review(tmp_path: Path) -> None:
    workflow = build_orchestrator(tmp_path)

    state = workflow.start(
        tenant_id="de",
        source_name="claim.txt",
        document_text=(
            "Claim Form\n"
            "Claimant Name: Rahul Sharma\n"
            "Policy Number: ABC-987654\n"
            "Claim Amount: $14500\n"
            "Reason for Claim: Surgery\n"
        ),
    )

    assert state.status == "WAITING_FOR_HUMAN_REVIEW"
    assert state.review_task is not None
    assert state.exception_summary is not None


def test_input_guardrail_redacts_pii_before_persisting(tmp_path: Path) -> None:
    workflow = build_orchestrator(tmp_path)

    state = workflow.start(
        tenant_id="de",
        source_name="claim.txt",
        document_text=(
            "Claim Form\n"
            "Claimant Name: Rahul Sharma\n"
            "Policy Number: ABC-987654\n"
            "Claim Amount: $14500\n"
            "Reason for Claim: Surgery\n"
            "Email: rahul.sharma@example.com\n"
            "Mobile: +91 98765 43210\n"
        ),
    )

    # Contact PII never survives past the guardrail node.
    assert "rahul.sharma@example.com" not in state.document_text
    assert "98765 43210" not in state.document_text
    # Claim entities are still extracted from the redacted text.
    assert state.extracted_entities.get_value("policy_number") == "ABC-987654"
    assert state.extracted_entities.get_value("claimant_name") == "Rahul Sharma"
    # The redaction is recorded as a guardrail finding.
    assert any(f.rule_id == "INPUT_PII_REDACTION" for f in state.validation_findings)


def test_blocking_business_failure_routes_to_reject() -> None:
    # A blocking BUSINESS failure, with no HITL trigger and no extraction failure,
    # must be auto-rejected (not sent to human review). Driven at the node level so
    # it stays valid regardless of which provider a tenant is configured to use.
    from app.domain.models import (
        ValidationFinding,
        ValidationLayer,
        ValidationOutcome,
        ValidationSeverity,
    )
    from app.graph.nodes.hitl_decision_node import HitlDecisionNode
    from app.llm.clients.deterministic_client import DeterministicLLMClient

    config = ProviderConfig(entity_definitions=[], features={"hitl_review": True})
    workflow = WorkflowState(
        tenant_id="t", provider_id="p", source_name="s.txt", document_text="x"
    )
    workflow.validation_findings.append(
        ValidationFinding(
            rule_id="POLICY_NUMBER_FORMAT",
            layer=ValidationLayer.BUSINESS,
            outcome=ValidationOutcome.FAILED,
            severity=ValidationSeverity.ERROR,
            message="Policy number format is invalid.",
        )
    )

    result = HitlDecisionNode(RuleEngine(), DeterministicLLMClient())(
        {"workflow": workflow, "provider_config": config}
    )

    assert result["workflow"].status == "REJECTED"
    assert result["workflow"].recommendation == "reject"


def test_disabled_provider_routes_to_unsupported() -> None:
    # Keeps the UNSUPPORTED_PROVIDER path covered now that max_bupa is active:
    # a disabled provider must short-circuit at ingestion.
    config = ProviderConfig(enabled=False, entity_definitions=[])
    workflow = WorkflowState(
        tenant_id="t", provider_id="p", source_name="s.txt", document_text="anything"
    )

    result = DocumentIngestionNode()({"workflow": workflow, "provider_config": config})

    assert result["workflow"].status == "UNSUPPORTED_PROVIDER"


def test_pipeline_exception_marks_workflow_failed(tmp_path: Path) -> None:
    class _BoomClient:
        def classify_document(self, text, config):
            raise RuntimeError("provider exploded")

        def extract_entities(self, text, config):  # pragma: no cover - never reached
            raise RuntimeError("unused")

        def draft_letter(self, state, config, letter_type):  # pragma: no cover
            return ""

        def draft_exception_summary(self, state, config):  # pragma: no cover
            return ""

    class _BoomFactory:
        def create(self, config):
            return _BoomClient()

    store = JsonWorkflowStateStore(tmp_path)
    workflow = ClaimWorkflowOrchestrator(
        config_repository=TenantConfigRepository(Path("config")),
        state_store=store,
        rule_engine=RuleEngine(),
        llm_provider_factory=_BoomFactory(),
    )

    state = workflow.start(
        tenant_id="de",
        source_name="claim.txt",
        document_text=(
            "Claim Form\n"
            "Claimant Name: Rahul Sharma\n"
            "Policy Number: ABC-987654\n"
            "Claim Amount: $14500\n"
            "Reason for Claim: Surgery\n"
        ),
    )

    # Exception is handled: terminal FAILED status, not a crash.
    assert state.status == "FAILED"
    assert state.recommendation == "processing_error"
    assert any(f.rule_id == "PROCESSING_ERROR" for f in state.validation_findings)
    assert any("document_classification" in event for event in state.audit_events)
    # And it is persisted, not orphaned in RECEIVED/PROCESSING.
    assert workflow.get(state.workflow_id).status == "FAILED"


def test_non_claim_document_is_invalid(tmp_path: Path) -> None:
    workflow = build_orchestrator(tmp_path)

    state = workflow.start(
        tenant_id="de",
        source_name="notes.txt",
        document_text="Team meeting notes about project planning and hiring.",
    )

    assert state.status == "INVALID_DOCUMENT"

