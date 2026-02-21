"""NanoBot Web UI - Enhanced FastAPI + Single-Page App"""
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets

app = FastAPI(title="NanoBot Web UI")
security = HTTPBasic(auto_error=False)

NANOBOT_DIR = Path(os.environ.get("NANOBOT_DIR", Path.home() / ".nanobot"))
CONFIG_FILE = NANOBOT_DIR / "config.toml"
MEMORY_FILE = NANOBOT_DIR / "memory.md"
SKILLS_DIR = NANOBOT_DIR / "skills"

ADMIN_USER = os.environ.get("WEBUI_USER", "admin")
ADMIN_PASS = os.environ.get("WEBUI_PASS", "nanobot123")

_gateway_process = None
_gateway_lock = threading.Lock()


def verify_auth(credentials: HTTPBasicCredentials = None):
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated",
                            headers={"WWW-Authenticate": "Basic"})
    ok_user = secrets.compare_digest(credentials.username.encode(), ADMIN_USER.encode())
    ok_pass = secrets.compare_digest(credentials.password.encode(), ADMIN_PASS.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(status_code=401, detail="Wrong credentials",
                            headers={"WWW-Authenticate": "Basic"})
    return credentials.username


def read_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(CONFIG_FILE, "rb") as f:
        return tomllib.load(f)


def write_config(data: dict):
    NANOBOT_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    def _write_section(d, prefix=""):
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                _write_section(v, key)
            elif isinstance(v, bool):
                lines.append(f"{key} = {'true' if v else 'false'}")
            elif isinstance(v, (int, float)):
                lines.append(f"{key} = {v}")
            elif isinstance(v, str):
                escaped = v.replace('\\', '\\\\').replace('"', '\\"')
                lines.append(f'{key} = "{escaped}"')
    _write_section(data)
    with open(CONFIG_FILE, "w") as f:
        f.write("\n".join(lines) + "\n")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    credentials = await security(request)
    try:
        verify_auth(credentials)
    except HTTPException:
        return HTMLResponse(
            content="<h2>401 Unauthorized</h2>",
            status_code=401,
            headers={"WWW-Authenticate": "Basic realm=NanoBot"}
        )
    return HTMLResponse(content=get_html())


@app.get("/api/config")
async def api_get_config(request: Request):
    credentials = await security(request)
    verify_auth(credentials)
    cfg = read_config()
    return JSONResponse(cfg)


@app.post("/api/config")
async def api_save_config(request: Request):
    credentials = await security(request)
    verify_auth(credentials)
    data = await request.json()
    write_config(data)
    return {"ok": True}


@app.get("/api/status")
async def api_status(request: Request):
    credentials = await security(request)
    verify_auth(credentials)
    global _gateway_process
    running = _gateway_process is not None and _gateway_process.poll() is None
    return {"running": running, "pid": _gateway_process.pid if running else None}


@app.post("/api/gateway/start")
async def api_start(request: Request):
    credentials = await security(request)
    verify_auth(credentials)
    global _gateway_process
    with _gateway_lock:
        if _gateway_process and _gateway_process.poll() is None:
            return {"ok": True, "msg": "Already running"}
        _gateway_process = subprocess.Popen(
            ["nanobot", "start"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=str(NANOBOT_DIR)
        )
    return {"ok": True, "pid": _gateway_process.pid}


@app.post("/api/gateway/stop")
async def api_stop(request: Request):
    credentials = await security(request)
    verify_auth(credentials)
    global _gateway_process
    with _gateway_lock:
        if _gateway_process and _gateway_process.poll() is None:
            _gateway_process.terminate()
            _gateway_process.wait(timeout=10)
    return {"ok": True}


@app.post("/api/gateway/restart")
async def api_restart(request: Request):
    credentials = await security(request)
    verify_auth(credentials)
    await api_stop(request)
    return await api_start(request)


@app.get("/api/logs")
async def api_logs(request: Request):
    credentials = await security(request)
    verify_auth(credentials)
    global _gateway_process
    if not _gateway_process:
        return {"lines": []}
    try:
        import fcntl
        fd = _gateway_process.stdout.fileno()
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        raw = _gateway_process.stdout.read(8192) or b""
        lines = raw.decode(errors="replace").splitlines()[-200:]
        return {"lines": lines}
    except Exception as e:
        return {"lines": [f"Error reading logs: {e}"]}


@app.get("/api/skills")
async def api_list_skills(request: Request):
    credentials = await security(request)
    verify_auth(credentials)
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    skills = []
    for f in sorted(SKILLS_DIR.glob("*.md")):
        skills.append({"name": f.stem, "size": f.stat().st_size})
    return {"skills": skills}


@app.get("/api/skills/{name}")
async def api_get_skill(name: str, request: Request):
    credentials = await security(request)
    verify_auth(credentials)
    f = SKILLS_DIR / f"{name}.md"
    if not f.exists():
        raise HTTPException(404, "Skill not found")
    return {"name": name, "content": f.read_text()}


@app.post("/api/skills/{name}")
async def api_save_skill(name: str, request: Request):
    credentials = await security(request)
    verify_auth(credentials)
    data = await request.json()
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    (SKILLS_DIR / f"{name}.md").write_text(data.get("content", ""))
    return {"ok": True}


@app.delete("/api/skills/{name}")
async def api_delete_skill(name: str, request: Request):
    credentials = await security(request)
    verify_auth(credentials)
    f = SKILLS_DIR / f"{name}.md"
    if f.exists():
        f.unlink()
    return {"ok": True}


@app.get("/api/memory")
async def api_get_memory(request: Request):
    credentials = await security(request)
    verify_auth(credentials)
    content = MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""
    return {"content": content}


@app.post("/api/memory")
async def api_save_memory(request: Request):
    credentials = await security(request)
    verify_auth(credentials)
    data = await request.json()
    NANOBOT_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(data.get("content", ""))
    return {"ok": True}


def get_html() -> str:
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NanoBot Dashboard</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f0f13;color:#e0e0e0;min-height:100vh}
  header{background:linear-gradient(135deg,#1a1a2e,#16213e);padding:18px 32px;display:flex;align-items:center;gap:14px;border-bottom:1px solid #2a2a4a;box-shadow:0 2px 20px rgba(0,0,0,0.5)}
  header h1{font-size:1.5rem;font-weight:700;color:#fff}
  header span{font-size:0.85rem;color:#888;margin-left:auto}
  .badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:0.75rem;font-weight:600}
  .badge.on{background:#0d3d1f;color:#4ade80;border:1px solid #4ade80}
  .badge.off{background:#3d0d0d;color:#f87171;border:1px solid #f87171}
  .main{display:flex;min-height:calc(100vh - 65px)}
  .sidebar{width:200px;background:#13131f;border-right:1px solid #2a2a4a;padding:16px 0;flex-shrink:0}
  .sidebar button{display:block;width:100%;text-align:left;padding:12px 20px;background:none;border:none;color:#aaa;cursor:pointer;font-size:0.9rem;transition:all 0.2s;border-left:3px solid transparent}
  .sidebar button:hover{background:#1e1e35;color:#fff}
  .sidebar button.active{background:#1e1e35;color:#7c6cff;border-left-color:#7c6cff;font-weight:600}
  .content{flex:1;padding:28px;overflow-y:auto;max-height:calc(100vh - 65px)}
  .tab-panel{display:none}.tab-panel.active{display:block}
  .card{background:#1a1a2e;border:1px solid #2a2a4a;border-radius:12px;padding:22px;margin-bottom:20px}
  .card h3{font-size:1rem;font-weight:600;color:#c0b8ff;margin-bottom:16px;display:flex;align-items:center;gap:8px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
  .provider-card{background:#13131f;border:1px solid #2a2a4a;border-radius:10px;padding:16px;cursor:pointer;transition:all 0.2s}
  .provider-card:hover{border-color:#7c6cff;background:#1a1a2e}
  .provider-card.configured{border-color:#4ade80}
  .provider-card h4{font-size:0.95rem;font-weight:600;margin-bottom:4px}
  .provider-card p{font-size:0.78rem;color:#888}
  .channel-card{background:#13131f;border:1px solid #2a2a4a;border-radius:10px;padding:16px;cursor:pointer;transition:all 0.2s}
  .channel-card:hover{border-color:#7c6cff;background:#1a1a2e}
  .channel-card.configured{border-color:#4ade80}
  .channel-card h4{font-size:0.95rem;font-weight:600;margin-bottom:4px}
  .channel-card p{font-size:0.78rem;color:#888}
  .form-group{margin-bottom:14px}
  .form-group label{display:block;font-size:0.82rem;color:#aaa;margin-bottom:5px;font-weight:500}
  .form-group input,.form-group select,.form-group textarea{width:100%;padding:9px 12px;background:#0f0f18;border:1px solid #3a3a5a;border-radius:8px;color:#e0e0e0;font-size:0.88rem;outline:none;transition:border-color 0.2s}
  .form-group input:focus,.form-group select:focus,.form-group textarea:focus{border-color:#7c6cff}
  .form-group textarea{min-height:120px;resize:vertical;font-family:monospace}
  .btn{padding:9px 20px;border-radius:8px;border:none;cursor:pointer;font-size:0.88rem;font-weight:600;transition:all 0.2s}
  .btn-primary{background:#7c6cff;color:#fff}.btn-primary:hover{background:#6a5aed}
  .btn-success{background:#166534;color:#4ade80;border:1px solid #4ade80}.btn-success:hover{background:#15803d}
  .btn-danger{background:#7f1d1d;color:#f87171;border:1px solid #f87171}.btn-danger:hover{background:#991b1b}
  .btn-secondary{background:#2a2a4a;color:#aaa;border:1px solid #3a3a5a}.btn-secondary:hover{background:#3a3a5a;color:#fff}
  .btn-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
  .gateway-status{display:flex;align-items:center;gap:16px;padding:16px;background:#13131f;border-radius:10px;margin-bottom:16px}
  .dot{width:12px;height:12px;border-radius:50%;background:#f87171;flex-shrink:0}
  .dot.on{background:#4ade80;box-shadow:0 0 8px #4ade80}
  .skill-item{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:#13131f;border:1px solid #2a2a4a;border-radius:8px;margin-bottom:8px}
  .skill-item span{font-size:0.88rem}
  .log-box{background:#080810;border:1px solid #2a2a4a;border-radius:8px;padding:14px;font-family:monospace;font-size:0.78rem;line-height:1.6;height:420px;overflow-y:auto;color:#a0ffa0}
  .log-toolbar{display:flex;gap:8px;margin-bottom:10px;align-items:center}
  .log-toolbar input{flex:1;padding:7px 12px;background:#0f0f18;border:1px solid #3a3a5a;border-radius:8px;color:#e0e0e0;font-size:0.82rem;outline:none}
  .modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:100;align-items:center;justify-content:center}
  .modal-overlay.open{display:flex}
  .modal{background:#1a1a2e;border:1px solid #2a2a4a;border-radius:14px;padding:28px;width:min(520px,95vw);max-height:85vh;overflow-y:auto}
  .modal h3{margin-bottom:18px;color:#c0b8ff}
  input[type=checkbox]{width:16px;height:16px;accent-color:#7c6cff}
  .toggle-row{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid #2a2a4a}
  .toggle-row:last-child{border-bottom:none}
  .mcp-item{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:#13131f;border:1px solid #2a2a4a;border-radius:8px;margin-bottom:8px}
  .section-title{font-size:0.75rem;text-transform:uppercase;letter-spacing:0.08em;color:#666;margin-bottom:12px;margin-top:8px}
</style>
</head>
<body>
<header>
  <svg width="32" height="32" viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="16" fill="#7c6cff" opacity="0.2"/><circle cx="16" cy="16" r="8" fill="#7c6cff"/></svg>
  <h1>NanoBot</h1>
  <span id="hdr-status" class="badge off">Offline</span>
</header>
<div class="main">
  <nav class="sidebar">
    <button class="active" onclick="nav('status',this)">&#9881; Status</button>
    <button onclick="nav('providers',this)">&#128273; Providers</button>
    <button onclick="nav('channels',this)">&#128242; Channels</button>
    <button onclick="nav('skills',this)">&#128736; Skills</button>
    <button onclick="nav('memory',this)">&#128190; Memory</button>
    <button onclick="nav('mcp',this)">&#128279; MCP Servers</button>
    <button onclick="nav('logs',this)">&#128196; Logs</button>
  </nav>
  <div class="content">

    <!-- STATUS -->
    <div id="panel-status" class="tab-panel active">
      <div class="card">
        <h3>&#128268; Gateway Control</h3>
        <div class="gateway-status">
          <div class="dot" id="gw-dot"></div>
          <div>
            <div id="gw-label" style="font-weight:600">Checking...</div>
            <div id="gw-pid" style="font-size:0.78rem;color:#888"></div>
          </div>
        </div>
        <div class="btn-row">
          <button class="btn btn-success" onclick="gwAction('start')">&#9654; Start</button>
          <button class="btn btn-danger" onclick="gwAction('stop')">&#9632; Stop</button>
          <button class="btn btn-secondary" onclick="gwAction('restart')">&#8635; Restart</button>
        </div>
      </div>
      <div class="card">
        <h3>&#8505; About</h3>
        <p style="color:#888;font-size:0.88rem;line-height:1.7">
          NanoBot is a lightweight AI gateway supporting multiple LLM providers and messaging channels.
          Configure your providers and channels, then start the gateway to serve requests.
        </p>
      </div>
    </div>

    <!-- PROVIDERS -->
    <div id="panel-providers" class="tab-panel">
      <div class="card">
        <h3>&#128273; LLM Providers</h3>
        <p style="color:#888;font-size:0.82rem;margin-bottom:16px">Click a provider to configure it. Green border = configured.</p>
        <div class="grid" id="providers-grid"></div>
      </div>
    </div>

    <!-- CHANNELS -->
    <div id="panel-channels" class="tab-panel">
      <div class="card">
        <h3>&#128242; Messaging Channels</h3>
        <p style="color:#888;font-size:0.82rem;margin-bottom:16px">Click a channel to configure it. Green border = configured.</p>
        <div class="grid" id="channels-grid"></div>
      </div>
    </div>

    <!-- SKILLS -->
    <div id="panel-skills" class="tab-panel">
      <div class="card">
        <h3>&#128736; Skills</h3>
        <div id="skills-list"></div>
        <div class="btn-row">
          <button class="btn btn-primary" onclick="openNewSkill()">+ New Skill</button>
        </div>
      </div>
    </div>

    <!-- MEMORY -->
    <div id="panel-memory" class="tab-panel">
      <div class="card">
        <h3>&#128190; Memory (memory.md)</h3>
        <div class="form-group">
          <textarea id="memory-editor" style="min-height:380px;font-family:monospace"></textarea>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" onclick="saveMemory()">&#128190; Save Memory</button>
        </div>
      </div>
    </div>

    <!-- MCP -->
    <div id="panel-mcp" class="tab-panel">
      <div class="card">
        <h3>&#128279; MCP Servers</h3>
        <div id="mcp-list"></div>
        <div class="btn-row">
          <button class="btn btn-primary" onclick="openAddMcp()">+ Add Server</button>
        </div>
      </div>
    </div>

    <!-- LOGS -->
    <div id="panel-logs" class="tab-panel">
      <div class="card">
        <h3>&#128196; Gateway Logs</h3>
        <div class="log-toolbar">
          <input id="log-filter" placeholder="Filter logs..." oninput="filterLogs()">
          <button class="btn btn-secondary" onclick="loadLogs()">&#8635; Refresh</button>
          <button class="btn btn-danger" onclick="clearLogs()">&#128465; Clear</button>
          <label style="display:flex;align-items:center;gap:6px;font-size:0.82rem;color:#aaa;cursor:pointer">
            <input type="checkbox" id="auto-refresh" onchange="toggleAutoRefresh()"> Auto
          </label>
        </div>
        <div class="log-box" id="log-box"></div>
      </div>
    </div>

  </div>
</div>

<!-- PROVIDER MODAL -->
<div class="modal-overlay" id="provider-modal">
  <div class="modal">
    <h3 id="prov-modal-title">Configure Provider</h3>
    <div id="prov-modal-body"></div>
    <div class="btn-row">
      <button class="btn btn-primary" onclick="saveProvider()">&#128190; Save</button>
      <button class="btn btn-secondary" onclick="closeModal('provider-modal')">Cancel</button>
    </div>
  </div>
</div>

<!-- CHANNEL MODAL -->
<div class="modal-overlay" id="channel-modal">
  <div class="modal">
    <h3 id="chan-modal-title">Configure Channel</h3>
    <div id="chan-modal-body"></div>
    <div class="btn-row">
      <button class="btn btn-primary" onclick="saveChannel()">&#128190; Save</button>
      <button class="btn btn-secondary" onclick="closeModal('channel-modal')">Cancel</button>
    </div>
  </div>
</div>

<!-- SKILL MODAL -->
<div class="modal-overlay" id="skill-modal">
  <div class="modal">
    <h3 id="skill-modal-title">Skill</h3>
    <div class="form-group">
      <label>Name</label>
      <input id="skill-name" placeholder="my-skill">
    </div>
    <div class="form-group">
      <label>Content (Markdown)</label>
      <textarea id="skill-content" style="min-height:260px;font-family:monospace"></textarea>
    </div>
    <div class="btn-row">
      <button class="btn btn-primary" onclick="saveSkill()">&#128190; Save</button>
      <button class="btn btn-danger" id="skill-delete-btn" onclick="deleteSkill()" style="display:none">&#128465; Delete</button>
      <button class="btn btn-secondary" onclick="closeModal('skill-modal')">Cancel</button>
    </div>
  </div>
</div>

<!-- MCP MODAL -->
<div class="modal-overlay" id="mcp-modal">
  <div class="modal">
    <h3>Add MCP Server</h3>
    <div class="form-group"><label>Name</label><input id="mcp-name" placeholder="my-server"></div>
    <div class="form-group"><label>Type</label>
      <select id="mcp-type" onchange="updateMcpForm()">
        <option value="sse">SSE (HTTP)</option>
        <option value="stdio">stdio (local process)</option>
      </select>
    </div>
    <div id="mcp-sse-fields">
      <div class="form-group"><label>URL</label><input id="mcp-url" placeholder="http://localhost:8080/sse"></div>
    </div>
    <div id="mcp-stdio-fields" style="display:none">
      <div class="form-group"><label>Command</label><input id="mcp-cmd" placeholder="python"></div>
      <div class="form-group"><label>Args (space-separated)</label><input id="mcp-args" placeholder="-m myserver"></div>
      <div class="form-group"><label>Working Directory</label><input id="mcp-cwd" placeholder="/path/to/dir"></div>
    </div>
    <div class="btn-row">
      <button class="btn btn-primary" onclick="saveMcp()">Add</button>
      <button class="btn btn-secondary" onclick="closeModal('mcp-modal')">Cancel</button>
    </div>
  </div>
</div>

<script>
const PROVIDERS = [
  {id:'openrouter', name:'OpenRouter', desc:'Access 100+ models via one API', fields:[
    {k:'api_key',l:'API Key',t:'password',ph:'sk-or-...'},
    {k:'model',l:'Model',t:'text',ph:'openai/gpt-4o'},
  ]},
  {id:'openai', name:'OpenAI', desc:'GPT-4o, GPT-4, GPT-3.5 and more', fields:[
    {k:'api_key',l:'API Key',t:'password',ph:'sk-...'},
    {k:'model',l:'Model',t:'text',ph:'gpt-4o'},
    {k:'base_url',l:'Base URL (optional)',t:'text',ph:'https://api.openai.com/v1'},
  ]},
  {id:'anthropic', name:'Anthropic', desc:'Claude 3.5, Claude 3 Opus/Sonnet', fields:[
    {k:'api_key',l:'API Key',t:'password',ph:'sk-ant-...'},
    {k:'model',l:'Model',t:'text',ph:'claude-3-5-sonnet-20241022'},
  ]},
  {id:'google', name:'Google Gemini', desc:'Gemini 1.5 Pro, Flash and more', fields:[
    {k:'api_key',l:'API Key',t:'password',ph:'AIza...'},
    {k:'model',l:'Model',t:'text',ph:'gemini-1.5-pro'},
  ]},
  {id:'deepseek', name:'DeepSeek', desc:'DeepSeek-V3, DeepSeek-R1', fields:[
    {k:'api_key',l:'API Key',t:'password',ph:'sk-...'},
    {k:'model',l:'Model',t:'text',ph:'deepseek-chat'},
  ]},
  {id:'groq', name:'Groq', desc:'Ultra-fast inference with Llama, Mixtral', fields:[
    {k:'api_key',l:'API Key',t:'password',ph:'gsk_...'},
    {k:'model',l:'Model',t:'text',ph:'llama-3.1-70b-versatile'},
  ]},
  {id:'moonshot', name:'Moonshot', desc:'Kimi AI long-context models', fields:[
    {k:'api_key',l:'API Key',t:'password',ph:'sk-...'},
    {k:'model',l:'Model',t:'text',ph:'moonshot-v1-8k'},
  ]},
  {id:'zhipu', name:'Zhipu AI', desc:'GLM-4 and other Zhipu models', fields:[
    {k:'api_key',l:'API Key',t:'password',ph:'your-key'},
    {k:'model',l:'Model',t:'text',ph:'glm-4'},
  ]},
  {id:'dashscope', name:'DashScope', desc:'Alibaba Qwen models', fields:[
    {k:'api_key',l:'API Key',t:'password',ph:'sk-...'},
    {k:'model',l:'Model',t:'text',ph:'qwen-max'},
  ]},
  {id:'aihubmix', name:'AiHubMix', desc:'OpenAI-compatible hub', fields:[
    {k:'api_key',l:'API Key',t:'password',ph:'your-key'},
    {k:'model',l:'Model',t:'text',ph:'gpt-4o'},
    {k:'base_url',l:'Base URL',t:'text',ph:'https://aihubmix.com/v1'},
  ]},
  {id:'nvidia', name:'NVIDIA NIM', desc:'NVIDIA-hosted inference endpoints', fields:[
    {k:'api_key',l:'API Key',t:'password',ph:'nvapi-...'},
    {k:'model',l:'Model',t:'text',ph:'meta/llama-3.1-70b-instruct'},
    {k:'base_url',l:'Base URL',t:'text',ph:'https://integrate.api.nvidia.com/v1'},
  ]},
  {id:'vllm', name:'vLLM', desc:'Self-hosted vLLM server', fields:[
    {k:'base_url',l:'Base URL',t:'text',ph:'http://localhost:8000/v1'},
    {k:'model',l:'Model',t:'text',ph:'meta-llama/Meta-Llama-3-8B-Instruct'},
    {k:'api_key',l:'API Key (optional)',t:'password',ph:'optional'},
  ]},
];

const CHANNELS = [
  {id:'telegram', name:'Telegram', desc:'Bot via Telegram Bot API', fields:[
    {k:'token',l:'Bot Token',t:'password',ph:'1234567890:AAF...'},
    {k:'webhook_url',l:'Webhook URL (optional)',t:'text',ph:'https://yourbot.com/webhook'},
  ]},
  {id:'discord', name:'Discord', desc:'Bot via Discord Gateway', fields:[
    {k:'token',l:'Bot Token',t:'password',ph:'MTk4...'},
    {k:'application_id',l:'Application ID',t:'text',ph:'1234567890'},
  ]},
  {id:'slack', name:'Slack', desc:'App via Slack Events API', fields:[
    {k:'bot_token',l:'Bot Token',t:'password',ph:'xoxb-...'},
    {k:'signing_secret',l:'Signing Secret',t:'password',ph:'abc123...'},
    {k:'app_token',l:'App-Level Token (Socket Mode)',t:'password',ph:'xapp-...'},
  ]},
  {id:'whatsapp', name:'WhatsApp', desc:'Via WhatsApp Cloud API (Meta)', fields:[
    {k:'access_token',l:'Access Token',t:'password',ph:'EAABs...'},
    {k:'phone_number_id',l:'Phone Number ID',t:'text',ph:'1234567890'},
    {k:'verify_token',l:'Webhook Verify Token',t:'text',ph:'myverifytoken'},
  ]},
  {id:'lark', name:'Lark / Feishu', desc:'Lark Bot via Event API', fields:[
    {k:'app_id',l:'App ID',t:'text',ph:'cli_...'},
    {k:'app_secret',l:'App Secret',t:'password',ph:'your-secret'},
    {k:'verification_token',l:'Verification Token',t:'password',ph:'your-token'},
  ]},
  {id:'dingtalk', name:'DingTalk', desc:'DingTalk outbound robot', fields:[
    {k:'access_token',l:'Access Token',t:'password',ph:'your-token'},
    {k:'secret',l:'Signing Secret',t:'password',ph:'SEC...'},
  ]},
  {id:'wecom', name:'WeCom (WeChat Work)', desc:'WeCom corporate WeChat', fields:[
    {k:'corp_id',l:'Corp ID',t:'text',ph:'wx...'},
    {k:'agent_id',l:'Agent ID',t:'text',ph:'1000001'},
    {k:'secret',l:'Secret',t:'password',ph:'your-secret'},
  ]},
  {id:'matrix', name:'Matrix', desc:'Matrix protocol via matrix-bot-sdk', fields:[
    {k:'homeserver',l:'Homeserver URL',t:'text',ph:'https://matrix.org'},
    {k:'access_token',l:'Access Token',t:'password',ph:'syt_...'},
    {k:'user_id',l:'User ID',t:'text',ph:'@mybot:matrix.org'},
  ]},
  {id:'irc', name:'IRC', desc:'IRC bot via direct TCP connection', fields:[
    {k:'host',l:'Server Host',t:'text',ph:'irc.libera.chat'},
    {k:'port',l:'Port',t:'text',ph:'6697'},
    {k:'nick',l:'Nickname',t:'text',ph:'mynanobot'},
    {k:'channel',l:'Channel',t:'text',ph:'#mychannel'},
    {k:'password',l:'NickServ Password (optional)',t:'password',ph:'optional'},
  ]},
];

let cfg = {};
let mcpServers = JSON.parse(localStorage.getItem('mcp_servers')||'[]');
let allLogLines = [];
let autoRefreshTimer = null;
let currentProvider = null;
let currentChannel = null;
let editingSkill = null;

async function api(path, opts={}) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

function nav(id, btn) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.sidebar button').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-'+id).classList.add('active');
  btn.classList.add('active');
  if (id==='logs') loadLogs();
  if (id==='skills') loadSkills();
  if (id==='memory') loadMemory();
  if (id==='providers') renderProviders();
  if (id==='channels') renderChannels();
  if (id==='mcp') renderMcp();
}

function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}

// ---- GATEWAY ----
async function loadStatus() {
  try {
    const s = await api('/api/status');
    const dot = document.getElementById('gw-dot');
    const lbl = document.getElementById('gw-label');
    const pid = document.getElementById('gw-pid');
    const hdr = document.getElementById('hdr-status');
    if (s.running) {
      dot.className='dot on'; lbl.textContent='Running';
      pid.textContent='PID: '+s.pid;
      hdr.className='badge on'; hdr.textContent='Online';
    } else {
      dot.className='dot'; lbl.textContent='Stopped';
      pid.textContent='';
      hdr.className='badge off'; hdr.textContent='Offline';
    }
  } catch(e) { console.error(e); }
}

async function gwAction(action) {
  try {
    await api('/api/gateway/'+action, {method:'POST'});
    setTimeout(loadStatus, 800);
  } catch(e) { alert('Error: '+e.message); }
}

// ---- PROVIDERS ----
async function loadConfig() {
  cfg = await api('/api/config');
  renderProviders();
  renderChannels();
}

function renderProviders() {
  const grid = document.getElementById('providers-grid');
  if (!grid) return;
  grid.innerHTML = PROVIDERS.map(p => {
    const section = cfg[p.id] || {};
    const configured = Object.keys(section).some(k => section[k]);
    return `<div class="provider-card${configured?' configured':''}" onclick="openProvider('${p.id}')">
      <h4>${p.name}</h4>
      <p>${p.desc}</p>
      ${configured ? '<p style="color:#4ade80;font-size:0.75rem;margin-top:6px">&#10003; Configured</p>' : ''}
    </div>`;
  }).join('');
}

function openProvider(id) {
  currentProvider = PROVIDERS.find(p=>p.id===id);
  document.getElementById('prov-modal-title').textContent = 'Configure '+currentProvider.name;
  const section = cfg[id] || {};
  document.getElementById('prov-modal-body').innerHTML = currentProvider.fields.map(f =>
    `<div class="form-group">
      <label>${f.l}</label>
      <input type="${f.t}" id="pf-${f.k}" placeholder="${f.ph}" value="${section[f.k]||''}">
    </div>`
  ).join('') +
  `<div class="toggle-row" style="margin-top:12px">
    <span style="font-size:0.88rem">Set as default provider</span>
    <input type="checkbox" id="pf-default" ${cfg.provider===id?'checked':''}>
  </div>`;
  document.getElementById('provider-modal').classList.add('open');
}

async function saveProvider() {
  if (!currentProvider) return;
  const section = {};
  currentProvider.fields.forEach(f => {
    const v = document.getElementById('pf-'+f.k).value.trim();
    if (v) section[f.k] = v;
  });
  cfg[currentProvider.id] = section;
  if (document.getElementById('pf-default').checked) {
    cfg.provider = currentProvider.id;
  }
  await api('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(cfg)});
  closeModal('provider-modal');
  renderProviders();
}

// ---- CHANNELS ----
function renderChannels() {
  const grid = document.getElementById('channels-grid');
  if (!grid) return;
  grid.innerHTML = CHANNELS.map(c => {
    const section = cfg[c.id] || {};
    const configured = Object.keys(section).some(k => section[k]);
    return `<div class="channel-card${configured?' configured':''}" onclick="openChannel('${c.id}')">
      <h4>${c.name}</h4>
      <p>${c.desc}</p>
      ${configured ? '<p style="color:#4ade80;font-size:0.75rem;margin-top:6px">&#10003; Configured</p>' : ''}
    </div>`;
  }).join('');
}

function openChannel(id) {
  currentChannel = CHANNELS.find(c=>c.id===id);
  document.getElementById('chan-modal-title').textContent = 'Configure '+currentChannel.name;
  const section = cfg[id] || {};
  document.getElementById('chan-modal-body').innerHTML = currentChannel.fields.map(f =>
    `<div class="form-group">
      <label>${f.l}</label>
      <input type="${f.t}" id="cf-${f.k}" placeholder="${f.ph}" value="${section[f.k]||''}">
    </div>`
  ).join('') +
  `<div class="toggle-row" style="margin-top:12px">
    <span style="font-size:0.88rem">Enable this channel</span>
    <input type="checkbox" id="cf-enabled" ${(cfg[id]||{}).enabled!==false?'checked':''}>
  </div>`;
  document.getElementById('channel-modal').classList.add('open');
}

async function saveChannel() {
  if (!currentChannel) return;
  const section = {};
  currentChannel.fields.forEach(f => {
    const v = document.getElementById('cf-'+f.k).value.trim();
    if (v) section[f.k] = v;
  });
  section.enabled = document.getElementById('cf-enabled').checked;
  cfg[currentChannel.id] = section;
  await api('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(cfg)});
  closeModal('channel-modal');
  renderChannels();
}

// ---- SKILLS ----
async function loadSkills() {
  const data = await api('/api/skills');
  const list = document.getElementById('skills-list');
  if (!data.skills.length) {
    list.innerHTML = '<p style="color:#888;font-size:0.88rem">No skills yet. Create one below.</p>';
    return;
  }
  list.innerHTML = data.skills.map(s =>
    `<div class="skill-item">
      <span>&#128736; ${s.name}.md <span style="color:#888;font-size:0.75rem">(${s.size}b)</span></span>
      <button class="btn btn-secondary" style="padding:5px 12px;font-size:0.78rem" onclick="editSkill('${s.name}')">Edit</button>
    </div>`
  ).join('');
}

function openNewSkill() {
  editingSkill = null;
  document.getElementById('skill-modal-title').textContent = 'New Skill';
  document.getElementById('skill-name').value = '';
  document.getElementById('skill-name').disabled = false;
  document.getElementById('skill-content').value = '';
  document.getElementById('skill-delete-btn').style.display = 'none';
  document.getElementById('skill-modal').classList.add('open');
}

async function editSkill(name) {
  const data = await api('/api/skills/'+name);
  editingSkill = name;
  document.getElementById('skill-modal-title').textContent = 'Edit: '+name;
  document.getElementById('skill-name').value = name;
  document.getElementById('skill-name').disabled = true;
  document.getElementById('skill-content').value = data.content;
  document.getElementById('skill-delete-btn').style.display = 'inline-block';
  document.getElementById('skill-modal').classList.add('open');
}

async function saveSkill() {
  const name = (editingSkill || document.getElementById('skill-name').value).trim();
  if (!name) { alert('Enter a skill name'); return; }
  const content = document.getElementById('skill-content').value;
  await api('/api/skills/'+name, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({content})});
  closeModal('skill-modal');
  loadSkills();
}

async function deleteSkill() {
  if (!editingSkill) return;
  if (!confirm('Delete skill "'+editingSkill+'"?')) return;
  await api('/api/skills/'+editingSkill, {method:'DELETE'});
  closeModal('skill-modal');
  loadSkills();
}

// ---- MEMORY ----
async function loadMemory() {
  const data = await api('/api/memory');
  document.getElementById('memory-editor').value = data.content;
}

async function saveMemory() {
  const content = document.getElementById('memory-editor').value;
  await api('/api/memory', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({content})});
  alert('Memory saved!');
}

// ---- MCP ----
function renderMcp() {
  const list = document.getElementById('mcp-list');
  if (!mcpServers.length) {
    list.innerHTML = '<p style="color:#888;font-size:0.88rem">No MCP servers configured.</p>';
    return;
  }
  list.innerHTML = mcpServers.map((s,i) =>
    `<div class="mcp-item">
      <div>
        <div style="font-weight:600;font-size:0.88rem">${s.name}</div>
        <div style="font-size:0.75rem;color:#888">${s.type==='sse'?s.url:s.cmd+' '+s.args}</div>
      </div>
      <button class="btn btn-danger" style="padding:4px 10px;font-size:0.78rem" onclick="deleteMcp(${i})">Remove</button>
    </div>`
  ).join('');
}

function openAddMcp() {
  document.getElementById('mcp-name').value='';
  document.getElementById('mcp-url').value='';
  document.getElementById('mcp-cmd').value='';
  document.getElementById('mcp-args').value='';
  document.getElementById('mcp-cwd').value='';
  document.getElementById('mcp-type').value='sse';
  updateMcpForm();
  document.getElementById('mcp-modal').classList.add('open');
}

function updateMcpForm() {
  const t = document.getElementById('mcp-type').value;
  document.getElementById('mcp-sse-fields').style.display = t==='sse'?'block':'none';
  document.getElementById('mcp-stdio-fields').style.display = t==='stdio'?'block':'none';
}

function saveMcp() {
  const name = document.getElementById('mcp-name').value.trim();
  const type = document.getElementById('mcp-type').value;
  if (!name) { alert('Enter a server name'); return; }
  const entry = {name, type};
  if (type==='sse') {
    entry.url = document.getElementById('mcp-url').value.trim();
  } else {
    entry.cmd = document.getElementById('mcp-cmd').value.trim();
    entry.args = document.getElementById('mcp-args').value.trim();
    entry.cwd = document.getElementById('mcp-cwd').value.trim();
  }
  mcpServers.push(entry);
  localStorage.setItem('mcp_servers', JSON.stringify(mcpServers));
  closeModal('mcp-modal');
  renderMcp();
}

function deleteMcp(i) {
  if (!confirm('Remove this MCP server?')) return;
  mcpServers.splice(i,1);
  localStorage.setItem('mcp_servers', JSON.stringify(mcpServers));
  renderMcp();
}

// ---- LOGS ----
async function loadLogs() {
  try {
    const data = await api('/api/logs');
    allLogLines = data.lines || [];
    filterLogs();
  } catch(e) {}
}

function filterLogs() {
  const q = document.getElementById('log-filter').value.toLowerCase();
  const filtered = q ? allLogLines.filter(l=>l.toLowerCase().includes(q)) : allLogLines;
  const box = document.getElementById('log-box');
  box.innerHTML = filtered.map(l => `<div>${escHtml(l)}</div>`).join('') || '<div style="color:#555">No logs yet...</div>';
  box.scrollTop = box.scrollHeight;
}

function clearLogs() { allLogLines=[]; filterLogs(); }

function escHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function toggleAutoRefresh() {
  if (document.getElementById('auto-refresh').checked) {
    autoRefreshTimer = setInterval(loadLogs, 3000);
  } else {
    clearInterval(autoRefreshTimer);
  }
}

// ---- INIT ----
loadStatus();
loadConfig();
setInterval(loadStatus, 5000);

document.querySelectorAll('.modal-overlay').forEach(m => {
  m.addEventListener('click', e => { if (e.target===m) m.classList.remove('open'); });
});
</script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
