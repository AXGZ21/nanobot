import os
import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

app = FastAPI(title="NanoBot Web UI")
security = HTTPBasic(auto_error=False)

CONFIG_DIR = Path.home() / ".nanobot"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = CONFIG_DIR / "gateway.log"

gateway_process: Optional[subprocess.Popen] = None
gateway_lock = threading.Lock()

WEBUI_PASSWORD = os.environ.get("WEBUI_PASSWORD", "")


def check_auth(credentials: Optional[HTTPBasicCredentials] = Depends(security)):
    if not WEBUI_PASSWORD:
        return True
    if credentials is None:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    correct = secrets.compare_digest(credentials.password.encode(), WEBUI_PASSWORD.encode())
    if not correct:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    return True


def read_config() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {
        "providers": {
            "openrouter": {"api_key": "", "api_base": "https://openrouter.ai/api/v1"},
            "openai": {"api_key": "", "api_base": "https://api.openai.com/v1"},
            "anthropic": {"api_key": ""}
        },
        "agents": {"default_model": "openrouter/anthropic/claude-3.5-sonnet"},
        "channels": {
            "telegram": {"enabled": False, "token": ""},
            "discord": {"enabled": False, "token": ""},
            "slack": {"enabled": False, "bot_token": "", "app_token": ""}
        }
    }


