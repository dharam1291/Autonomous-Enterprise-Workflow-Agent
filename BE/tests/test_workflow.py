from __future__ import annotations

from pathlib import Path

from app.config.tenant_config import TenantConfigRepository
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
        tenant_id="default",
        provider_id="default",
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
        tenant_id="default",
        provider_id="default",
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


def test_disabled_provider_is_not_processed(tmp_path: Path) -> None:
    workflow = build_orchestrator(tmp_path)

    state = workflow.start(
        tenant_id="default",
        provider_id="max_bupa",
        source_name="claim.txt",
        document_text=(
            "Claim Form\n"
            "Claimant Name: Rahul Sharma\n"
            "Policy Number: ABC-987654\n"
            "Claim Amount: $4500\n"
            "Reason for Claim: Consultation\n"
        ),
    )

    assert state.status == "UNSUPPORTED_PROVIDER"


def test_non_claim_document_is_invalid(tmp_path: Path) -> None:
    workflow = build_orchestrator(tmp_path)

    state = workflow.start(
        tenant_id="default",
        provider_id="default",
        source_name="notes.txt",
        document_text="Team meeting notes about project planning and hiring.",
    )

    assert state.status == "INVALID_DOCUMENT"

