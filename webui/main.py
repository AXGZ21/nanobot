"""NanoBot Web UI - Complete FastAPI + Single-Page App"""
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets
import asyncio

app = FastAPI(title="NanoBot Web UI")
security = HTTPBasic(auto_error=False)

NANOBOT_DIR = Path.home() / ".nanobot"
CONFIG_FILE = NANOBOT_DIR / "config.json"
LOG_FILE = NANOBOT_DIR / "nanobot.log"
SKILLS_DIR = NANOBOT_DIR / "skills"
MEMORY_FILE = NANOBOT_DIR / "memory.md"

gateway_process: Optional[subprocess.Popen] = None
gateway_lock = threading.Lock()

WEBUI_PASSWORD = os.environ.get("WEBUI_PASSWORD", "")


def check_auth(credentials: Optional[HTTPBasicCredentials] = Depends(security)):
    if not WEBUI_PASSWORD:
        return True
    if credentials is None:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    ok = secrets.compare_digest(credentials.password.encode(), WEBUI_PASSWORD.encode())
    if not ok:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    return True


def start_gateway():
    global gateway_process
    with gateway_lock:
        try:
            if gateway_process and gateway_process.poll() is None:
                return
            NANOBOT_DIR.mkdir(parents=True, exist_ok=True)
            log_f = open(LOG_FILE, "a")
            gateway_process = subprocess.Popen(
                ["nanobot", "gateway"],
                stdout=log_f,
                stderr=subprocess.STDOUT,
                cwd=str(NANOBOT_DIR),
            )
        except Exception as e:
            print(f"Failed to start gateway: {e}")


def is_gateway_running() -> bool:
    if gateway_process is None:
        return False
    return gateway_process.poll() is None


def read_config() -> dict:
    NANOBOT_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def write_config(data: dict):
    NANOBOT_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


@app.on_event("startup")
async def startup_event():
    start_gateway()


# ── API endpoints ──────────────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status(_=Depends(check_auth)):
    return {"ok": True, "gateway_running": is_gateway_running(), "config_exists": CONFIG_FILE.exists()}


@app.get("/api/config")
async def get_config(_=Depends(check_auth)):
    return read_config()


@app.post("/api/config")
async def save_config(request: Request, _=Depends(check_auth)):
    try:
        data = await request.json()
        write_config(data)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/restart")
async def restart_gateway(_=Depends(check_auth)):
    global gateway_process
    with gateway_lock:
        try:
            if gateway_process and gateway_process.poll() is None:
                gateway_process.terminate()
                try:
                    gateway_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    gateway_process.kill()
            await asyncio.sleep(1)
            start_gateway()
            return {"success": True, "running": is_gateway_running()}
        except Exception as e:
            return {"success": False, "error": str(e)}


@app.get("/api/logs")
async def get_logs(lines: int = 200, _=Depends(check_auth)):
    if not LOG_FILE.exists():
        return {"lines": []}
    try:
        with open(LOG_FILE, "r", errors="replace") as f:
            all_lines = f.readlines()
        return {"lines": all_lines[-lines:]}
    except Exception as e:
        return {"error": str(e), "lines": []}


@app.post("/api/logs/clear")
async def clear_logs(_=Depends(check_auth)):
    try:
        LOG_FILE.write_text("")
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/skills")
async def list_skills(_=Depends(check_auth)):
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    skills = []
    for f in SKILLS_DIR.glob("*.md"):
        skills.append({"name": f.stem, "filename": f.name, "size": f.stat().st_size})
    return {"skills": skills}


@app.get("/api/skills/{name}")
async def get_skill(name: str, _=Depends(check_auth)):
    f = SKILLS_DIR / f"{name}.md"
    if not f.exists():
        raise HTTPException(404, "Skill not found")
    return {"name": name, "content": f.read_text()}


@app.post("/api/skills/{name}")
async def save_skill(name: str, request: Request, _=Depends(check_auth)):
    try:
        body = await request.json()
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        (SKILLS_DIR / f"{name}.md").write_text(body.get("content", ""))
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.delete("/api/skills/{name}")
async def delete_skill(name: str, _=Depends(check_auth)):
    f = SKILLS_DIR / f"{name}.md"
    if f.exists():
        f.unlink()
    return {"success": True}


@app.get("/api/memory")
async def get_memory(_=Depends(check_auth)):
    if not MEMORY_FILE.exists():
        return {"content": ""}
    return {"content": MEMORY_FILE.read_text()}


