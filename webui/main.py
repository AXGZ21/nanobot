"""NanoBot Web UI"""
import json, os, subprocess, threading, secrets
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

app = FastAPI(title="NanoBot")
security = HTTPBasic(auto_error=False)

NANOBOT_DIR = Path(os.environ.get("NANOBOT_DIR", str(Path.home() / ".nanobot")))
CONFIG_FILE = NANOBOT_DIR / "config.toml"
MEMORY_FILE = NANOBOT_DIR / "memory.md"
SKILLS_DIR = NANOBOT_DIR / "skills"
ADMIN_USER = os.environ.get("WEBUI_USER", "admin")
ADMIN_PASS = os.environ.get("WEBUI_PASS", "nanobot123")
_proc = None
_lock = threading.Lock()

def verify(creds):
    if not creds:
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})
    u = secrets.compare_digest(creds.username.encode(), ADMIN_USER.encode())
    p = secrets.compare_digest(creds.password.encode(), ADMIN_PASS.encode())
    if not (u and p):
        raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})

def read_cfg():
    if not CONFIG_FILE.exists(): return {}
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(CONFIG_FILE, "rb") as f: return tomllib.load(f)

def write_cfg(data):
    NANOBOT_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    def _w(d, pre=""):
        for k, v in d.items():
            key = f"{pre}.{k}" if pre else k
            if isinstance(v, dict): _w(v, key)
            elif isinstance(v, bool): lines.append(f"{key} = {str(v).lower()}")
            elif isinstance(v, (int,float)): lines.append(f"{key} = {v}")
            else:
                escaped = v.replace('\\', '\\\\').replace('"', '\\"')
                lines.append(f'{key} = "{escaped}"')
    _w(data)
    CONFIG_FILE.write_text("\n".join(lines)+"\n")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    creds = await security(request)
    try: verify(creds)
    except: return HTMLResponse("<h2>401</h2>", 401, headers={"WWW-Authenticate":"Basic realm=NanoBot"})
    return HTMLResponse(get_html())

@app.get("/api/config")
async def get_config(request: Request):
    creds = await security(request); verify(creds)
    return read_cfg()

@app.post("/api/config")
async def set_config(request: Request):
    creds = await security(request); verify(creds)
    write_cfg(await request.json()); return {"ok": True}

@app.get("/api/status")
async def status(request: Request):
    creds = await security(request); verify(creds)
    running = _proc is not None and _proc.poll() is None
    return {"running": running, "pid": _proc.pid if running else None}

