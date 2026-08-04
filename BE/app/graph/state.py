from __future__ import annotations

from typing import TypedDict

from app.domain.models import ProviderConfig, WorkflowState


class ClaimGraphState(TypedDict):
    workflow: WorkflowState
    provider_config: ProviderConfig
