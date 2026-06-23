"""Optional debug dashboard only — production uses Hermes :3978 + headless Lexi worker.

Teams chat: Azure Bot → Hermes gateway (:3978) — NOT this app.
Inbound email: Lexi worker (embedded in hermes_mcp_server.py or `python -m app.worker`).
Proactive Teams cards: lexi_register_teams_conversation + TEAMS_* in .env.

Enable this module only for local audit UI:
    LEXI_DASHBOARD_ENABLED=true uvicorn app.main:create_app --factory --port 8080
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from scripts.init_lexi_db import init_lexi_db

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    if os.getenv("LEXI_DASHBOARD_ENABLED", "false").lower() not in {"1", "true", "yes"}:
        app = FastAPI(title="Lexi (disabled)")
        init_lexi_db()

        @app.get("/")
        def disabled() -> dict[str, str]:
            return {
                "status": "disabled",
                "message": (
                    "Lexi FastAPI server is not used in production. "
                    "Run Hermes gateway for Teams and embed Lexi worker via MCP. "
                    "Set LEXI_DASHBOARD_ENABLED=true for optional audit UI."
                ),
            }

        return app

    from app.dashboard.routes import router as dashboard_router

    init_lexi_db()
    app = FastAPI(title="Lexi Audit Dashboard (debug)")
    app.mount("/static", StaticFiles(directory="app/dashboard/static"), name="static")
    app.include_router(dashboard_router)

    @app.get("/api/health")
    def health() -> dict[str, object]:
        from app.bot.teams_conversation_store import load_conversation_reference, teams_delivery_ready
        from app.config import settings
        from app.worker.runner import is_worker_running

        return {
            "status": "ok",
            "service": "lexi-dashboard-debug",
            "teams_mode": "hermes_only",
            "worker_running": is_worker_running(),
            "teams_cards_ready": teams_delivery_ready(),
            "teams_conversation_captured": load_conversation_reference() is not None,
            "lexi_write_mode": settings.lexi_write_mode,
            "note": "Production: Hermes :3978 + python -m app.worker (optional webhook)",
        }

    logger.warning(
        "Lexi debug dashboard enabled — NOT for production Teams or email ingress."
    )
    return app


app = create_app()