@app.post("/api/gateway/{action}")
async def gateway(action: str, request: Request):
    global _proc
    creds = await security(request); verify(creds)
    with _lock:
        if action == "start":
            if _proc and _proc.poll() is None: return {"ok":True,"msg":"already running"}
            _proc = subprocess.Popen(["nanobot","start"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(NANOBOT_DIR))
            return {"ok":True,"pid":_proc.pid}
        elif action == "stop":
            if _proc and _proc.poll() is None: _proc.terminate(); _proc.wait(10)
            return {"ok":True}
        elif action == "restart":
            if _proc and _proc.poll() is None: _proc.terminate(); _proc.wait(10)
            _proc = subprocess.Popen(["nanobot","start"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(NANOBOT_DIR))
            return {"ok":True,"pid":_proc.pid}

@app.get("/api/logs")
async def logs(request: Request):
    creds = await security(request); verify(creds)
    if not _proc: return {"lines":[]}
    try:
        import fcntl
        fd = _proc.stdout.fileno()
        fl = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
        raw = _proc.stdout.read(8192) or b""
        return {"lines": raw.decode(errors="replace").splitlines()[-200:]}
    except Exception as e:
        return {"lines":[str(e)]}

@app.get("/api/skills")
async def list_skills(request: Request):
    creds = await security(request); verify(creds)
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    return {"skills":[{"name":f.stem,"size":f.stat().st_size} for f in sorted(SKILLS_DIR.glob("*.md"))]}

@app.get("/api/skills/{name}")
async def get_skill(name: str, request: Request):
    creds = await security(request); verify(creds)
    f = SKILLS_DIR/f"{name}.md"
    if not f.exists(): raise HTTPException(404)
    return {"name":name,"content":f.read_text()}

@app.post("/api/skills/{name}")
async def save_skill(name: str, request: Request):
    creds = await security(request); verify(creds)
    data = await request.json()
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    (SKILLS_DIR/f"{name}.md").write_text(data.get("content",""))
    return {"ok":True}

@app.delete("/api/skills/{name}")
async def del_skill(name: str, request: Request):
    creds = await security(request); verify(creds)
    f = SKILLS_DIR/f"{name}.md"
    if f.exists(): f.unlink()
    return {"ok":True}

@app.get("/api/memory")
async def get_mem(request: Request):
    creds = await security(request); verify(creds)
    return {"content": MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""}

@app.post("/api/memory")
async def save_mem(request: Request):
    creds = await security(request); verify(creds)
    data = await request.json()
    NANOBOT_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(data.get("content",""))
    return {"ok":True}

def get_html():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>NanoBot</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0d0d14;color:#e2e2e2;display:flex;flex-direction:column;height:100vh;overflow:hidden}
::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:#111}::-webkit-scrollbar-thumb{background:#333;border-radius:3px}
header{background:#111827;padding:14px 24px;display:flex;align-items:center;gap:12px;border-bottom:1px solid #1f2937;flex-shrink:0}
header h1{font-size:1.2rem;font-weight:700;color:#fff;letter-spacing:-0.5px}
header h1 span{color:#818cf8}
#status-badge{margin-left:auto;padding:4px 12px;border-radius:20px;font-size:0.72rem;font-weight:600;border:1px solid}
.running{background:#052e16;color:#4ade80;border-color:#166534!important}
.stopped{background:#2d0707;color:#f87171;border-color:#7f1d1d!important}
.layout{display:flex;flex:1;overflow:hidden}
nav{width:190px;background:#111827;border-right:1px solid #1f2937;padding:12px 0;display:flex;flex-direction:column;gap:2px;flex-shrink:0}
nav button{display:flex;align-items:center;gap:10px;width:100%;padding:10px 16px;background:none;border:none;color:#9ca3af;cursor:pointer;font-size:0.85rem;text-align:left;border-left:3px solid transparent;transition:all 0.15s}
nav button:hover{background:#1f2937;color:#e2e2e2}
nav button.active{background:#1e1b4b;color:#a5b4fc;border-left-color:#6366f1;font-weight:600}
nav .icon{font-size:1rem;width:20px;text-align:center}
main{flex:1;overflow-y:auto;padding:24px}
.panel{display:none}.panel.active{display:block}
.panel-title{font-size:1.1rem;font-weight:700;color:#c7d2fe;margin-bottom:20px;padding-bottom:12px;border-bottom:1px solid #1f2937}
.card{background:#111827;border:1px solid #1f2937;border-radius:10px;padding:20px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-bottom:20px}
.tile{background:#111827;border:2px solid #1f2937;border-radius:10px;padding:16px 12px;cursor:pointer;transition:all 0.2s;text-align:center}
.tile:hover{border-color:#4f46e5;background:#1a1a35}
.tile.configured{border-color:#16a34a;background:#052e16}
.tile .tile-icon{font-size:1.8rem;margin-bottom:8px}
.tile .tile-name{font-size:0.82rem;font-weight:600;color:#e2e2e2}
.tile .tile-sub{font-size:0.7rem;color:#6b7280;margin-top:3px}
.tile.configured .tile-name{color:#4ade80}
.form-row{display:flex;flex-direction:column;gap:6px;margin-bottom:14px}
.form-row label{font-size:0.8rem;color:#9ca3af;font-weight:500}
input,textarea,select{background:#1f2937;border:1px solid #374151;border-radius:6px;color:#e2e2e2;padding:8px 12px;font-size:0.85rem;width:100%;outline:none;transition:border 0.15s}
input:focus,textarea:focus{border-color:#6366f1}
textarea{resize:vertical;min-height:120px;font-family:monospace}
.btn{padding:8px 18px;border-radius:6px;border:none;cursor:pointer;font-size:0.83rem;font-weight:600;transition:all 0.15s}
.btn-primary{background:#4f46e5;color:#fff}.btn-primary:hover{background:#4338ca}
.btn-success{background:#16a34a;color:#fff}.btn-success:hover{background:#15803d}
.btn-danger{background:#dc2626;color:#fff}.btn-danger:hover{background:#b91c1c}
.btn-ghost{background:#1f2937;color:#9ca3af;border:1px solid #374151}.btn-ghost:hover{color:#e2e2e2}
.btn-sm{padding:5px 12px;font-size:0.78rem}
.row{display:flex;gap:10px;align-items:center}
.log-box{background:#000;border:1px solid #1f2937;border-radius:8px;padding:14px;font-family:monospace;font-size:0.78rem;color:#4ade80;height:380px;overflow-y:auto;white-space:pre-wrap;word-break:break-all}
.skill-item{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:#1f2937;border-radius:8px;margin-bottom:8px}
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,0.75);z-index:100;align-items:center;justify-content:center}
.modal-bg.open{display:flex}
.modal{background:#111827;border:1px solid #374151;border-radius:12px;padding:28px;width:420px;max-width:90vw}
.modal h3{font-size:1rem;font-weight:700;color:#c7d2fe;margin-bottom:18px}
.modal .close{float:right;background:none;border:none;color:#6b7280;font-size:1.2rem;cursor:pointer;margin-top:-4px}
.mcp-item{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:#1f2937;border-radius:8px;margin-bottom:8px}
.section-actions{display:flex;justify-content:flex-end;margin-bottom:16px}
</style>
</head>
<body>
<header>
  <h1>Nano<span>Bot</span></h1>
  <span id="status-badge" class="stopped">Stopped</span>
  <div style="margin-left:16px;display:flex;gap:8px">
    <button class="btn btn-sm btn-success" onclick="gw('start')">Start</button>
    <button class="btn btn-sm btn-ghost" onclick="gw('restart')">Restart</button>
    <button class="btn btn-sm btn-danger" onclick="gw('stop')">Stop</button>
  </div>
</header>
<div class="layout">
<nav>
  <button class="active" onclick="show('providers',this)"><span class="icon">&#128273;</span>Providers</button>
  <button onclick="show('channels',this)"><span class="icon">&#128172;</span>Channels</button>
  <button onclick="show('skills',this)"><span class="icon">&#129504;</span>Skills</button>
  <button onclick="show('memory',this)"><span class="icon">&#128221;</span>Memory</button>
  <button onclick="show('mcp',this)"><span class="icon">&#128268;</span>MCP Servers</button>
  <button onclick="show('logs',this)"><span class="icon">&#128203;</span>Logs</button>
</nav>
<main>
<div id="panel-providers" class="panel active">
  <div class="panel-title">AI Providers</div>
  <div class="grid" id="providers-grid"></div>
</div>
<div id="panel-channels" class="panel">
  <div class="panel-title">Channels</div>
  <div class="grid" id="channels-grid"></div>
</div>
<div id="panel-skills" class="panel">
  <div class="panel-title">Skills</div>
  <div class="section-actions"><button class="btn btn-primary btn-sm" onclick="newSkill()">+ New Skill</button></div>
  <div id="skills-list"></div>
  <div id="skill-editor" style="display:none" class="card">
    <div class="form-row"><label>Skill Name</label><input id="skill-name" placeholder="my-skill"/></div>
    <div class="form-row"><label>Content (Markdown)</label><textarea id="skill-content" style="min-height:200px"></textarea></div>
    <div class="row"><button class="btn btn-primary btn-sm" onclick="saveSkill()">Save</button><button class="btn btn-ghost btn-sm" onclick="cancelSkill()">Cancel</button></div>
  </div>
</div>
<div id="panel-memory" class="panel">
  <div class="panel-title">Memory</div>
  <div class="card">
    <div class="form-row"><textarea id="memory-content" style="min-height:300px"></textarea></div>
    <button class="btn btn-primary btn-sm" onclick="saveMemory()">Save Memory</button>
  </div>
</div>
<div id="panel-mcp" class="panel">
  <div class="panel-title">MCP Servers</div>
  <div class="section-actions"><button class="btn btn-primary btn-sm" onclick="openMCP()">+ Add Server</button></div>
  <div id="mcp-list"></div>
</div>
<div id="panel-logs" class="panel">
  <div class="panel-title">Logs</div>
  <div class="row" style="margin-bottom:12px;gap:12px">
    <input id="log-filter" placeholder="Filter..." style="max-width:220px" oninput="renderLogs()"/>
    <button class="btn btn-ghost btn-sm" onclick="loadLogs()">Refresh</button>
    <label style="font-size:0.8rem;color:#9ca3af;display:flex;align-items:center;gap:6px"><input type="checkbox" id="log-auto" onchange="toggleAuto()"> Auto</label>
    <button class="btn btn-danger btn-sm" style="margin-left:auto" onclick="clearLogs()">Clear</button>
  </div>
  <div class="log-box" id="log-box"></div>
</div>
</main>
</div>

<div class="modal-bg" id="provider-modal">
  <div class="modal">
    <button class="close" onclick="closeModal('provider-modal')">&times;</button>
    <h3 id="pm-title">Configure Provider</h3>
    <div id="pm-body"></div>
    <div class="row" style="margin-top:16px;justify-content:flex-end;gap:8px">
      <button class="btn btn-ghost btn-sm" onclick="closeModal('provider-modal')">Cancel</button>
      <button class="btn btn-primary btn-sm" onclick="saveProvider()">Save</button>
    </div>
  </div>
</div>
<div class="modal-bg" id="channel-modal">
  <div class="modal">
    <button class="close" onclick="closeModal('channel-modal')">&times;</button>
    <h3 id="cm-title">Configure Channel</h3>
    <div id="cm-body"></div>
    <div class="row" style="margin-top:16px;justify-content:flex-end;gap:8px">
      <button class="btn btn-ghost btn-sm" onclick="closeModal('channel-modal')">Cancel</button>
      <button class="btn btn-primary btn-sm" onclick="saveChannel()">Save</button>
    </div>
  </div>
</div>
<div class="modal-bg" id="mcp-modal">
  <div class="modal">
    <button class="close" onclick="closeModal('mcp-modal')">&times;</button>
    <h3>Add MCP Server</h3>
    <div class="form-row"><label>Name</label><input id="mcp-name" placeholder="my-server"/></div>
    <div class="form-row"><label>Type</label>
      <select id="mcp-type" onchange="toggleMCPType()">
        <option value="sse">SSE (HTTP)</option>
        <option value="stdio">stdio (process)</option>
      </select>
    </div>
    <div id="mcp-sse-fields"><div class="form-row"><label>URL</label><input id="mcp-url" placeholder="https://..."/></div></div>
    <div id="mcp-stdio-fields" style="display:none">
      <div class="form-row"><label>Command</label><input id="mcp-cmd" placeholder="python"/></div>
      <div class="form-row"><label>Args (comma separated)</label><input id="mcp-args" placeholder="-m,myserver"/></div>
      <div class="form-row"><label>Working Dir</label><input id="mcp-cwd" placeholder="/opt/mcp"/></div>
    </div>
    <div class="row" style="margin-top:16px;justify-content:flex-end;gap:8px">
      <button class="btn btn-ghost btn-sm" onclick="closeModal('mcp-modal')">Cancel</button>
      <button class="btn btn-primary btn-sm" onclick="saveMCP()">Add</button>
    </div>
  </div>
</div>

<script>
const PROVIDERS=[
  {id:"openrouter",name:"OpenRouter",icon:"&#127760;",fields:[{k:"openrouter.api_key",l:"API Key",t:"password"}]},
  {id:"openai",name:"OpenAI",icon:"&#129302;",fields:[{k:"openai.api_key",l:"API Key",t:"password"},{k:"openai.base_url",l:"Base URL (optional)",t:"text"}]},
  {id:"anthropic",name:"Anthropic",icon:"&#129516;",fields:[{k:"anthropic.api_key",l:"API Key",t:"password"}]},
  {id:"gemini",name:"Gemini",icon:"&#10024;",fields:[{k:"gemini.api_key",l:"API Key",t:"password"}]},
  {id:"deepseek",name:"DeepSeek",icon:"&#128269;",fields:[{k:"deepseek.api_key",l:"API Key",t:"password"}]},
  {id:"groq",name:"Groq",icon:"&#9889;",fields:[{k:"groq.api_key",l:"API Key",t:"password"}]},
  {id:"moonshot",name:"Moonshot",icon:"&#127769;",fields:[{k:"moonshot.api_key",l:"API Key",t:"password"}]},
  {id:"zhipu",name:"Zhipu",icon:"&#127464;&#127475;",fields:[{k:"zhipu.api_key",l:"API Key",t:"password"}]},
  {id:"dashscope",name:"DashScope",icon:"&#128202;",fields:[{k:"dashscope.api_key",l:"API Key",t:"password"}]},
  {id:"aihubmix",name:"AiHubMix",icon:"&#127907;",fields:[{k:"aihubmix.api_key",l:"API Key",t:"password"}]},
  {id:"nvidia",name:"NVIDIA NIM",icon:"&#128421;",fields:[{k:"nvidia.api_key",l:"API Key",t:"password"},{k:"nvidia.base_url",l:"Base URL",t:"text"}]},
  {id:"vllm",name:"vLLM",icon:"&#129422;",fields:[{k:"vllm.base_url",l:"Base URL",t:"text"},{k:"vllm.api_key",l:"API Key (opt)",t:"password"}]},
];
const CHANNELS=[
  {id:"telegram",name:"Telegram",icon:"&#9992;",fields:[{k:"telegram.token",l:"Bot Token",t:"password"},{k:"telegram.allowed_users",l:"Allowed Users",t:"text"}]},
  {id:"discord",name:"Discord",icon:"&#127918;",fields:[{k:"discord.token",l:"Bot Token",t:"password"},{k:"discord.allowed_channels",l:"Allowed Channels",t:"text"}]},
  {id:"slack",name:"Slack",icon:"&#128188;",fields:[{k:"slack.bot_token",l:"Bot Token",t:"password"},{k:"slack.app_token",l:"App Token",t:"password"}]},
  {id:"whatsapp",name:"WhatsApp",icon:"&#128241;",fields:[{k:"whatsapp.phone_id",l:"Phone Number ID",t:"text"},{k:"whatsapp.token",l:"Access Token",t:"password"},{k:"whatsapp.verify_token",l:"Verify Token",t:"text"}]},
  {id:"lark",name:"Lark",icon:"&#128038;",fields:[{k:"lark.app_id",l:"App ID",t:"text"},{k:"lark.app_secret",l:"App Secret",t:"password"}]},
  {id:"dingtalk",name:"DingTalk",icon:"&#128276;",fields:[{k:"dingtalk.client_id",l:"Client ID",t:"text"},{k:"dingtalk.client_secret",l:"Client Secret",t:"password"}]},
  {id:"wecom",name:"WeCom",icon:"&#128172;",fields:[{k:"wecom.corp_id",l:"Corp ID",t:"text"},{k:"wecom.secret",l:"Secret",t:"password"}]},
  {id:"matrix",name:"Matrix",icon:"&#128311;",fields:[{k:"matrix.homeserver",l:"Homeserver URL",t:"text"},{k:"matrix.user_id",l:"User ID",t:"text"},{k:"matrix.password",l:"Password",t:"password"}]},
  {id:"irc",name:"IRC",icon:"&#128225;",fields:[{k:"irc.server",l:"Server",t:"text"},{k:"irc.port",l:"Port",t:"text"},{k:"irc.nick",l:"Nickname",t:"text"},{k:"irc.channel",l:"Channel",t:"text"}]},
];

let cfg={},logs=[],logTimer=null,curProvider=null,curChannel=null;

async function init(){
  try{cfg=await apiFetch("/api/config");}catch(e){cfg={};}
  renderProviders();renderChannels();loadMemory();loadSkills();renderMCP();
  pollStatus();setInterval(pollStatus,8000);
}

async function apiFetch(url,opts={}){
  const r=await fetch(url,opts);
  if(!r.ok)throw new Error(r.status);
  return r.json();
}

async function pollStatus(){
  try{
    const s=await apiFetch("/api/status");
    const b=document.getElementById("status-badge");
    if(s.running){b.textContent="Running";b.className="running";}
    else{b.textContent="Stopped";b.className="stopped";}
  }catch(e){}
}

function show(id,btn){
  document.querySelectorAll(".panel").forEach(p=>p.classList.remove("active"));
  document.querySelectorAll("nav button").forEach(b=>b.classList.remove("active"));
  document.getElementById("panel-"+id).classList.add("active");
  btn.classList.add("active");
  if(id==="logs")loadLogs();
  if(id==="skills")loadSkills();
  if(id==="memory")loadMemory();
  if(id==="mcp")renderMCP();
}

function getV(path){const p=path.split(".");let o=cfg;for(const k of p){if(!o||o[k]===undefined)return "";o=o[k];}return o||""}
function setV(path,val){const p=path.split(".");let o=cfg;for(let i=0;i<p.length-1;i++){if(!o[p[i]])o[p[i]]={};o=o[p[i]];}o[p[p.length-1]]=val;}

function renderProviders(){
  const g=document.getElementById("providers-grid");g.innerHTML="";
  PROVIDERS.forEach(pr=>{
    const configured=pr.fields.some(f=>getV(f.k));
    const d=document.createElement("div");
    d.className="tile"+(configured?" configured":"");
    d.innerHTML=`<div class="tile-icon">${pr.icon}</div><div class="tile-name">${pr.name}</div><div class="tile-sub">${configured?"Configured":"Not set"}</div>`;
    d.onclick=()=>openProvider(pr);
    g.appendChild(d);
  });
}

function renderChannels(){
  const g=document.getElementById("channels-grid");g.innerHTML="";
  CHANNELS.forEach(ch=>{
    const configured=ch.fields.some(f=>getV(f.k));
    const d=document.createElement("div");
    d.className="tile"+(configured?" configured":"");
    d.innerHTML=`<div class="tile-icon">${ch.icon}</div><div class="tile-name">${ch.name}</div><div class="tile-sub">${configured?"Configured":"Not set"}</div>`;
    d.onclick=()=>openChannel(ch);
    g.appendChild(d);
  });
}

function openProvider(pr){
  curProvider=pr;
  document.getElementById("pm-title").textContent="Configure "+pr.name;
  const body=document.getElementById("pm-body");body.innerHTML="";
  pr.fields.forEach(f=>{
    body.innerHTML+=`<div class="form-row"><label>${f.l}</label><input id="pf-${f.k.replace(/\./g,'-')}" type="${f.t}" value="${getV(f.k)}" placeholder="${f.l}"/></div>`;
  });
  document.getElementById("provider-modal").classList.add("open");
}

async function saveProvider(){
  if(!curProvider)return;
  curProvider.fields.forEach(f=>{const v=document.getElementById("pf-"+f.k.replace(/\./g,"-"))?.value||"";if(v)setV(f.k,v);});
  await apiFetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(cfg)});
  closeModal("provider-modal");renderProviders();
}

function openChannel(ch){
  curChannel=ch;
  document.getElementById("cm-title").textContent="Configure "+ch.name;
  const body=document.getElementById("cm-body");body.innerHTML="";
  ch.fields.forEach(f=>{
    body.innerHTML+=`<div class="form-row"><label>${f.l}</label><input id="cf-${f.k.replace(/\./g,'-')}" type="${f.t}" value="${getV(f.k)}" placeholder="${f.l}"/></div>`;
  });
  document.getElementById("channel-modal").classList.add("open");
}

async function saveChannel(){
  if(!curChannel)return;
  curChannel.fields.forEach(f=>{const v=document.getElementById("cf-"+f.k.replace(/\./g,"-"))?.value||"";if(v)setV(f.k,v);});
  await apiFetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(cfg)});
  closeModal("channel-modal");renderChannels();
}

function closeModal(id){document.getElementById(id).classList.remove("open");}

async function gw(action){
  try{await apiFetch("/api/gateway/"+action,{method:"POST"});await pollStatus();}
  catch(e){alert("Error: "+e.message);}
}

async function loadLogs(){
  try{const r=await apiFetch("/api/logs");logs=r.lines||[];renderLogs();}catch(e){}
}
function renderLogs(){
  const f=document.getElementById("log-filter").value.toLowerCase();
  const box=document.getElementById("log-box");
  box.textContent=(f?logs.filter(l=>l.toLowerCase().includes(f)):logs).join("\n")||"(no logs)";
  box.scrollTop=box.scrollHeight;
}
function clearLogs(){logs=[];renderLogs();}
function toggleAuto(){
  const on=document.getElementById("log-auto").checked;
  if(on){loadLogs();logTimer=setInterval(loadLogs,3000);}
  else if(logTimer){clearInterval(logTimer);logTimer=null;}
}

async function loadSkills(){
  try{
    const r=await apiFetch("/api/skills");
    const el=document.getElementById("skills-list");el.innerHTML="";
    (r.skills||[]).forEach(s=>{
      const d=document.createElement("div");d.className="skill-item";
      d.innerHTML=`<span style="font-size:0.85rem">&#128196; ${s.name}.md <small style="color:#6b7280">${s.size}b</small></span>
        <div style="display:flex;gap:6px">
          <button class="btn btn-ghost btn-sm" onclick="editSkill('${s.name}')">Edit</button>
          <button class="btn btn-danger btn-sm" onclick="deleteSkill('${s.name}')">Delete</button>
        </div>`;
      el.appendChild(d);
    });
  }catch(e){}
}

function newSkill(){document.getElementById("skill-name").value="";document.getElementById("skill-content").value="";document.getElementById("skill-editor").style.display="block";}

async function editSkill(name){
  try{
    const r=await apiFetch("/api/skills/"+name);
    document.getElementById("skill-name").value=r.name;
    document.getElementById("skill-content").value=r.content;
    document.getElementById("skill-editor").style.display="block";
  }catch(e){}
}

async function saveSkill(){
  const name=document.getElementById("skill-name").value.trim();
  const content=document.getElementById("skill-content").value;
  if(!name)return alert("Enter a skill name");
  await apiFetch("/api/skills/"+name,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({content})});
  document.getElementById("skill-editor").style.display="none";loadSkills();
}

async function deleteSkill(name){
  if(!confirm("Delete "+name+"?"))return;
  await apiFetch("/api/skills/"+name,{method:"DELETE"});loadSkills();
}

function cancelSkill(){document.getElementById("skill-editor").style.display="none";}

async function loadMemory(){
  try{const r=await apiFetch("/api/memory");document.getElementById("memory-content").value=r.content||"";}catch(e){}
}

async function saveMemory(){
  const content=document.getElementById("memory-content").value;
  await apiFetch("/api/memory",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({content})});
  alert("Memory saved!");
}

function renderMCP(){
  const mcps=cfg.mcp||{};
  const el=document.getElementById("mcp-list");if(!el)return;el.innerHTML="";
  Object.entries(mcps).forEach(([name,v])=>{
    const d=document.createElement("div");d.className="mcp-item";
    d.innerHTML=`<span>&#128268; <b>${name}</b> <small style="color:#6b7280">${v.type||"sse"} &mdash; ${v.url||v.command||""}</small></span>
      <button class="btn btn-danger btn-sm" onclick="deleteMCP('${name}')">Remove</button>`;
    el.appendChild(d);
  });
}

function openMCP(){document.getElementById("mcp-modal").classList.add("open");}
function toggleMCPType(){
  const t=document.getElementById("mcp-type").value;
  document.getElementById("mcp-sse-fields").style.display=t==="sse"?"block":"none";
  document.getElementById("mcp-stdio-fields").style.display=t==="stdio"?"block":"none";
}

async function saveMCP(){
  const name=document.getElementById("mcp-name").value.trim();
  const type=document.getElementById("mcp-type").value;
  if(!name)return;
  if(!cfg.mcp)cfg.mcp={};
  if(type==="sse"){
    cfg.mcp[name]={type:"sse",url:document.getElementById("mcp-url").value};
  }else{
    const args=document.getElementById("mcp-args").value.split(",").map(s=>s.trim()).filter(Boolean);
    cfg.mcp[name]={type:"stdio",command:document.getElementById("mcp-cmd").value,args,cwd:document.getElementById("mcp-cwd").value};
  }
  await apiFetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(cfg)});
  closeModal("mcp-modal");renderMCP();
}

async function deleteMCP(name){
  if(!confirm("Remove "+name+"?"))return;
  if(cfg.mcp)delete cfg.mcp[name];
  await apiFetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(cfg)});
  renderMCP();
}

init();
</script>
</body>
</html>"""