from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.api.schemas import (
    ClaimTextRequest,
    GraphResponse,
    GraphView,
    HumanReviewRequest,
    ProviderSummary,
    WorkflowResponse,
)
from app.core.container import AppContainer
from app.domain.models import WorkflowState, WorkflowStatus
from app.graph.builder import ClaimWorkflowGraph
from app.services.document_loader import DocumentLoaderError
from app.workflow.orchestrator import (
    ClaimWorkflowOrchestrator,
    InvalidWorkflowTransitionError,
    WorkflowNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def get_orchestrator(container: AppContainer = Depends(get_container)) -> ClaimWorkflowOrchestrator:
    return container.orchestrator


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/graph", response_model=GraphResponse)
def graph_topology() -> GraphResponse:
    """Return the LangGraph topology (as Mermaid) for the UI to render."""
    graph = ClaimWorkflowGraph.for_visualization()
    return GraphResponse(
        main=GraphView(
            name="Claim processing",
            mermaid=graph.draw_mermaid(),
            nodes=graph.node_names(),
        ),
        resume=GraphView(
            name="Resume after human review",
            mermaid=graph.draw_resume_mermaid(),
            nodes=graph.resume_node_names(),
        ),
    )


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
    logger.info(
        "Processing claim text: tenant=%s provider=%s source=%s",
        request.tenant_id,
        request.provider_id,
        request.source_name,
    )
    state = workflow.start(
        tenant_id=request.tenant_id,
        provider_id=request.provider_id,
        source_name=request.source_name,
        document_text=request.document_text,
    )
    logger.info("Claim %s finished with status=%s", state.workflow_id, state.status)
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
        logger.warning("Rejected upload %s: %s", file.filename, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "Processing claim upload: tenant=%s provider=%s source=%s",
        tenant_id,
        provider_id,
        file.filename,
    )
    state = container.orchestrator.start(
        tenant_id=tenant_id,
        provider_id=provider_id,
        source_name=file.filename or "uploaded-file",
        document_text=document_text,
    )
    logger.info("Claim %s finished with status=%s", state.workflow_id, state.status)
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
    logger.info("Reviewing workflow %s: action=%s reviewer=%s", workflow_id, request.action, request.reviewer)
    try:
        state = workflow.resume_after_human_review(
            workflow_id=workflow_id,
            action=request.action,
            reviewer=request.reviewer,
            notes=request.notes,
        )
    except WorkflowNotFoundError as exc:
        logger.warning("Review failed, workflow not found: %s", workflow_id)
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}") from exc
    except InvalidWorkflowTransitionError as exc:
        logger.warning("Review failed for %s: %s", workflow_id, exc)
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
