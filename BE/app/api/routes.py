from __future__ import annotations

import asyncio
import json
import logging
import queue

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.schemas import (
    ClaimTextRequest,
    GraphResponse,
    GraphView,
    HumanReviewRequest,
    ProviderSummary,
    WorkflowResponse,
)
from app.config.tenant_config import UnknownTenantError
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


# ── Health / metadata ────────────────────────────────────────────────
@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/graph", response_model=GraphResponse)
def graph_topology() -> GraphResponse:
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


# ── Synchronous claim processing (API / test compat) ────────────────
@router.post("/claims/process", response_model=WorkflowResponse)
def process_claim_text(
    request: ClaimTextRequest,
    workflow: ClaimWorkflowOrchestrator = Depends(get_orchestrator),
) -> WorkflowResponse:
    logger.info("Processing claim text: tenant=%s source=%s", request.tenant_id, request.source_name)
    try:
        state = workflow.start(
            tenant_id=request.tenant_id,
            source_name=request.source_name,
            document_text=request.document_text,
        )
    except UnknownTenantError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logger.info("Claim %s finished with status=%s", state.workflow_id, state.status)
    return response_from_state(state)


@router.post("/claims/upload", response_model=WorkflowResponse)
async def process_claim_upload(
    tenant_id: str = "de",
    file: UploadFile = File(...),
    container: AppContainer = Depends(get_container),
) -> WorkflowResponse:
    try:
        document_text = container.document_loader.load_text(file.filename or "uploaded-file", await file.read())
    except DocumentLoaderError as exc:
        logger.warning("Rejected upload %s: %s", file.filename, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("Processing claim upload: tenant=%s source=%s", tenant_id, file.filename)
    try:
        state = container.orchestrator.start(
            tenant_id=tenant_id,
            source_name=file.filename or "uploaded-file",
            document_text=document_text,
        )
    except UnknownTenantError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logger.info("Claim %s finished with status=%s", state.workflow_id, state.status)
    return response_from_state(state)


# ── Async claim processing (background + SSE) ───────────────────────
@router.post("/claims/submit", response_model=WorkflowResponse)
async def submit_claim_upload(
    background_tasks: BackgroundTasks,
    tenant_id: str = "de",
    file: UploadFile = File(...),
    container: AppContainer = Depends(get_container),
) -> WorkflowResponse:
    try:
        document_text = container.document_loader.load_text(file.filename or "uploaded-file", await file.read())
    except DocumentLoaderError as exc:
        logger.warning("Rejected upload %s: %s", file.filename, exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info("Submitting claim (async): tenant=%s source=%s", tenant_id, file.filename)
    try:
        state = container.orchestrator.create_workflow(
            tenant_id=tenant_id,
            source_name=file.filename or "uploaded-file",
            document_text=document_text,
        )
    except UnknownTenantError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    container.event_bus.create_channel(state.workflow_id)
    background_tasks.add_task(
        container.orchestrator.process_workflow,
        state,
        container.event_bus,
    )
    return response_from_state(state)


@router.get("/claims/{workflow_id}/stream")
async def stream_workflow(
    workflow_id: str,
    container: AppContainer = Depends(get_container),
) -> StreamingResponse:
    channel = container.event_bus.get_channel(workflow_id)

    if channel is None:
        try:
            state = container.orchestrator.get(workflow_id)
        except WorkflowNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}") from exc

        async def _completed():
            yield _sse("complete", {"workflow_id": workflow_id, "status": str(state.status)})

        return StreamingResponse(
            _completed(),
            media_type="text/event-stream",
            headers=_SSE_HEADERS,
        )

    return StreamingResponse(
        _drain_channel(channel, workflow_id, container),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


async def _drain_channel(channel: queue.Queue, workflow_id: str, container: AppContainer):
    idle = 0.0
    max_idle = 120.0
    try:
        while idle < max_idle:
            try:
                event = channel.get_nowait()
                idle = 0.0
                yield _sse(event["type"], event)
                if event["type"] in ("complete", "error"):
                    return
            except queue.Empty:
                await asyncio.sleep(0.4)
                idle += 0.4
    finally:
        container.event_bus.close_channel(workflow_id)


# ── Workflow queries ─────────────────────────────────────────────────
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


# ── Human review (sync) ─────────────────────────────────────────────
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


# ── Human review (async + SSE) ──────────────────────────────────────
@router.post("/workflows/{workflow_id}/review/stream", response_model=WorkflowResponse)
def review_workflow_stream(
    workflow_id: str,
    request: HumanReviewRequest,
    background_tasks: BackgroundTasks,
    container: AppContainer = Depends(get_container),
) -> WorkflowResponse:
    logger.info("Reviewing workflow (async) %s: action=%s reviewer=%s", workflow_id, request.action, request.reviewer)
    try:
        state = container.orchestrator.prepare_resume(
            workflow_id=workflow_id,
            action=request.action,
            reviewer=request.reviewer,
            notes=request.notes,
        )
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Workflow not found: {workflow_id}") from exc
    except InvalidWorkflowTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    container.event_bus.create_channel(state.workflow_id)
    background_tasks.add_task(
        container.orchestrator.process_resume,
        state,
        container.event_bus,
    )
    return response_from_state(state)


# ── Helpers ──────────────────────────────────────────────────────────
def response_from_state(state: WorkflowState) -> WorkflowResponse:
    return WorkflowResponse(
        workflow_id=state.workflow_id,
        status=state.status,
        recommendation=state.recommendation,
        requires_human_review=state.status == WorkflowStatus.WAITING_FOR_HUMAN_REVIEW,
        summary=state.exception_summary or state.generated_letter,
        state=state,
    )