def write_config(config: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def is_gateway_running() -> bool:
    global gateway_process
    if gateway_process is None:
        return False
    return gateway_process.poll() is None


def start_gateway():
    global gateway_process
    with gateway_lock:
        if is_gateway_running():
            return
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        log_fd = open(LOG_FILE, "a")
        gateway_process = subprocess.Popen(
            ["python", "-m", "nanobot"],
            stdout=log_fd,
            stderr=log_fd,
            env={**os.environ, "NANOBOT_CONFIG": str(CONFIG_FILE)}
        )


def stop_gateway():
    global gateway_process
    with gateway_lock:
        if gateway_process and gateway_process.poll() is None:
            gateway_process.terminate()
            try:
                gateway_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                gateway_process.kill()
        gateway_process = None


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NanoBot Control Panel</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1117; color: #e0e0e0; min-height: 100vh; }
  .header { background: #1a1d2e; border-bottom: 1px solid #2d3148; padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
  .header h1 { font-size: 1.3rem; font-weight: 600; color: #fff; }
  .header .logo { width: 32px; height: 32px; background: linear-gradient(135deg, #6366f1, #8b5cf6); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 18px; }
  .status-badge { margin-left: auto; padding: 4px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; }
  .status-badge.running { background: #064e3b; color: #34d399; }
  .status-badge.stopped { background: #450a0a; color: #f87171; }
  .container { max-width: 900px; margin: 0 auto; padding: 24px; }
  .card { background: #1a1d2e; border: 1px solid #2d3148; border-radius: 12px; padding: 24px; margin-bottom: 20px; }
  .card h2 { font-size: 1rem; font-weight: 600; color: #a78bfa; margin-bottom: 16px; text-transform: uppercase; letter-spacing: 0.05em; }
  .form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
  .form-group { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
  .form-group label { font-size: 0.8rem; color: #9ca3af; font-weight: 500; }
  .form-group input, .form-group select { background: #0f1117; border: 1px solid #2d3148; border-radius: 8px; padding: 8px 12px; color: #e0e0e0; font-size: 0.875rem; outline: none; transition: border-color 0.2s; }
  .form-group input:focus, .form-group select:focus { border-color: #6366f1; }
  .toggle-row { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
  .toggle { position: relative; width: 40px; height: 22px; }
  .toggle input { opacity: 0; width: 0; height: 0; }
  .slider { position: absolute; cursor: pointer; inset: 0; background: #374151; border-radius: 22px; transition: 0.3s; }
  .slider:before { position: absolute; content: ""; height: 16px; width: 16px; left: 3px; bottom: 3px; background: white; border-radius: 50%; transition: 0.3s; }
  input:checked + .slider { background: #6366f1; }
  input:checked + .slider:before { transform: translateX(18px); }
  .btn { padding: 8px 20px; border-radius: 8px; border: none; cursor: pointer; font-size: 0.875rem; font-weight: 600; transition: all 0.2s; }
  .btn-primary { background: #6366f1; color: white; }
  .btn-primary:hover { background: #4f46e5; }
  .btn-success { background: #059669; color: white; }
  .btn-success:hover { background: #047857; }
  .btn-danger { background: #dc2626; color: white; }
  .btn-danger:hover { background: #b91c1c; }
  .btn-warning { background: #d97706; color: white; }
  .btn-warning:hover { background: #b45309; }
  .controls { display: flex; gap: 10px; flex-wrap: wrap; }
  .logs { background: #0a0c14; border: 1px solid #1e2235; border-radius: 8px; padding: 16px; font-family: 'Courier New', monospace; font-size: 0.78rem; height: 300px; overflow-y: auto; color: #86efac; white-space: pre-wrap; word-break: break-all; }
  .toast { position: fixed; bottom: 24px; right: 24px; padding: 12px 20px; border-radius: 8px; font-size: 0.875rem; font-weight: 500; z-index: 1000; animation: fadeIn 0.3s ease; }
  .toast.success { background: #064e3b; color: #34d399; border: 1px solid #065f46; }
  .toast.error { background: #450a0a; color: #f87171; border: 1px solid #7f1d1d; }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
  .section-title { font-size: 0.75rem; color: #6b7280; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 10px; margin-top: 16px; }
</style>
</head>
<body>
<div class="header">
  <div class="logo">🤖</div>
  <h1>NanoBot Control Panel</h1>
  <span class="status-badge stopped" id="statusBadge">● Stopped</span>
</div>
<div class="container">

  <!-- Gateway Controls -->
  <div class="card">
    <h2>Gateway</h2>
    <div class="controls">
      <button class="btn btn-success" onclick="gatewayAction('start')">▶ Start</button>
      <button class="btn btn-danger" onclick="gatewayAction('stop')">■ Stop</button>
      <button class="btn btn-warning" onclick="gatewayAction('restart')">↺ Restart</button>
      <button class="btn btn-primary" onclick="loadLogs()">↓ Refresh Logs</button>
    </div>
  </div>

  <!-- Configuration -->
  <div class="card">
    <h2>Configuration</h2>

    <div class="section-title">LLM Providers</div>
    <div class="form-row">
      <div class="form-group">
        <label>Default Model</label>
        <input id="default_model" placeholder="openrouter/anthropic/claude-3.5-sonnet">
      </div>
      <div class="form-group">
        <label>OpenRouter API Key</label>
        <input id="openrouter_key" type="password" placeholder="sk-or-...">
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>OpenAI API Key</label>
        <input id="openai_key" type="password" placeholder="sk-...">
      </div>
      <div class="form-group">
        <label>Anthropic API Key</label>
        <input id="anthropic_key" type="password" placeholder="sk-ant-...">
      </div>
    </div>

    <div class="section-title">Channels</div>

    <div class="toggle-row">
      <label class="toggle"><input type="checkbox" id="telegram_enabled" onchange="toggleSection('telegram')"><span class="slider"></span></label>
      <span style="font-size:0.9rem">Telegram</span>
    </div>
    <div id="telegram_section" style="display:none; margin-bottom:12px;">
      <div class="form-group">
        <label>Bot Token</label>
        <input id="telegram_token" type="password" placeholder="123456:ABC...">
      </div>
    </div>

    <div class="toggle-row">
      <label class="toggle"><input type="checkbox" id="discord_enabled" onchange="toggleSection('discord')"><span class="slider"></span></label>
      <span style="font-size:0.9rem">Discord</span>
    </div>
    <div id="discord_section" style="display:none; margin-bottom:12px;">
      <div class="form-group">
        <label>Bot Token</label>
        <input id="discord_token" type="password" placeholder="MTI...">
      </div>
    </div>

    <div class="toggle-row">
      <label class="toggle"><input type="checkbox" id="slack_enabled" onchange="toggleSection('slack')"><span class="slider"></span></label>
      <span style="font-size:0.9rem">Slack</span>
    </div>
    <div id="slack_section" style="display:none; margin-bottom:12px;">
      <div class="form-row">
        <div class="form-group">
          <label>Bot Token</label>
          <input id="slack_bot_token" type="password" placeholder="xoxb-...">
        </div>
        <div class="form-group">
          <label>App Token</label>
          <input id="slack_app_token" type="password" placeholder="xapp-...">
        </div>
      </div>
    </div>

    <div style="margin-top:16px; display:flex; gap:10px;">
      <button class="btn btn-primary" onclick="saveConfig()">💾 Save Config</button>
      <button class="btn btn-warning" onclick="saveAndRestart()">💾 Save & Restart</button>
    </div>
  </div>

  <!-- Logs -->
  <div class="card">
    <h2>Logs</h2>
    <div class="logs" id="logsBox">Loading logs...</div>
  </div>

</div>

<script>
function toggleSection(ch) {
  const el = document.getElementById(ch + '_section');
  const cb = document.getElementById(ch + '_enabled');
  el.style.display = cb.checked ? 'block' : 'none';
}

function showToast(msg, type='success') {
  const t = document.createElement('div');
  t.className = 'toast ' + type;
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

async function loadStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    const badge = document.getElementById('statusBadge');
    if (d.gateway_running) {
      badge.textContent = '● Running';
      badge.className = 'status-badge running';
    } else {
      badge.textContent = '● Stopped';
      badge.className = 'status-badge stopped';
    }
  } catch(e) {}
}

async function loadConfig() {
  try {
    const r = await fetch('/api/config');
    const c = await r.json();
    document.getElementById('default_model').value = c.agents?.default_model || '';
    document.getElementById('openrouter_key').value = c.providers?.openrouter?.api_key || '';
    document.getElementById('openai_key').value = c.providers?.openai?.api_key || '';
    document.getElementById('anthropic_key').value = c.providers?.anthropic?.api_key || '';

    const tg = c.channels?.telegram || {};
    document.getElementById('telegram_enabled').checked = !!tg.enabled;
    document.getElementById('telegram_token').value = tg.token || '';
    toggleSection('telegram');

    const dc = c.channels?.discord || {};
    document.getElementById('discord_enabled').checked = !!dc.enabled;
    document.getElementById('discord_token').value = dc.token || '';
    toggleSection('discord');

    const sl = c.channels?.slack || {};
    document.getElementById('slack_enabled').checked = !!sl.enabled;
    document.getElementById('slack_bot_token').value = sl.bot_token || '';
    document.getElementById('slack_app_token').value = sl.app_token || '';
    toggleSection('slack');
  } catch(e) { showToast('Failed to load config', 'error'); }
}

async function saveConfig() {
  const config = {
    providers: {
      openrouter: { api_key: document.getElementById('openrouter_key').value, api_base: 'https://openrouter.ai/api/v1' },
      openai: { api_key: document.getElementById('openai_key').value, api_base: 'https://api.openai.com/v1' },
      anthropic: { api_key: document.getElementById('anthropic_key').value }
    },
    agents: { default_model: document.getElementById('default_model').value },
    channels: {
      telegram: { enabled: document.getElementById('telegram_enabled').checked, token: document.getElementById('telegram_token').value },
      discord: { enabled: document.getElementById('discord_enabled').checked, token: document.getElementById('discord_token').value },
      slack: { enabled: document.getElementById('slack_enabled').checked, bot_token: document.getElementById('slack_bot_token').value, app_token: document.getElementById('slack_app_token').value }
    }
  };
  try {
    const r = await fetch('/api/config', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(config) });
    if (r.ok) showToast('Config saved!');
    else showToast('Save failed', 'error');
  } catch(e) { showToast('Save failed', 'error'); }
}

async function saveAndRestart() {
  await saveConfig();
  await gatewayAction('restart');
}

async function gatewayAction(action) {
  try {
    const r = await fetch('/api/' + action, { method: 'POST' });
    const d = await r.json();
    showToast(action.charAt(0).toUpperCase() + action.slice(1) + (d.success ? ' successful' : ' failed'), d.success ? 'success' : 'error');
    loadStatus();
    if (action !== 'stop') setTimeout(loadLogs, 2000);
  } catch(e) { showToast('Action failed', 'error'); }
}

async function loadLogs() {
  try {
    const r = await fetch('/api/logs');
    const d = await r.json();
    const box = document.getElementById('logsBox');
    box.textContent = d.lines.join('\\n') || '(no logs yet)';
    box.scrollTop = box.scrollHeight;
  } catch(e) {}
}

// Init
loadConfig();
loadStatus();
loadLogs();
setInterval(loadStatus, 5000);
setInterval(loadLogs, 10000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(check_auth)])
async def index():
    return HTML_PAGE


@app.get("/api/status", dependencies=[Depends(check_auth)])
async def get_status():
    return {"ok": True, "gateway_running": is_gateway_running(), "config_exists": CONFIG_FILE.exists()}


@app.get("/api/config", dependencies=[Depends(check_auth)])
async def get_config():
    return read_config()


@app.post("/api/config", dependencies=[Depends(check_auth)])
async def post_config(request: Request):
    try:
        data = await request.json()
        write_config(data)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/start", dependencies=[Depends(check_auth)])
async def api_start():
    try:
        start_gateway()
        time.sleep(1)
        return {"success": True, "running": is_gateway_running()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/stop", dependencies=[Depends(check_auth)])
async def api_stop():
    try:
        stop_gateway()
        return {"success": True, "running": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/restart", dependencies=[Depends(check_auth)])
async def api_restart():
    try:
        stop_gateway()
        time.sleep(1)
        start_gateway()
        time.sleep(1)
        return {"success": True, "running": is_gateway_running()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs", dependencies=[Depends(check_auth)])
async def get_logs():
    if not LOG_FILE.exists():
        return {"lines": []}
    try:
        text = LOG_FILE.read_text()
        lines = text.splitlines()
        return {"lines": lines[-200:]}
    except Exception:
        return {"lines": []}


@app.on_event("startup")
async def on_startup():
    # Auto-start gateway if config exists and has at least one provider key
    config = read_config()
    providers = config.get("providers", {})
    has_key = any(
        p.get("api_key", "") for p in providers.values() if isinstance(p, dict)
    )
    if has_key and CONFIG_FILE.exists():
        threading.Thread(target=start_gateway, daemon=True).start()