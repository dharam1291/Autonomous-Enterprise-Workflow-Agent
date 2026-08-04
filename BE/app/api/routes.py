from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.api.schemas import ClaimTextRequest, HumanReviewRequest, ProviderSummary, WorkflowResponse
from app.core.container import AppContainer
from app.domain.models import WorkflowState, WorkflowStatus
from app.services.document_loader import DocumentLoaderError
from app.workflow.orchestrator import (
    ClaimWorkflowOrchestrator,
    InvalidWorkflowTransitionError,
    WorkflowNotFoundError,
)

router = APIRouter()


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def get_orchestrator(container: AppContainer = Depends(get_container)) -> ClaimWorkflowOrchestrator:
    return container.orchestrator


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/providers", response_model=list[ProviderSummary])
def providers(container: AppContainer = Depends(get_container)) -> list[ProviderSummary]:
    return [
        ProviderSummary(
            provider_id=config.provider_id,
            tenant_id=config.tenant_id,
            display_name=config.display_name,
            enabled=config.enabled,
        )
        for config in container.config_repository.list()
    ]


@router.post("/claims/process", response_model=WorkflowResponse)
def process_claim_text(
    request: ClaimTextRequest,
    workflow: ClaimWorkflowOrchestrator = Depends(get_orchestrator),
) -> WorkflowResponse:
    state = workflow.start(
        tenant_id=request.tenant_id,
        provider_id=request.provider_id,
        source_name=request.source_name,
        document_text=request.document_text,
    )
    return response_from_state(state)


@router.post("/claims/upload", response_model=WorkflowResponse)
async def process_claim_upload(
    tenant_id: str = "default",
    provider_id: str = "default",
    file: UploadFile = File(...),
    container: AppContainer = Depends(get_container),
) -> WorkflowResponse:
    try:
        document_text = container.document_loader.load_text(file.filename or "uploaded-file", await file.read())
    except DocumentLoaderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    state = container.orchestrator.start(
        tenant_id=tenant_id,
        provider_id=provider_id,
        source_name=file.filename or "uploaded-file",
        document_text=document_text,
    )
    return response_from_state(state)


@router.get("/workflows", response_model=list[WorkflowState])
def list_workflows(
    status: WorkflowStatus | None = None,
    workflow: ClaimWorkflowOrchestrator = Depends(get_orchestrator),
) -> list[WorkflowState]:
    return workflow.list(status)


@router.get("/workflows/{workflow_id}", response_model=WorkflowState)
def get_workflow(
    workflow_id: str,
    workflow: ClaimWorkflowOrchestrator = Depends(get_orchestrator),
) -> WorkflowState:
    try:
        return workflow.get(workflow_id)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}") from exc


@router.post("/workflows/{workflow_id}/review", response_model=WorkflowResponse)
def review_workflow(
    workflow_id: str,
    request: HumanReviewRequest,
    workflow: ClaimWorkflowOrchestrator = Depends(get_orchestrator),
) -> WorkflowResponse:
    try:
        state = workflow.resume_after_human_review(
            workflow_id=workflow_id,
            action=request.action,
            reviewer=request.reviewer,
            notes=request.notes,
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}") from exc
    except InvalidWorkflowTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return response_from_state(state)


def response_from_state(state: WorkflowState) -> WorkflowResponse:
    return WorkflowResponse(
        workflow_id=state.workflow_id,
        status=state.status,
        recommendation=state.recommendation,
        requires_human_review=state.status == WorkflowStatus.WAITING_FOR_HUMAN_REVIEW,
        summary=state.exception_summary or state.generated_letter,
        state=state,
    )
