"""Minimal Composio webhook HTTP server (aiohttp) — not a full Lexi FastAPI app."""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
from typing import Any

from aiohttp import web

from app.workflows.webhooks import accept_composio_webhook

logger = logging.getLogger(__name__)

WEBHOOK_PATH = "/webhooks/composio"


async def _composio_webhook_handler(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception as exc:
        return web.json_response(
            {"ok": False, "queued": False, "error": f"invalid_json: {exc}"},
            status=400,
        )

    if not isinstance(payload, dict):
        return web.json_response(
            {"ok": False, "queued": False, "error": "payload_must_be_object"},
            status=400,
        )

    try:
        result = accept_composio_webhook(payload)
    except Exception as exc:
        logger.exception("Composio webhook handler failed.")
        return web.json_response(
            {
                "ok": False,
                "queued": False,
                "error": f"{type(exc).__name__}: {exc}",
            },
            status=202,
        )

    return web.json_response(result, status=202)


async def _health_handler(_request: web.Request) -> web.Response:
    from app.bot.teams_conversation_store import load_conversation_reference, teams_delivery_ready
    from app.config import settings

    return web.json_response(
        {
            "status": "ok",
            "service": "lexi-worker",
            "webhook_path": WEBHOOK_PATH,
            "lexi_write_mode": settings.lexi_write_mode,
            "teams_cards_ready": teams_delivery_ready(),
            "teams_conversation_captured": load_conversation_reference() is not None,
        }
    )


def _build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/api/health", _health_handler)
    app.router.add_post(WEBHOOK_PATH, _composio_webhook_handler)
    return app


class WebhookServerThread:
    """Run aiohttp webhook server in a background thread."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self._port}{WEBHOOK_PATH}"

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            app = _build_app()
            runner = web.AppRunner(app)
            self._runner = runner
            loop.run_until_complete(runner.setup())
            site = web.TCPSite(runner, self._host, self._port)
            loop.run_until_complete(site.start())
            logger.info("Lexi webhook listening on %s", self.url)
            print(f"[lexi-worker] Composio webhook → {self.url}", file=sys.stderr, flush=True)
            loop.run_forever()

        self._thread = threading.Thread(target=_run, name="lexi-webhook", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._loop is None or self._runner is None:
            return

        async def _shutdown() -> None:
            await self._runner.cleanup()

        try:
            asyncio.run_coroutine_threadsafe(_shutdown(), self._loop).result(timeout=5)
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            logger.exception("Webhook server shutdown error.")
