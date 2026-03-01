"""Railway web control plane for nanobot."""

from __future__ import annotations

import os
import secrets
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from nanobot.config.loader import get_config_path, load_config, save_config
from nanobot.config.schema import Config
from nanobot.utils.helpers import get_workspace_path, sync_workspace_templates

app = FastAPI(title="nanobot control plane")
security = HTTPBasic(auto_error=False)

WEBUI_DIR = Path(__file__).resolve().parent
INDEX_HTML = (WEBUI_DIR / "static" / "index.html").read_text(encoding="utf-8")

ADMIN_USER = os.environ.get("WEBUI_USER", "admin")
ADMIN_PASS = os.environ.get("WEBUI_PASS") or os.environ.get("WEBUI_PASSWORD", "nanobot123")

LOG_LINES = deque(maxlen=int(os.environ.get("WEBUI_LOG_LINES", "3000")))
PROC_LOCK = threading.Lock()
GATEWAY_PROC: subprocess.Popen[str] | None = None


def _bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_nested(data: dict[str, Any], path: list[str]) -> Any:
    cursor: Any = data
    for key in path:
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(key)
    return cursor


def _set_nested(data: dict[str, Any], path: list[str], value: Any) -> None:
    cursor: dict[str, Any] = data
    for key in path[:-1]:
        node = cursor.get(key)
        if not isinstance(node, dict):
            node = {}
            cursor[key] = node
        cursor = node
    cursor[path[-1]] = value


def _reader_thread(proc: subprocess.Popen[str]) -> None:
    try:
        if not proc.stdout:
            return
        for line in iter(proc.stdout.readline, ""):
            text = line.rstrip()
            if text:
                LOG_LINES.append(text)
    finally:
        code = proc.poll()
        LOG_LINES.append(f"[gateway exited] code={code}")


def _gateway_running() -> bool:
    return GATEWAY_PROC is not None and GATEWAY_PROC.poll() is None


def _start_gateway() -> dict[str, Any]:
    global GATEWAY_PROC
    with PROC_LOCK:
        if _gateway_running():
            return {"ok": True, "message": "already running", "pid": GATEWAY_PROC.pid}

        cmd = os.environ.get("NANOBOT_GATEWAY_CMD", "nanobot gateway")
        LOG_LINES.append(f"[gateway start] {cmd}")
        GATEWAY_PROC = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            cwd=str(Path.home() / ".nanobot"),
        )
        thread = threading.Thread(target=_reader_thread, args=(GATEWAY_PROC,), daemon=True)
        thread.start()
        return {"ok": True, "pid": GATEWAY_PROC.pid}


def _stop_gateway() -> dict[str, Any]:
    global GATEWAY_PROC
    with PROC_LOCK:
        if not _gateway_running():
            return {"ok": True, "message": "already stopped"}

        assert GATEWAY_PROC is not None
        proc = GATEWAY_PROC
        proc.terminate()
        try:
            proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        GATEWAY_PROC = None
        LOG_LINES.append("[gateway stop] stopped")
        return {"ok": True}