@app.post("/api/memory")
async def save_memory(request: Request, _=Depends(check_auth)):
    try:
        body = await request.json()
        NANOBOT_DIR.mkdir(parents=True, exist_ok=True)
        MEMORY_FILE.write_text(body.get("content", ""))
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── HTML SPA ───────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>NanoBot Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1117;color:#e2e8f0;min-height:100vh}
header{background:#1a1d2e;border-bottom:1px solid #2d3748;padding:14px 24px;display:flex;align-items:center;gap:16px}
header h1{font-size:1.25rem;font-weight:700;color:#7c3aed}
#status-badge{padding:4px 12px;border-radius:999px;font-size:.75rem;font-weight:600}
.running{background:#065f46;color:#6ee7b7}.stopped{background:#7f1d1d;color:#fca5a5}
#save-btn{margin-left:auto;background:#7c3aed;color:#fff;border:none;padding:8px 20px;border-radius:8px;cursor:pointer;font-weight:600}
#save-btn:hover{background:#6d28d9}
#restart-btn{background:#1e3a5f;color:#93c5fd;border:none;padding:8px 16px;border-radius:8px;cursor:pointer;font-weight:600}
#restart-btn:hover{background:#1e40af}
nav{display:flex;gap:4px;padding:12px 24px;background:#13151f;border-bottom:1px solid #2d3748;flex-wrap:wrap}
.tab{padding:8px 18px;border-radius:8px;cursor:pointer;font-size:.875rem;color:#94a3b8;border:none;background:none}
.tab:hover{background:#1e2130;color:#e2e8f0}
.tab.active{background:#7c3aed;color:#fff}
main{padding:24px;max-width:960px;margin:0 auto}
.panel{display:none}.panel.active{display:block}
h2{font-size:1rem;font-weight:700;margin-bottom:16px;color:#c4b5fd}
h3{font-size:.9rem;font-weight:600;margin:20px 0 10px;color:#a78bfa}
.card{background:#1a1d2e;border:1px solid #2d3748;border-radius:12px;padding:20px;margin-bottom:16px}
label{display:block;font-size:.8rem;color:#94a3b8;margin-bottom:4px;margin-top:12px}
label:first-child{margin-top:0}
input[type=text],input[type=password],input[type=number],textarea,select{
  width:100%;background:#0f1117;border:1px solid #2d3748;border-radius:8px;
  padding:8px 12px;color:#e2e8f0;font-size:.875rem;outline:none}
input:focus,textarea:focus,select:focus{border-color:#7c3aed}
textarea{resize:vertical;min-height:80px;font-family:monospace}
.toggle-row{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid #1e2130}
.toggle-row:last-child{border-bottom:none}
.toggle{position:relative;width:44px;height:24px}
.toggle input{opacity:0;width:0;height:0}
.slider{position:absolute;inset:0;background:#374151;border-radius:12px;cursor:pointer;transition:.3s}
.slider:before{content:'';position:absolute;width:18px;height:18px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.3s}
input:checked+.slider{background:#7c3aed}
input:checked+.slider:before{transform:translateX(20px)}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.row3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
#log-box{background:#0a0c14;border:1px solid #2d3748;border-radius:8px;padding:12px;font-family:monospace;font-size:.75rem;height:400px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;color:#86efac}
.log-toolbar{display:flex;gap:8px;margin-bottom:10px;align-items:center}
.log-toolbar input{flex:1}
.btn-sm{background:#1e2130;border:1px solid #374151;color:#94a3b8;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:.8rem}
.btn-sm:hover{background:#2d3748;color:#e2e8f0}
.btn-danger{background:#7f1d1d;border-color:#991b1b;color:#fca5a5}
.btn-danger:hover{background:#991b1b}
.skill-list{list-style:none;display:flex;flex-direction:column;gap:8px;margin-bottom:16px}
.skill-item{display:flex;align-items:center;justify-content:space-between;background:#0f1117;border:1px solid #2d3748;border-radius:8px;padding:10px 14px}
.skill-item span{font-size:.875rem;color:#c4b5fd}
.skill-actions{display:flex;gap:6px}
.mcp-item{background:#0f1117;border:1px solid #2d3748;border-radius:8px;padding:14px;margin-bottom:10px}
.mcp-item .row2{margin-top:8px}
.add-btn{background:none;border:1px dashed #374151;color:#7c3aed;width:100%;padding:10px;border-radius:8px;cursor:pointer;font-size:.875rem}
.add-btn:hover{background:#1e2130}
.msg{padding:10px 14px;border-radius:8px;font-size:.85rem;margin-bottom:12px;display:none}
.msg.success{background:#065f46;color:#6ee7b7;display:block}
.msg.error{background:#7f1d1d;color:#fca5a5;display:block}
</style>
</head>
<body>
<header>
  <h1>&#x1F916; NanoBot</h1>
  <span id="status-badge" class="stopped">Stopped</span>
  <button id="restart-btn" onclick="restartGateway()">&#x21BB; Restart</button>
  <button id="save-btn" onclick="saveConfig()">Save Config</button>
</header>
<nav>
  <button class="tab active" onclick="switchTab('providers')">Providers</button>
  <button class="tab" onclick="switchTab('channels')">Channels</button>
  <button class="tab" onclick="switchTab('tools')">Tools</button>
  <button class="tab" onclick="switchTab('mcp')">MCP Servers</button>
  <button class="tab" onclick="switchTab('skills')">Skills</button>
  <button class="tab" onclick="switchTab('memory')">Memory</button>
  <button class="tab" onclick="switchTab('logs')">Logs</button>
</nav>
<main>
<div id="flash" class="msg"></div>

<!-- PROVIDERS -->
<div id="panel-providers" class="panel active">
<h2>AI Providers</h2>

<div class="card">
<h3>OpenRouter</h3>
<label>API Key</label><input type="password" id="or-key" placeholder="sk-or-..."/>
<label>API Base</label><input type="text" id="or-base" value="https://openrouter.ai/api/v1"/>
<label>Default Model</label><input type="text" id="or-model" placeholder="openai/gpt-4o"/>
</div>

<div class="card">
<h3>OpenAI</h3>
<label>API Key</label><input type="password" id="oai-key" placeholder="sk-..."/>
<label>API Base</label><input type="text" id="oai-base" value="https://api.openai.com/v1"/>
<label>Default Model</label><input type="text" id="oai-model" placeholder="gpt-4o"/>
</div>

<div class="card">
<h3>Anthropic</h3>
<label>API Key</label><input type="password" id="ant-key" placeholder="sk-ant-..."/>
<label>Default Model</label><input type="text" id="ant-model" placeholder="claude-3-5-sonnet-20241022"/>
</div>

<div class="card">
<h3>Google Gemini</h3>
<label>API Key</label><input type="password" id="gem-key" placeholder="AIza..."/>
<label>Default Model</label><input type="text" id="gem-model" placeholder="gemini-1.5-pro"/>
</div>

<div class="card">
<h3>DeepSeek</h3>
<label>API Key</label><input type="password" id="ds-key" placeholder="sk-..."/>
<label>API Base</label><input type="text" id="ds-base" value="https://api.deepseek.com/v1"/>
<label>Default Model</label><input type="text" id="ds-model" placeholder="deepseek-chat"/>
</div>

<div class="card">
<h3>Groq</h3>
<label>API Key</label><input type="password" id="groq-key" placeholder="gsk_..."/>
<label>Default Model</label><input type="text" id="groq-model" placeholder="llama-3.3-70b-versatile"/>
</div>

<div class="card">
<h3>Moonshot</h3>
<label>API Key</label><input type="password" id="moon-key" placeholder="sk-..."/>
<label>API Base</label><input type="text" id="moon-base" value="https://api.moonshot.cn/v1"/>
<label>Default Model</label><input type="text" id="moon-model" placeholder="moonshot-v1-8k"/>
</div>

<div class="card">
<h3>Zhipu AI</h3>
<label>API Key</label><input type="password" id="zhipu-key" placeholder="..."/>
<label>Default Model</label><input type="text" id="zhipu-model" placeholder="glm-4"/>
</div>

<div class="card">
<h3>DashScope (Alibaba)</h3>
<label>API Key</label><input type="password" id="dash-key" placeholder="sk-..."/>
<label>Default Model</label><input type="text" id="dash-model" placeholder="qwen-turbo"/>
</div>

<div class="card">
<h3>AiHubMix</h3>
<label>API Key</label><input type="password" id="ahm-key" placeholder="..."/>
<label>API Base</label><input type="text" id="ahm-base" value="https://aihubmix.com/v1"/>
<label>Default Model</label><input type="text" id="ahm-model" placeholder="gpt-4o"/>
</div>

<div class="card">
<h3>NVIDIA NIM</h3>
<label>API Key</label><input type="password" id="nvidia-key" placeholder="nvapi-..."/>
<label>API Base</label><input type="text" id="nvidia-base" value="https://integrate.api.nvidia.com/v1"/>
<label>Default Model</label><input type="text" id="nvidia-model" placeholder="meta/llama-3.1-70b-instruct"/>
</div>

<div class="card">
<h3>vLLM (Self-hosted)</h3>
<label>API Base URL</label><input type="text" id="vllm-base" placeholder="http://localhost:8000/v1"/>
<label>Model Name</label><input type="text" id="vllm-model" placeholder="your-model-name"/>
<label>API Key (optional)</label><input type="password" id="vllm-key" placeholder="token-..."/>
</div>

</div><!-- /panel-providers -->

<!-- CHANNELS -->
<div id="panel-channels" class="panel">
<h2>Channels</h2>

<div class="card">
<h3>Telegram</h3>
<div class="toggle-row"><span>Enabled</span><label class="toggle"><input type="checkbox" id="tg-enabled"/><span class="slider"></span></label></div>
<label>Bot Token</label><input type="password" id="tg-token" placeholder="123456:ABC-..."/>
</div>

<div class="card">
<h3>Discord</h3>
<div class="toggle-row"><span>Enabled</span><label class="toggle"><input type="checkbox" id="dc-enabled"/><span class="slider"></span></label></div>
<label>Bot Token</label><input type="password" id="dc-token" placeholder="MTI..."/>
<label>Application ID</label><input type="text" id="dc-app-id" placeholder="123456789"/>
</div>

<div class="card">
<h3>Slack</h3>
<div class="toggle-row"><span>Enabled</span><label class="toggle"><input type="checkbox" id="sl-enabled"/><span class="slider"></span></label></div>
<label>Bot Token</label><input type="password" id="sl-token" placeholder="xoxb-..."/>
<label>App Token</label><input type="password" id="sl-app-token" placeholder="xapp-..."/>
<label>Signing Secret</label><input type="password" id="sl-secret" placeholder="..."/>
</div>

<div class="card">
<h3>WhatsApp</h3>
<div class="toggle-row"><span>Enabled</span><label class="toggle"><input type="checkbox" id="wa-enabled"/><span class="slider"></span></label></div>
<label>Phone Number ID</label><input type="text" id="wa-phone-id" placeholder="123456789"/>
<label>Access Token</label><input type="password" id="wa-token" placeholder="EAAx..."/>
<label>Verify Token</label><input type="text" id="wa-verify" placeholder="my-verify-token"/>
</div>

<div class="card">
<h3>Lark / Feishu</h3>
<div class="toggle-row"><span>Enabled</span><label class="toggle"><input type="checkbox" id="lk-enabled"/><span class="slider"></span></label></div>
<label>App ID</label><input type="text" id="lk-app-id" placeholder="cli_..."/>
<label>App Secret</label><input type="password" id="lk-secret" placeholder="..."/>
<label>Verification Token</label><input type="text" id="lk-verify" placeholder="..."/>
</div>

<div class="card">
<h3>DingTalk</h3>
<div class="toggle-row"><span>Enabled</span><label class="toggle"><input type="checkbox" id="dt-enabled"/><span class="slider"></span></label></div>
<label>App Key</label><input type="text" id="dt-key" placeholder="..."/>
<label>App Secret</label><input type="password" id="dt-secret" placeholder="..."/>
</div>

<div class="card">
<h3>WeChat Work (企业微信)</h3>
<div class="toggle-row"><span>Enabled</span><label class="toggle"><input type="checkbox" id="wx-enabled"/><span class="slider"></span></label></div>
<label>Corp ID</label><input type="text" id="wx-corp" placeholder="ww..."/>
<label>Agent ID</label><input type="text" id="wx-agent" placeholder="1000001"/>
<label>Agent Secret</label><input type="password" id="wx-secret" placeholder="..."/>
<label>Token</label><input type="text" id="wx-token" placeholder="..."/>
<label>Encoding AES Key</label><input type="text" id="wx-aes" placeholder="..."/>
</div>

<div class="card">
<h3>Matrix</h3>
<div class="toggle-row"><span>Enabled</span><label class="toggle"><input type="checkbox" id="mx-enabled"/><span class="slider"></span></label></div>
<label>Homeserver URL</label><input type="text" id="mx-server" placeholder="https://matrix.org"/>
<label>Access Token</label><input type="password" id="mx-token" placeholder="syt_..."/>
<label>User ID</label><input type="text" id="mx-user" placeholder="@bot:matrix.org"/>
</div>

<div class="card">
<h3>IRC</h3>
<div class="toggle-row"><span>Enabled</span><label class="toggle"><input type="checkbox" id="irc-enabled"/><span class="slider"></span></label></div>
<label>Server</label><input type="text" id="irc-server" placeholder="irc.libera.chat"/>
<label>Port</label><input type="number" id="irc-port" value="6697"/>
<label>Nick</label><input type="text" id="irc-nick" placeholder="nanobot"/>
<label>Channel</label><input type="text" id="irc-chan" placeholder="#mychannel"/>
<label>Password (optional)</label><input type="password" id="irc-pass" placeholder="..."/>
</div>

</div><!-- /panel-channels -->

<!-- TOOLS -->
<div id="panel-tools" class="panel">
<h2>Built-in Tools</h2>
<div class="card">
<div class="toggle-row"><span>Web Search</span><label class="toggle"><input type="checkbox" id="tool-search"/><span class="slider"></span></label></div>
<div class="toggle-row"><span>Web Scrape / Browse</span><label class="toggle"><input type="checkbox" id="tool-scrape"/><span class="slider"></span></label></div>
<div class="toggle-row"><span>Code Execution (Python)</span><label class="toggle"><input type="checkbox" id="tool-code"/><span class="slider"></span></label></div>
<div class="toggle-row"><span>Image Generation</span><label class="toggle"><input type="checkbox" id="tool-image"/><span class="slider"></span></label></div>
<div class="toggle-row"><span>File Read/Write</span><label class="toggle"><input type="checkbox" id="tool-files"/><span class="slider"></span></label></div>
<div class="toggle-row"><span>Wikipedia</span><label class="toggle"><input type="checkbox" id="tool-wiki"/><span class="slider"></span></label></div>
<div class="toggle-row"><span>Calculator</span><label class="toggle"><input type="checkbox" id="tool-calc"/><span class="slider"></span></label></div>
<div class="toggle-row"><span>Weather</span><label class="toggle"><input type="checkbox" id="tool-weather"/><span class="slider"></span></label></div>
</div>
<div class="card">
<h3>System Prompt</h3>
<label>Custom system prompt (appended to default)</label>
<textarea id="sys-prompt" rows="6" placeholder="You are a helpful assistant..."></textarea>
</div>
</div><!-- /panel-tools -->

<!-- MCP -->
<div id="panel-mcp" class="panel">
<h2>MCP Servers</h2>
<div id="mcp-list"></div>
<button class="add-btn" onclick="addMCP()">+ Add MCP Server</button>
</div>

<!-- SKILLS -->
<div id="panel-skills" class="panel">
<h2>Skills (SKILL.md files)</h2>
<ul class="skill-list" id="skill-list"></ul>
<div class="card">
<h3>New Skill</h3>
<label>Skill Name</label><input type="text" id="skill-name" placeholder="my-skill"/>
<label>Content (Markdown)</label>
<textarea id="skill-content" rows="10" placeholder="# My Skill&#10;&#10;Describe the skill here..."></textarea>
<button class="btn-sm" style="margin-top:12px" onclick="saveSkill()">Save Skill</button>
</div>
</div>

<!-- MEMORY -->
<div id="panel-memory" class="panel">
<h2>Memory (memory.md)</h2>
<div class="card">
<label>Edit memory.md — facts NanoBot should always remember</label>
<textarea id="memory-content" rows="20" placeholder="# Memory&#10;&#10;- User's name is Alice&#10;- Timezone: UTC+8"></textarea>
<button class="btn-sm" style="margin-top:12px" onclick="saveMemory()">Save Memory</button>
</div>
</div>

<!-- LOGS -->
<div id="panel-logs" class="panel">
<h2>Gateway Logs</h2>
<div class="log-toolbar">
<input type="text" id="log-filter" placeholder="Filter logs..." oninput="filterLogs()"/>
<button class="btn-sm" onclick="loadLogs()">&#x21BB; Refresh</button>
<button class="btn-sm btn-danger" onclick="clearLogs()">Clear</button>
<label class="toggle" title="Auto-refresh"><input type="checkbox" id="auto-refresh" onchange="toggleAutoRefresh()"/><span class="slider"></span></label>
<span style="font-size:.75rem;color:#64748b">Auto</span>
</div>
<div id="log-box"></div>
</div>

</main>

<script>
const $ = id => document.getElementById(id);
let cfg = {};
let allLogLines = [];
let autoRefreshTimer = null;
let mcpEntries = [];

// ── Tab switching ──────────────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  $('panel-' + name).classList.add('active');
  event.target.classList.add('active');
  if (name === 'logs') loadLogs();
  if (name === 'skills') loadSkills();
  if (name === 'memory') loadMemory();
}

// ── Flash ──────────────────────────────────────────────────────────────────────
function flash(msg, type='success') {
  const el = $('flash');
  el.textContent = msg;
  el.className = 'msg ' + type;
  setTimeout(() => { el.className = 'msg'; }, 3000);
}

// ── Status ─────────────────────────────────────────────────────────────────────
async function pollStatus() {
  try {
    const r = await fetch('/api/status');
    const d = await r.json();
    const badge = $('status-badge');
    badge.textContent = d.gateway_running ? 'Running' : 'Stopped';
    badge.className = d.gateway_running ? 'running' : 'stopped';
  } catch {}
}
setInterval(pollStatus, 5000);
pollStatus();

// ── Load config ────────────────────────────────────────────────────────────────
async function loadConfig() {
  const r = await fetch('/api/config');
  cfg = await r.json();
  const p = cfg.providers || {};
  const or = p.openrouter || {};
  $('or-key').value = or.api_key || '';
  $('or-base').value = or.api_base || 'https://openrouter.ai/api/v1';
  $('or-model').value = or.default_model || '';
  const oai = p.openai || {};
  $('oai-key').value = oai.api_key || '';
  $('oai-base').value = oai.api_base || 'https://api.openai.com/v1';
  $('oai-model').value = oai.default_model || '';
  const ant = p.anthropic || {};
  $('ant-key').value = ant.api_key || '';
  $('ant-model').value = ant.default_model || '';
  const gem = p.gemini || {};
  $('gem-key').value = gem.api_key || '';
  $('gem-model').value = gem.default_model || '';
  const ds = p.deepseek || {};
  $('ds-key').value = ds.api_key || '';
  $('ds-base').value = ds.api_base || 'https://api.deepseek.com/v1';
  $('ds-model').value = ds.default_model || '';
  const groq = p.groq || {};
  $('groq-key').value = groq.api_key || '';
  $('groq-model').value = groq.default_model || '';
  const moon = p.moonshot || {};
  $('moon-key').value = moon.api_key || '';
  $('moon-base').value = moon.api_base || 'https://api.moonshot.cn/v1';
  $('moon-model').value = moon.default_model || '';
  const zhipu = p.zhipu || {};
  $('zhipu-key').value = zhipu.api_key || '';
  $('zhipu-model').value = zhipu.default_model || '';
  const dash = p.dashscope || {};
  $('dash-key').value = dash.api_key || '';
  $('dash-model').value = dash.default_model || '';
  const ahm = p.aihubmix || {};
  $('ahm-key').value = ahm.api_key || '';
  $('ahm-base').value = ahm.api_base || 'https://aihubmix.com/v1';
  $('ahm-model').value = ahm.default_model || '';
  const nv = p.nvidia || {};
  $('nvidia-key').value = nv.api_key || '';
  $('nvidia-base').value = nv.api_base || 'https://integrate.api.nvidia.com/v1';
  $('nvidia-model').value = nv.default_model || '';
  const vllm = p.vllm || {};
  $('vllm-base').value = vllm.api_base || '';
  $('vllm-model').value = vllm.default_model || '';
  $('vllm-key').value = vllm.api_key || '';

  // Channels
  const ch = cfg.channels || {};
  const tg = ch.telegram || {};
  $('tg-enabled').checked = !!tg.enabled;
  $('tg-token').value = tg.token || '';
  const dc = ch.discord || {};
  $('dc-enabled').checked = !!dc.enabled;
  $('dc-token').value = dc.token || '';
  $('dc-app-id').value = dc.application_id || '';
  const sl = ch.slack || {};
  $('sl-enabled').checked = !!sl.enabled;
  $('sl-token').value = sl.bot_token || '';
  $('sl-app-token').value = sl.app_token || '';
  $('sl-secret').value = sl.signing_secret || '';
  const wa = ch.whatsapp || {};
  $('wa-enabled').checked = !!wa.enabled;
  $('wa-phone-id').value = wa.phone_number_id || '';
  $('wa-token').value = wa.access_token || '';
  $('wa-verify').value = wa.verify_token || '';
  const lk = ch.lark || {};
  $('lk-enabled').checked = !!lk.enabled;
  $('lk-app-id').value = lk.app_id || '';
  $('lk-secret').value = lk.app_secret || '';
  $('lk-verify').value = lk.verification_token || '';
  const dt = ch.dingtalk || {};
  $('dt-enabled').checked = !!dt.enabled;
  $('dt-key').value = dt.app_key || '';
  $('dt-secret').value = dt.app_secret || '';
  const wx = ch.wechat || {};
  $('wx-enabled').checked = !!wx.enabled;
  $('wx-corp').value = wx.corp_id || '';
  $('wx-agent').value = wx.agent_id || '';
  $('wx-secret').value = wx.secret || '';
  $('wx-token').value = wx.token || '';
  $('wx-aes').value = wx.encoding_aes_key || '';
  const mx = ch.matrix || {};
  $('mx-enabled').checked = !!mx.enabled;
  $('mx-server').value = mx.homeserver || '';
  $('mx-token').value = mx.access_token || '';
  $('mx-user').value = mx.user_id || '';
  const irc = ch.irc || {};
  $('irc-enabled').checked = !!irc.enabled;
  $('irc-server').value = irc.server || '';
  $('irc-port').value = irc.port || 6697;
  $('irc-nick').value = irc.nick || '';
  $('irc-chan').value = irc.channel || '';
  $('irc-pass').value = irc.password || '';

  // Tools
  const tools = cfg.tools || {};
  $('tool-search').checked = !!tools.web_search;
  $('tool-scrape').checked = !!tools.web_scrape;
  $('tool-code').checked = !!tools.code_execution;
  $('tool-image').checked = !!tools.image_generation;
  $('tool-files').checked = !!tools.file_rw;
  $('tool-wiki').checked = !!tools.wikipedia;
  $('tool-calc').checked = !!tools.calculator;
  $('tool-weather').checked = !!tools.weather;
  $('sys-prompt').value = cfg.system_prompt || '';

  // MCP
  mcpEntries = cfg.mcp_servers ? [...cfg.mcp_servers] : [];
  renderMCP();
}

// ── Save config ────────────────────────────────────────────────────────────────
async function saveConfig() {
  const newCfg = {
    providers: {
      openrouter: {api_key: $('or-key').value, api_base: $('or-base').value, default_model: $('or-model').value},
      openai: {api_key: $('oai-key').value, api_base: $('oai-base').value, default_model: $('oai-model').value},
      anthropic: {api_key: $('ant-key').value, default_model: $('ant-model').value},
      gemini: {api_key: $('gem-key').value, default_model: $('gem-model').value},
      deepseek: {api_key: $('ds-key').value, api_base: $('ds-base').value, default_model: $('ds-model').value},
      groq: {api_key: $('groq-key').value, default_model: $('groq-model').value},
      moonshot: {api_key: $('moon-key').value, api_base: $('moon-base').value, default_model: $('moon-model').value},
      zhipu: {api_key: $('zhipu-key').value, default_model: $('zhipu-model').value},
      dashscope: {api_key: $('dash-key').value, default_model: $('dash-model').value},
      aihubmix: {api_key: $('ahm-key').value, api_base: $('ahm-base').value, default_model: $('ahm-model').value},
      nvidia: {api_key: $('nvidia-key').value, api_base: $('nvidia-base').value, default_model: $('nvidia-model').value},
      vllm: {api_base: $('vllm-base').value, default_model: $('vllm-model').value, api_key: $('vllm-key').value},
    },
    channels: {
      telegram: {enabled: $('tg-enabled').checked, token: $('tg-token').value},
      discord: {enabled: $('dc-enabled').checked, token: $('dc-token').value, application_id: $('dc-app-id').value},
      slack: {enabled: $('sl-enabled').checked, bot_token: $('sl-token').value, app_token: $('sl-app-token').value, signing_secret: $('sl-secret').value},
      whatsapp: {enabled: $('wa-enabled').checked, phone_number_id: $('wa-phone-id').value, access_token: $('wa-token').value, verify_token: $('wa-verify').value},
      lark: {enabled: $('lk-enabled').checked, app_id: $('lk-app-id').value, app_secret: $('lk-secret').value, verification_token: $('lk-verify').value},
      dingtalk: {enabled: $('dt-enabled').checked, app_key: $('dt-key').value, app_secret: $('dt-secret').value},
      wechat: {enabled: $('wx-enabled').checked, corp_id: $('wx-corp').value, agent_id: $('wx-agent').value, secret: $('wx-secret').value, token: $('wx-token').value, encoding_aes_key: $('wx-aes').value},
      matrix: {enabled: $('mx-enabled').checked, homeserver: $('mx-server').value, access_token: $('mx-token').value, user_id: $('mx-user').value},
      irc: {enabled: $('irc-enabled').checked, server: $('irc-server').value, port: parseInt($('irc-port').value)||6697, nick: $('irc-nick').value, channel: $('irc-chan').value, password: $('irc-pass').value},
    },
    tools: {
      web_search: $('tool-search').checked,
      web_scrape: $('tool-scrape').checked,
      code_execution: $('tool-code').checked,
      image_generation: $('tool-image').checked,
      file_rw: $('tool-files').checked,
      wikipedia: $('tool-wiki').checked,
      calculator: $('tool-calc').checked,
      weather: $('tool-weather').checked,
    },
    system_prompt: $('sys-prompt').value,
    mcp_servers: mcpEntries,
  };
  const r = await fetch('/api/config', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(newCfg)});
  const d = await r.json();
  if (d.success) flash('Config saved!');
  else flash('Error: ' + d.error, 'error');
}

// ── Restart ────────────────────────────────────────────────────────────────────
async function restartGateway() {
  $('restart-btn').textContent = 'Restarting...';
  const r = await fetch('/api/restart', {method:'POST'});
  const d = await r.json();
  $('restart-btn').textContent = '\u21BB Restart';
  if (d.success) flash('Gateway restarted!');
  else flash('Error: ' + d.error, 'error');
  pollStatus();
}

// ── MCP ────────────────────────────────────────────────────────────────────────
function renderMCP() {
  const container = $('mcp-list');
  container.innerHTML = '';
  mcpEntries.forEach((entry, i) => {
    const div = document.createElement('div');
    div.className = 'mcp-item';
    div.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center">
        <strong style="color:#c4b5fd">MCP #${i+1}</strong>
        <button class="btn-sm btn-danger" onclick="removeMCP(${i})">Remove</button>
      </div>
      <div class="row2">
        <div><label>Name</label><input type="text" value="${entry.name||''}" oninput="mcpEntries[${i}].name=this.value" placeholder="my-server"/></div>
        <div><label>Type</label>
          <select onchange="mcpEntries[${i}].type=this.value;renderMCP()">
            <option value="stdio" ${entry.type==='stdio'?'selected':''}>stdio</option>
            <option value="sse" ${entry.type==='sse'?'selected':''}>SSE / HTTP</option>
          </select>
        </div>
      </div>
      ${entry.type==='sse' ? `
        <label>URL</label><input type="text" value="${entry.url||''}" oninput="mcpEntries[${i}].url=this.value" placeholder="https://..."/>
        <label>Auth Token (optional)</label><input type="password" value="${entry.auth_token||''}" oninput="mcpEntries[${i}].auth_token=this.value"/>
      ` : `
        <label>Command</label><input type="text" value="${entry.command||''}" oninput="mcpEntries[${i}].command=this.value" placeholder="node server.js"/>
        <label>Args (space-separated)</label><input type="text" value="${(entry.args||[]).join(' ')}" oninput="mcpEntries[${i}].args=this.value.split(' ').filter(Boolean)" placeholder="--port 3000"/>
        <label>Working Directory</label><input type="text" value="${entry.cwd||''}" oninput="mcpEntries[${i}].cwd=this.value" placeholder="/path/to/server"/>
      `}
    `;
    container.appendChild(div);
  });
}

function addMCP() {
  mcpEntries.push({name:'', type:'stdio', command:'', args:[], cwd:'', url:'', auth_token:''});
  renderMCP();
}

function removeMCP(i) {
  mcpEntries.splice(i, 1);
  renderMCP();
}

// ── Skills ─────────────────────────────────────────────────────────────────────
async function loadSkills() {
  const r = await fetch('/api/skills');
  const d = await r.json();
  const list = $('skill-list');
  list.innerHTML = '';
  (d.skills || []).forEach(s => {
    const li = document.createElement('li');
    li.className = 'skill-item';
    li.innerHTML = `<span>${s.name}.md <small style="color:#64748b">(${(s.size/1024).toFixed(1)}KB)</small></span>
      <div class="skill-actions">
        <button class="btn-sm" onclick="editSkill('${s.name}')">Edit</button>
        <button class="btn-sm btn-danger" onclick="deleteSkill('${s.name}')">Delete</button>
      </div>`;
    list.appendChild(li);
  });
}

async function editSkill(name) {
  const r = await fetch('/api/skills/' + name);
  const d = await r.json();
  $('skill-name').value = d.name;
  $('skill-content').value = d.content;
}

async function saveSkill() {
  const name = $('skill-name').value.trim();
  if (!name) { flash('Enter a skill name', 'error'); return; }
  const r = await fetch('/api/skills/' + name, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({content: $('skill-content').value})});
  const d = await r.json();
  if (d.success) { flash('Skill saved!'); loadSkills(); $('skill-name').value=''; $('skill-content').value=''; }
  else flash('Error: ' + d.error, 'error');
}

async function deleteSkill(name) {
  if (!confirm('Delete skill ' + name + '?')) return;
  await fetch('/api/skills/' + name, {method:'DELETE'});
  loadSkills();
}

// ── Memory ─────────────────────────────────────────────────────────────────────
async function loadMemory() {
  const r = await fetch('/api/memory');
  const d = await r.json();
  $('memory-content').value = d.content || '';
}

async function saveMemory() {
  const r = await fetch('/api/memory', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({content: $('memory-content').value})});
  const d = await r.json();
  if (d.success) flash('Memory saved!');
  else flash('Error: ' + d.error, 'error');
}

// ── Logs ───────────────────────────────────────────────────────────────────────
async function loadLogs() {
  const r = await fetch('/api/logs?lines=300');
  const d = await r.json();
  allLogLines = d.lines || [];
  filterLogs();
  const box = $('log-box');
  box.scrollTop = box.scrollHeight;
}

function filterLogs() {
  const q = $('log-filter').value.toLowerCase();
  const filtered = q ? allLogLines.filter(l => l.toLowerCase().includes(q)) : allLogLines;
  $('log-box').textContent = filtered.join('');
}

async function clearLogs() {
  if (!confirm('Clear all logs?')) return;
  await fetch('/api/logs/clear', {method:'POST'});
  allLogLines = [];
  $('log-box').textContent = '';
}

function toggleAutoRefresh() {
  if ($('auto-refresh').checked) {
    autoRefreshTimer = setInterval(loadLogs, 3000);
  } else {
    clearInterval(autoRefreshTimer);
    autoRefreshTimer = null;
  }
}

// ── Init ───────────────────────────────────────────────────────────────────────
loadConfig();
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def root(_=Depends(check_auth)):
    return HTML
