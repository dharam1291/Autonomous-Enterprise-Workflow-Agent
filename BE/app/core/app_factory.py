from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.container import build_container
from app.core.settings import AppSettings


def create_app(settings: AppSettings | None = None) -> FastAPI:
    settings = settings or AppSettings.from_project_root()
    app = FastAPI(
        title="Autonomous Enterprise Workflow Agent",
        version="0.2.0",
        description="API for claim validation with LangGraph orchestration and HITL pause/resume.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ui_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.container = build_container(settings)
    app.include_router(router)

    return app