def _bootstrap_config() -> Config:
    cfg_path = get_config_path()
    if cfg_path.exists():
        config_data = load_config(cfg_path).model_dump(by_alias=True)
    else:
        config_data = Config().model_dump(by_alias=True)

    env_map: list[tuple[str, list[str]]] = [
        ("OPENROUTER_API_KEY", ["providers", "openrouter", "apiKey"]),
        ("OPENAI_API_KEY", ["providers", "openai", "apiKey"]),
        ("ANTHROPIC_API_KEY", ["providers", "anthropic", "apiKey"]),
        ("DEEPSEEK_API_KEY", ["providers", "deepseek", "apiKey"]),
        ("GEMINI_API_KEY", ["providers", "gemini", "apiKey"]),
        ("GROQ_API_KEY", ["providers", "groq", "apiKey"]),
        ("MOONSHOT_API_KEY", ["providers", "moonshot", "apiKey"]),
        ("MINIMAX_API_KEY", ["providers", "minimax", "apiKey"]),
        ("AIHUBMIX_API_KEY", ["providers", "aihubmix", "apiKey"]),
        ("VOLCENGINE_API_KEY", ["providers", "volcengine", "apiKey"]),
        ("SILICONFLOW_API_KEY", ["providers", "siliconflow", "apiKey"]),
        ("DASHSCOPE_API_KEY", ["providers", "dashscope", "apiKey"]),
        ("ZHIPU_API_KEY", ["providers", "zhipu", "apiKey"]),
        ("BRAVE_SEARCH_API_KEY", ["tools", "web", "search", "apiKey"]),
        ("DEFAULT_MODEL", ["agents", "defaults", "model"]),
        ("DEFAULT_PROVIDER", ["agents", "defaults", "provider"]),
        ("TELEGRAM_TOKEN", ["channels", "telegram", "token"]),
        ("DISCORD_TOKEN", ["channels", "discord", "token"]),
        ("SLACK_BOT_TOKEN", ["channels", "slack", "botToken"]),
        ("SLACK_APP_TOKEN", ["channels", "slack", "appToken"]),
    ]
    for env_name, path in env_map:
        value = os.environ.get(env_name, "").strip()
        if value and not _get_nested(config_data, path):
            _set_nested(config_data, path, value)

    if os.environ.get("TELEGRAM_TOKEN"):
        _set_nested(config_data, ["channels", "telegram", "enabled"], True)
    if os.environ.get("DISCORD_TOKEN"):
        _set_nested(config_data, ["channels", "discord", "enabled"], True)
    if os.environ.get("SLACK_BOT_TOKEN") and os.environ.get("SLACK_APP_TOKEN"):
        _set_nested(config_data, ["channels", "slack", "enabled"], True)

    if _bool(os.environ.get("RESTRICT_TO_WORKSPACE")):
        _set_nested(config_data, ["tools", "restrictToWorkspace"], True)

    config = Config.model_validate(config_data)
    save_config(config, cfg_path)

    workspace = get_workspace_path(config.agents.defaults.workspace)
    sync_workspace_templates(workspace, silent=True)
    return config


@app.on_event("startup")
def _startup() -> None:
    _bootstrap_config()


async def _require_auth(request: Request) -> None:
    creds: HTTPBasicCredentials | None = await security(request)
    if creds is None:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    ok_user = secrets.compare_digest(creds.username.encode(), ADMIN_USER.encode())
    ok_pass = secrets.compare_digest(creds.password.encode(), ADMIN_PASS.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
async def index(_: None = Depends(_require_auth)) -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


@app.get("/api/meta")
async def meta(_: None = Depends(_require_auth)) -> dict[str, Any]:
    cfg = load_config()
    return {
        "configPath": str(get_config_path()),
        "workspace": str(get_workspace_path(cfg.agents.defaults.workspace)),
        "defaultUser": ADMIN_USER,
    }


@app.get("/api/config")
async def get_config(_: None = Depends(_require_auth)) -> dict[str, Any]:
    return load_config().model_dump(by_alias=True)


@app.post("/api/config")
async def set_config(request: Request, _: None = Depends(_require_auth)) -> dict[str, bool]:
    payload = await request.json()
    config = Config.model_validate(payload)
    save_config(config)
    return {"ok": True}


@app.post("/api/config/reset")
async def reset_config(_: None = Depends(_require_auth)) -> dict[str, bool]:
    save_config(Config())
    _bootstrap_config()
    return {"ok": True}


@app.get("/api/status")
async def status(_: None = Depends(_require_auth)) -> dict[str, Any]:
    running = _gateway_running()
    return {"running": running, "pid": GATEWAY_PROC.pid if running else None}


@app.post("/api/gateway/{action}")
async def gateway(action: str, _: None = Depends(_require_auth)) -> dict[str, Any]:
    if action == "start":
        return _start_gateway()
    if action == "stop":
        return _stop_gateway()
    if action == "restart":
        _stop_gateway()
        return _start_gateway()
    raise HTTPException(status_code=400, detail="invalid action")


@app.get("/api/logs")
async def logs(limit: int = 400, _: None = Depends(_require_auth)) -> dict[str, Any]:
    if limit < 1:
        limit = 1
    if limit > 2000:
        limit = 2000
    return {"lines": list(LOG_LINES)[-limit:]}
