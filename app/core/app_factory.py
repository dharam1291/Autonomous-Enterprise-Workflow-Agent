from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.container import build_container
from app.core.settings import AppSettings


def create_app(settings: AppSettings | None = None) -> FastAPI:
    settings = settings or AppSettings.from_project_root()
    app = FastAPI(
        title="Autonomous Enterprise Workflow Agent",
        version="0.2.0",
        description="POC API and UI for claim validation with LangGraph orchestration and HITL pause/resume.",
    )
    app.state.container = build_container(settings)
    app.include_router(router)

    if settings.static_dir.exists():
        app.mount("/static", StaticFiles(directory=settings.static_dir), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(settings.static_dir / "index.html")

    return app
