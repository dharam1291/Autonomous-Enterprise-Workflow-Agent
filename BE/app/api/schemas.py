from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.models import HumanReviewAction, WorkflowState, WorkflowStatus


class ClaimTextRequest(BaseModel):
    tenant_id: str = Field(default="default", min_length=1)
    provider_id: str = Field(default="default", min_length=1)
    document_text: str = Field(min_length=1)
    source_name: str = Field(default="inline-text", min_length=1)


class WorkflowResponse(BaseModel):
    workflow_id: str
    status: WorkflowStatus
    recommendation: str | None
    requires_human_review: bool
    summary: str | None
    state: WorkflowState


class HumanReviewRequest(BaseModel):
    action: HumanReviewAction
    reviewer: str = Field(min_length=1)
    notes: str = Field(default="")


class ProviderSummary(BaseModel):
    provider_id: str
    enabled: bool
    tenant_id: str
    display_name: str


class SampleClaim(BaseModel):
    id: str
    label: str
    tenant_id: str
    provider_id: str
    source_name: str
    document_text: str

