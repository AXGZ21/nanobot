"""Web gateway server — serves the dashboard and REST/WebSocket API."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from aiohttp import web

from loguru import logger

from nanobot.web.api import setup_routes


STATIC_DIR = Path(__file__).parent / "static"


async def on_startup(app: web.Application) -> None:
    """Initialize shared resources on server start."""
    from nanobot.config.loader import load_config, get_data_dir
    from nanobot.bus.queue import MessageBus
    from nanobot.cron.service import CronService

    config = load_config()
    app["nanobot_config"] = config
    app["data_dir"] = get_data_dir()

    # Message bus for agent communication
    bus = MessageBus()
    app["bus"] = bus

    # Cron service
    cron_store = get_data_dir() / "cron" / "jobs.json"
    cron = CronService(cron_store)
    app["cron"] = cron

    # Agent loop (lazy — only created when chat is used)
    app["agent"] = None
    app["agent_lock"] = asyncio.Lock()

    # WebSocket clients for event broadcasting
    app["ws_clients"] = set()

    logger.info("Web dashboard ready")


async def on_shutdown(app: web.Application) -> None:
    """Clean up on server shutdown."""
    agent = app.get("agent")
    if agent:
        agent.stop()
        await agent.close_mcp()

    cron = app.get("cron")
    if cron:
        cron.stop()

    # Close all WebSocket connections
    for ws in set(app.get("ws_clients", [])):
        await ws.close()


async def index_handler(request: web.Request) -> web.Response:
    """Serve the dashboard HTML."""
    dashboard = STATIC_DIR / "dashboard.html"
    if not dashboard.exists():
        return web.Response(text="Dashboard not found", status=404)
    return web.FileResponse(dashboard)


def create_app() -> web.Application:
    """Create and configure the aiohttp application."""
    app = web.Application()

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    # Dashboard
    app.router.add_get("/", index_handler)

    # Static files
    if STATIC_DIR.exists():
        app.router.add_static("/static", STATIC_DIR)

    # REST + WebSocket API
    setup_routes(app)

    return app


def run_server(host: str = "0.0.0.0", port: int = 1890) -> None:
    """Start the web server."""
    app = create_app()
    web.run_app(app, host=host, port=port, print=lambda msg: logger.info(msg))
