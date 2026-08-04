from __future__ import annotations

from pathlib import Path

from app.config.provider_config import ProviderConfigRepository
from app.services.document_classifier import DocumentClassifier
from app.services.entity_extractor import ConfigDrivenEntityExtractor
from app.services.letter_generator import LetterGenerator
from app.services.rule_engine import RuleEngine
from app.storage.state_store import JsonWorkflowStateStore
from app.workflow.orchestrator import ClaimWorkflowOrchestrator


def build_orchestrator(tmp_path: Path) -> ClaimWorkflowOrchestrator:
    return ClaimWorkflowOrchestrator(
        config_repository=ProviderConfigRepository(Path("config/providers")),
        state_store=JsonWorkflowStateStore(tmp_path),
        classifier=DocumentClassifier(),
        extractor=ConfigDrivenEntityExtractor(),
        rule_engine=RuleEngine(),
        letter_generator=LetterGenerator(),
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

