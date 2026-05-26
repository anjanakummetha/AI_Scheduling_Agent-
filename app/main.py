"""FastAPI entry point for the AI Scheduling Agent demo."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.dashboard.routes import router as dashboard_router
from app.database import init_db


def create_app() -> FastAPI:
    app = FastAPI(title="AI Scheduling Agent")
    app.mount("/static", StaticFiles(directory="app/dashboard/static"), name="static")
    app.include_router(dashboard_router)

    @app.on_event("startup")
    def startup() -> None:
        init_db()

    return app


app = create_app()
