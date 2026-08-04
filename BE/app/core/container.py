from __future__ import annotations

from dataclasses import dataclass

from app.config.provider_config import ProviderConfigRepository
from app.core.settings import AppSettings
from app.llm.provider_factory import LLMProviderFactory
from app.services.document_loader import DocumentLoader
from app.services.rule_engine import RuleEngine
from app.services.sample_repository import SampleRepository
from app.storage.state_store import JsonWorkflowStateStore
from app.workflow.orchestrator import ClaimWorkflowOrchestrator


@dataclass(frozen=True)
class AppContainer:
    settings: AppSettings
    config_repository: ProviderConfigRepository
    state_store: JsonWorkflowStateStore
    document_loader: DocumentLoader
    sample_repository: SampleRepository
    orchestrator: ClaimWorkflowOrchestrator


def build_container(settings: AppSettings) -> AppContainer:
    config_repository = ProviderConfigRepository(settings.config_dir)
    state_store = JsonWorkflowStateStore(settings.workflow_dir)
    orchestrator = ClaimWorkflowOrchestrator(
        config_repository=config_repository,
        state_store=state_store,
        rule_engine=RuleEngine(),
        llm_provider_factory=LLMProviderFactory(),
    )
    return AppContainer(
        settings=settings,
        config_repository=config_repository,
        state_store=state_store,
        document_loader=DocumentLoader(),
        sample_repository=SampleRepository(settings.samples_dir),
        orchestrator=orchestrator,
    )
