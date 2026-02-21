"""NanoBot Web UI - Enhanced FastAPI + Single-Page App"""
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
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

gateway_process = None
gateway_lock = threading.Lock()
WEBUI_PASSWORD = os.environ.get("WEBUI_PASSWORD", "")


def check_auth(credentials=Depends(security)):
    if not WEBUI_PASSWORD:
        return True
    if credentials is None:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
    if not secrets.compare_digest(credentials.password.encode(), WEBUI_PASSWORD.encode()):
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
                stdout=log_f, stderr=subprocess.STDOUT,
                cwd=str(NANOBOT_DIR),
            )
        except Exception as e:
            print(f"Failed to start gateway: {e}")


def is_gateway_running():
    return gateway_process is not None and gateway_process.poll() is None


def read_config():
    NANOBOT_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {}


def write_config(data):
    NANOBOT_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


@app.on_event("startup")
async def startup():
    start_gateway()


@app.get("/api/status")
async def get_status(_=Depends(check_auth)):
    return {"ok": True, "gateway_running": is_gateway_running()}


@app.get("/api/config")
async def get_config(_=Depends(check_auth)):
    return read_config()


@app.post("/api/config")
async def save_config(request: Request, _=Depends(check_auth)):
    write_config(await request.json())
    return {"ok": True}


@app.post("/api/gateway/{action}")
async def gateway_action(action: str, _=Depends(check_auth)):
    global gateway_process
    if action == "stop" or action == "restart":
        with gateway_lock:
            if gateway_process:
                gateway_process.terminate()
                try:
                    gateway_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    gateway_process.kill()
                gateway_process = None
    if action == "start" or action == "restart":
        await asyncio.sleep(0.5)
        start_gateway()
        await asyncio.sleep(1)
    return {"ok": True, "running": is_gateway_running()}


@app.get("/api/logs")
async def get_logs(_=Depends(check_auth)):
    if not LOG_FILE.exists():
        return {"lines": []}
    return {"lines": LOG_FILE.read_text().split("\n")[-500:]}


@app.delete("/api/logs")
async def clear_logs(_=Depends(check_auth)):
    if LOG_FILE.exists():
        LOG_FILE.write_text("")
    return {"ok": True}


@app.get("/api/memory")
async def get_memory(_=Depends(check_auth)):
    return {"content": MEMORY_FILE.read_text() if MEMORY_FILE.exists() else ""}


@app.post("/api/memory")
async def save_memory(request: Request, _=Depends(check_auth)):
    data = await request.json()
    NANOBOT_DIR.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(data.get("content", ""))
    return {"ok": True}


@app.get("/api/skills")
async def list_skills(_=Depends(check_auth)):
    if not SKILLS_DIR.exists():
        return {"skills": []}
    return {"skills": [{"name": f.stem} for f in sorted(SKILLS_DIR.glob("*.md"))]}


@app.get("/api/skills/{name}")
async def get_skill(name: str, _=Depends(check_auth)):
    p = SKILLS_DIR / f"{name}.md"
    if not p.exists():
        raise HTTPException(404)
    return {"name": name, "content": p.read_text()}


@app.post("/api/skills/{name}")
async def save_skill(name: str, request: Request, _=Depends(check_auth)):
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    (SKILLS_DIR / f"{name}.md").write_text((await request.json()).get("content", ""))
    return {"ok": True}


@app.delete("/api/skills/{name}")
async def delete_skill(name: str, _=Depends(check_auth)):
    p = SKILLS_DIR / f"{name}.md"
    if p.exists():
        p.unlink()
    return {"ok": True}


HTML = open(__file__.replace("main.py", "ui.html")).read() if False else r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NanoBot Control Panel</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:linear-gradient(135deg,#1a1a2e,#16213e,#0f3460);min-height:100vh;padding:20px}
.container{max-width:1100px;margin:0 auto;background:#fff;border-radius:16px;box-shadow:0 25px 80px rgba(0,0,0,.5);overflow:hidden}
.header{background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;padding:26px 30px}
.header h1{font-size:1.8em;font-weight:700}
.header p{opacity:.8;margin-top:4px;font-size:.92em}
.tabs{display:flex;background:#f1f3f5;border-bottom:2px solid #dee2e6;overflow-x:auto}
.tab{flex:none;padding:13px 20px;background:none;border:none;cursor:pointer;font-size:.88em;font-weight:600;color:#6c757d;border-bottom:3px solid transparent;white-space:nowrap;transition:all .2s}
.tab:hover{background:#e9ecef;color:#495057}
.tab.active{background:#fff;color:#667eea;border-bottom-color:#667eea}
.content{padding:26px}
.pane{display:none}.pane.active{display:block}
.sec{font-size:1.05em;font-weight:700;color:#1e293b;margin-bottom:16px;padding-bottom:8px;border-bottom:2px solid #e5e7eb}
.card{background:#f8f9fa;border:1px solid #e9ecef;border-radius:10px;padding:18px;margin-bottom:16px}
.dot{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:8px}
.dot.on{background:#10b981;box-shadow:0 0 8px #10b981}.dot.off{background:#ef4444;box-shadow:0 0 8px #ef4444}
.brow{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.btn{padding:9px 18px;border:none;border-radius:7px;cursor:pointer;font-size:.87em;font-weight:600;transition:all .2s}
.btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(0,0,0,.15)}
.bp{background:#667eea;color:#fff}.bd{background:#ef4444;color:#fff}.bs{background:#10b981;color:#fff}.bw{background:#f59e0b;color:#fff}.bg{background:#6c757d;color:#fff}
.btn-sm{padding:5px 11px;font-size:.79em}
.pgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px;margin-bottom:14px}
.pc{padding:13px;border:2px solid #e5e7eb;border-radius:10px;cursor:pointer;transition:all .2s;background:#fff}
.pc:hover,.pc.active{border-color:#667eea;background:#f5f3ff}
.pc .pn{font-weight:700;font-size:.88em;color:#1e293b}
.pc .pd{font-size:.76em;color:#6b7280;margin-top:3px}
.pform{background:#f8f9fa;border:1px solid #e5e7eb;border-radius:10px;padding:18px;margin-top:14px;display:none}
.pform.show{display:block}
.cgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px;margin-bottom:14px}
.cc{padding:12px 14px;border:2px solid #e5e7eb;border-radius:10px;cursor:pointer;display:flex;align-items:center;gap:10px;transition:all .2s;background:#fff}
.cc:hover,.cc.active{border-color:#667eea;background:#f5f3ff}
.cc .ci{font-size:1.3em}.cc .cn{font-weight:600;font-size:.87em;color:#1e293b}
.cform{background:#f8f9fa;border:1px solid #e5e7eb;border-radius:10px;padding:18px;margin-top:12px;display:none}
.cform.show{display:block}
.fg{margin-bottom:13px}
.fg label{display:block;margin-bottom:5px;font-weight:600;font-size:.83em;color:#374151}
.fg input,.fg select,.fg textarea{width:100%;padding:9px 11px;border:2px solid #e5e7eb;border-radius:7px;font-size:.88em;transition:border-color .2s;background:#fff}
.fg input:focus,.fg select:focus,.fg textarea:focus{outline:none;border-color:#667eea}
.fg textarea{font-family:monospace;min-height:140px;resize:vertical}
.sgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px;margin-bottom:14px}
.sk{padding:13px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border-radius:10px;cursor:pointer;transition:transform .2s,box-shadow .2s;font-weight:700;font-size:.88em}
.sk:hover{transform:translateY(-3px);box-shadow:0 8px 20px rgba(102,126,234,.4)}
.seditor{margin-top:14px;display:none}.seditor.show{display:block}
.log-bar{display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap}
.log-search{flex:1;min-width:160px;padding:7px 11px;border:2px solid #e5e7eb;border-radius:7px;font-size:.86em}
.log-search:focus{outline:none;border-color:#667eea}
.logbox{background:#0f172a;color:#e2e8f0;padding:14px;border-radius:8px;font-family:monospace;font-size:.81em;max-height:540px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;line-height:1.5}
.mitem{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px 14px;margin-bottom:8px;display:flex;justify-content:space-between;align-items:center}
.mn{font-weight:700;font-size:.88em;color:#1e293b}.mu{font-size:.76em;color:#6b7280;margin-top:2px}
.toast{position:fixed;top:18px;right:18px;padding:11px 18px;background:#1e293b;color:#fff;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,.25);opacity:0;transform:translateX(110%);transition:all .3s;z-index:9999;font-size:.88em;max-width:300px}
.toast.show{opacity:1;transform:translateX(0)}.tok{border-left:4px solid #10b981}.terr{border-left:4px solid #ef4444}
</style>
</head>
<body>
<div class="container">
 <div class="header">
  <h1>&#x1F916; NanoBot Control Panel</h1>
  <p>AI agent gateway &mdash; providers, channels, skills, memory, MCP</p>
 </div>
 <div class="tabs">
  <button class="tab active" onclick="go('status')">&#x2665; Status</button>
  <button class="tab" onclick="go('providers')">&#x26A1; Providers</button>
  <button class="tab" onclick="go('channels')">&#x1F4AC; Channels</button>
  <button class="tab" onclick="go('skills')">&#x1F9E0; Skills</button>
  <button class="tab" onclick="go('memory')">&#x1F4DA; Memory</button>
  <button class="tab" onclick="go('mcp')">&#x1F527; MCP</button>
  <button class="tab" onclick="go('logs')">&#x1F4CB; Logs</button>
 </div>
 <div class="content">
  <!-- STATUS -->
  <div id="p-status" class="pane active">
   <div class="sec">Gateway Status</div>
   <div class="card">
    <div><span class="dot off" id="gw-dot"></span><span id="gw-txt">Checking...</span></div>
    <div class="brow">
     <button class="btn bs" onclick="gwAct('start')">&#x25B6; Start</button>
     <button class="btn bd" onclick="gwAct('stop')">&#x25A0; Stop</button>
     <button class="btn bw" onclick="gwAct('restart')">&#x21BA; Restart</button>
     <button class="btn bg" onclick="loadStatus()">&#x21BA; Refresh</button>
    </div>
   </div>
  </div>
  <!-- PROVIDERS -->
  <div id="p-providers" class="pane">
   <div class="sec">AI Provider</div>
   <div class="pgrid" id="pgrid"></div>
   <div class="pform" id="pform">
    <div id="pf-title" style="font-weight:700;font-size:1em;margin-bottom:12px;color:#1e293b"></div>
    <div id="pf-fields"></div>
    <div class="brow">
     <button class="btn bs" onclick="saveProvider()">Save</button>
     <button class="btn bg" onclick="closeProvider()">Cancel</button>
    </div>
   </div>
  </div>
  <!-- CHANNELS -->
  <div id="p-channels" class="pane">
   <div class="sec">Messaging Channels</div>
   <div class="cgrid" id="cgrid"></div>
   <div class="cform" id="cform">
    <div id="cf-title" style="font-weight:700;font-size:1em;margin-bottom:12px;color:#1e293b"></div>
    <div id="cf-fields"></div>
    <div class="brow">
     <button class="btn bs" onclick="saveCh()">Save</button>
     <button class="btn bg" onclick="closeCh()">Cancel</button>
    </div>
   </div>
  </div>
  <!-- SKILLS -->
  <div id="p-skills" class="pane">
   <div class="sec">Skills (SKILL.md files)</div>
   <div class="brow" style="margin-bottom:12px">
    <button class="btn bs" onclick="newSkill()">+ New Skill</button>
    <button class="btn bg" onclick="loadSkills()">&#x21BA; Refresh</button>
   </div>
   <div class="sgrid" id="sgrid"></div>
   <div class="seditor" id="seditor">
    <div class="fg"><label>Skill Name</label><input type="text" id="sk-name" placeholder="my_skill"></div>
    <div class="fg"><label>Content (Markdown)</label><textarea id="sk-content" style="min-height:260px" placeholder="# My Skill&#10;&#10;Describe the skill..."></textarea></div>
    <div class="brow">
     <button class="btn bs" onclick="saveSkill()">Save</button>
     <button class="btn bd" onclick="delSkill()">Delete</button>
     <button class="btn bg" onclick="closeSk()">Cancel</button>
    </div>
   </div>
  </div>
  <!-- MEMORY -->
  <div id="p-memory" class="pane">
   <div class="sec">Agent Memory</div>
   <div class="fg"><label>memory.md</label><textarea id="mem" style="min-height:360px" placeholder="# Memory&#10;&#10;Agent memory in markdown..."></textarea></div>
   <div class="brow">
    <button class="btn bs" onclick="saveMem()">Save Memory</button>
    <button class="btn bg" onclick="loadMemory()">&#x21BA; Refresh</button>
   </div>
  </div>
  <!-- MCP -->
  <div id="p-mcp" class="pane">
   <div class="sec">MCP Servers</div>
   <div id="mlist"></div>
   <div class="card" style="margin-top:14px">
    <div style="font-weight:700;margin-bottom:12px;font-size:.95em">Add MCP Server</div>
    <div class="fg"><label>Name</label><input type="text" id="mcp-name" placeholder="my-server"></div>
    <div class="fg"><label>Type</label>
     <select id="mcp-type" onchange="mcpType()">
      <option value="sse">SSE (HTTP)</option>
      <option value="stdio">Stdio (local process)</option>
     </select>
    </div>
    <div id="mcp-sse">
     <div class="fg"><label>URL</label><input type="text" id="mcp-url" placeholder="http://localhost:8080/sse"></div>
    </div>
    <div id="mcp-stdio" style="display:none">
     <div class="fg"><label>Command</label><input type="text" id="mcp-cmd" placeholder="node"></div>
     <div class="fg"><label>Arguments (space-separated)</label><input type="text" id="mcp-args" placeholder="/path/to/server.js arg1"></div>
     <div class="fg"><label>Working Directory</label><input type="text" id="mcp-cwd" placeholder="/home/user/project"></div>
    </div>
    <div class="brow"><button class="btn bs" onclick="addMcp()">Add Server</button></div>
   </div>
  </div>
  <!-- LOGS -->
  <div id="p-logs" class="pane">
   <div class="sec">Gateway Logs</div>
   <div class="log-bar">
    <input class="log-search" id="log-q" placeholder="Filter logs..." oninput="filterLogs()">
    <button class="btn bp btn-sm" onclick="loadLogs()">&#x21BA; Refresh</button>
    <button class="btn bd btn-sm" onclick="clearLogs()">Clear</button>
    <label style="display:flex;align-items:center;gap:5px;font-size:.84em;font-weight:600;cursor:pointer">
     <input type="checkbox" id="auto-ref" onchange="autoRef()"> Auto
    </label>
   </div>
   <div class="logbox" id="logbox">Loading...</div>
  </div>
 </div>
</div>
<div class="toast" id="toast"></div>
<script>
// Toast
function toast(m,t='ok'){const el=document.getElementById('toast');el.textContent=m;el.className='toast show '+(t==='ok'?'tok':'terr');clearTimeout(el._t);el._t=setTimeout(()=>el.classList.remove('show'),3000);}

// Tab navigation
const TABS=['status','providers','channels','skills','memory','mcp','logs'];
const LOADERS={status:loadStatus,providers:loadProviders,channels:loadChannels,skills:loadSkills,memory:loadMemory,mcp:loadMcp,logs:loadLogs};
function go(id){
  document.querySelectorAll('.tab').forEach((t,i)=>{t.classList.toggle('active',TABS[i]===id);});
  TABS.forEach(t=>document.getElementById('p-'+t).classList.toggle('active',t===id));
  if(LOADERS[id])LOADERS[id]();
}

// Status
async function loadStatus(){
  try{const d=await fetch('/api/status').then(r=>r.json());
   document.getElementById('gw-dot').className='dot '+(d.gateway_running?'on':'off');
   document.getElementById('gw-txt').textContent='Gateway '+(d.gateway_running?'RUNNING':'STOPPED');
  }catch(e){toast('Status error','err');}
}
async function gwAct(a){
  try{await fetch('/api/gateway/'+a,{method:'POST'});toast(a+' OK');setTimeout(loadStatus,1200);}
  catch(e){toast('Failed','err');}
}

// Config cache
let _cfg=null;
async function getCfg(){if(!_cfg)_cfg=await fetch('/api/config').then(r=>r.json()).catch(()=>({}));return _cfg;}
async function patchCfg(patch){
  const cfg=await getCfg();
  for(const k of Object.keys(patch)){
    if(typeof patch[k]==='object'&&!Array.isArray(patch[k])&&patch[k]!==null)cfg[k]={...(cfg[k]||{}),...patch[k]};
    else cfg[k]=patch[k];
  }
  _cfg=cfg;
  await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
}

// Providers
const PROVIDERS=[
 {id:'openrouter',name:'OpenRouter',desc:'200+ models unified',fields:[{k:'openrouter_api_key',l:'API Key',t:'password',p:'sk-or-...'},{k:'openrouter_model',l:'Model',t:'text',p:'openai/gpt-4o'}]},
 {id:'openai',name:'OpenAI',desc:'GPT-4o, o1, o3',fields:[{k:'openai_api_key',l:'API Key',t:'password',p:'sk-...'},{k:'openai_model',l:'Model',t:'text',p:'gpt-4o'},{k:'openai_base_url',l:'Base URL',t:'text',p:'https://api.openai.com/v1'}]},
 {id:'anthropic',name:'Anthropic',desc:'Claude 3.5 Sonnet',fields:[{k:'anthropic_api_key',l:'API Key',t:'password',p:'sk-ant-...'},{k:'anthropic_model',l:'Model',t:'text',p:'claude-3-5-sonnet-20241022'}]},
 {id:'gemini',name:'Google Gemini',desc:'Gemini 2.0 Flash',fields:[{k:'gemini_api_key',l:'API Key',t:'password',p:'AIza...'},{k:'gemini_model',l:'Model',t:'text',p:'gemini-2.0-flash-exp'}]},
 {id:'deepseek',name:'DeepSeek',desc:'DeepSeek-V3, R1',fields:[{k:'deepseek_api_key',l:'API Key',t:'password',p:'sk-...'},{k:'deepseek_model',l:'Model',t:'text',p:'deepseek-chat'}]},
 {id:'groq',name:'Groq',desc:'LLaMA ultra-fast',fields:[{k:'groq_api_key',l:'API Key',t:'password',p:'gsk_...'},{k:'groq_model',l:'Model',t:'text',p:'llama-3.3-70b-versatile'}]},
 {id:'moonshot',name:'Moonshot',desc:'Kimi long-context',fields:[{k:'moonshot_api_key',l:'API Key',t:'password',p:'...'},{k:'moonshot_model',l:'Model',t:'text',p:'moonshot-v1-128k'}]},
 {id:'zhipu',name:'Zhipu AI',desc:'GLM-4 series',fields:[{k:'zhipu_api_key',l:'API Key',t:'password',p:'...'},{k:'zhipu_model',l:'Model',t:'text',p:'glm-4'}]},
 {id:'dashscope',name:'DashScope',desc:'Alibaba Qwen',fields:[{k:'dashscope_api_key',l:'API Key',t:'password',p:'sk-...'},{k:'dashscope_model',l:'Model',t:'text',p:'qwen-max'}]},
 {id:'aihubmix',name:'AiHubMix',desc:'Multi-model hub',fields:[{k:'aihubmix_api_key',l:'API Key',t:'password',p:'...'},{k:'aihubmix_model',l:'Model',t:'text',p:'gpt-4o'}]},
 {id:'nvidia',name:'NVIDIA NIM',desc:'NVIDIA cloud AI',fields:[{k:'nvidia_api_key',l:'API Key',t:'password',p:'nvapi-...'},{k:'nvidia_model',l:'Model',t:'text',p:'meta/llama-3.1-70b-instruct'}]},
 {id:'vllm',name:'vLLM (Local)',desc:'Self-hosted vLLM',fields:[{k:'vllm_base_url',l:'Base URL',t:'text',p:'http://localhost:8000/v1'},{k:'vllm_model',l:'Model',t:'text',p:'Qwen/Qwen2.5-7B'},{k:'vllm_api_key',l:'API Key',t:'password',p:'token'}]},
];
let _ap=null;
async function loadProviders(){
  const cfg=await getCfg();
  document.getElementById('pgrid').innerHTML=PROVIDERS.map(p=>`
   <div class="pc" id="pc-${p.id}" onclick="openP('${p.id}')">
    <div class="pn">${p.name}</div><div class="pd">${p.desc}</div>
   </div>`).join('');
  for(const p of PROVIDERS)if(p.fields.some(f=>cfg[f.k])){const el=document.getElementById('pc-'+p.id);if(el)el.style.borderColor='#10b981';}
}
async function openP(id){
  const p=PROVIDERS.find(x=>x.id===id);if(!p)return;_ap=id;
  document.querySelectorAll('.pc').forEach(c=>c.classList.remove('active'));
  document.getElementById('pc-'+id)?.classList.add('active');
  document.getElementById('pf-title').textContent=p.name+' Settings';
  const cfg=await getCfg();
  document.getElementById('pf-fields').innerHTML=p.fields.map(f=>`<div class="fg"><label>${f.l}</label><input type="${f.t}" id="pf-${f.k}" placeholder="${f.p}" value="${cfg[f.k]||''}"></div>`).join('');
  const pf=document.getElementById('pform');pf.classList.add('show');pf.scrollIntoView({behavior:'smooth',block:'nearest'});
}
async function saveProvider(){
  const p=PROVIDERS.find(x=>x.id===_ap);if(!p)return;
  const patch={};
  for(const f of p.fields){const v=document.getElementById('pf-'+f.k)?.value||'';if(v)patch[f.k]=v;}
  await patchCfg(patch);toast('Provider saved');closeProvider();loadProviders();
}
function closeProvider(){document.getElementById('pform').classList.remove('show');document.querySelectorAll('.pc').forEach(c=>c.classList.remove('active'));_ap=null;}

// Channels
const CHANNELS=[
 {id:'telegram',icon:'&#x2708;',name:'Telegram',fields:[{k:'telegram_token',l:'Bot Token',t:'password',p:'123456:ABC...'}]},
 {id:'discord',icon:'&#x1F3AE;',name:'Discord',fields:[{k:'discord_token',l:'Bot Token',t:'password',p:'MTk...'}]},
 {id:'slack',icon:'&#x1F527;',name:'Slack',fields:[{k:'slack_bot_token',l:'Bot Token',t:'password',p:'xoxb-...'},{k:'slack_app_token',l:'App Token',t:'password',p:'xapp-...'}]},
 {id:'whatsapp',icon:'&#x1F4F1;',name:'WhatsApp',fields:[{k:'whatsapp_phone_id',l:'Phone Number ID',t:'text',p:'123456789'},{k:'whatsapp_token',l:'Access Token',t:'password',p:'EAABs...'},{k:'whatsapp_verify_token',l:'Verify Token',t:'text',p:'my_token'}]},
 {id:'lark',icon:'&#x1F985;',name:'Lark/Feishu',fields:[{k:'lark_app_id',l:'App ID',t:'text',p:'cli_...'},{k:'lark_app_secret',l:'App Secret',t:'password',p:'...'}]},
 {id:'dingtalk',icon:'&#x1F514;',name:'DingTalk',fields:[{k:'dingtalk_access_token',l:'Access Token',t:'password',p:'...'},{k:'dingtalk_secret',l:'Secret',t:'password',p:'...'}]},
 {id:'wechat',icon:'&#x1F4AC;',name:'WeChat Work',fields:[{k:'wechat_corp_id',l:'Corp ID',t:'text',p:'wx...'},{k:'wechat_agent_id',l:'Agent ID',t:'text',p:'1000001'},{k:'wechat_secret',l:'Secret',t:'password',p:'...'}]},
 {id:'matrix',icon:'&#x1F310;',name:'Matrix',fields:[{k:'matrix_homeserver',l:'Homeserver',t:'text',p:'https://matrix.org'},{k:'matrix_user',l:'User ID',t:'text',p:'@bot:matrix.org'},{k:'matrix_password',l:'Password',t:'password',p:'...'},{k:'matrix_access_token',l:'Access Token',t:'password',p:'syt_...'}]},
 {id:'irc',icon:'&#x1F4BB;',name:'IRC',fields:[{k:'irc_server',l:'Server',t:'text',p:'irc.libera.chat'},{k:'irc_port',l:'Port',t:'text',p:'6697'},{k:'irc_nick',l:'Nick',t:'text',p:'mynanobot'},{k:'irc_channel',l:'Channel',t:'text',p:'#mychan'},{k:'irc_password',l:'Password',t:'password',p:'...'}]},
];
let _ac=null;
async function loadChannels(){
  const cfg=await getCfg();
  document.getElementById('cgrid').innerHTML=CHANNELS.map(c=>`
   <div class="cc" id="cc-${c.id}" onclick="openCh('${c.id}')">
    <span class="ci">${c.icon}</span><span class="cn">${c.name}</span>
   </div>`).join('');
  for(const c of CHANNELS)if(c.fields.some(f=>cfg[f.k])){const el=document.getElementById('cc-'+c.id);if(el)el.style.borderColor='#10b981';}
}
async function openCh(id){
  const c=CHANNELS.find(x=>x.id===id);if(!c)return;_ac=id;
  document.querySelectorAll('.cc').forEach(e=>e.classList.remove('active'));
  document.getElementById('cc-'+id)?.classList.add('active');
  document.getElementById('cf-title').textContent=c.name+' Configuration';
  const cfg=await getCfg();
  document.getElementById('cf-fields').innerHTML=c.fields.map(f=>`<div class="fg"><label>${f.l}</label><input type="${f.t}" id="cf-${f.k}" placeholder="${f.p}" value="${cfg[f.k]||''}"></div>`).join('');
  const cf=document.getElementById('cform');cf.classList.add('show');cf.scrollIntoView({behavior:'smooth',block:'nearest'});
}
async function saveCh(){
  const c=CHANNELS.find(x=>x.id===_ac);if(!c)return;
  const patch={};
  for(const f of c.fields){const v=document.getElementById('cf-'+f.k)?.value||'';if(v)patch[f.k]=v;}
  await patchCfg(patch);toast('Channel saved');closeCh();loadChannels();
}
function closeCh(){document.getElementById('cform').classList.remove('show');document.querySelectorAll('.cc').forEach(e=>e.classList.remove('active'));_ac=null;}

// Skills
let _editSk=null;
async function loadSkills(){
  const r=await fetch('/api/skills').then(x=>x.json()).catch(()=>({skills:[]}));
  const g=document.getElementById('sgrid');
  g.innerHTML=r.skills.length?r.skills.map(s=>`<div class="sk" onclick="editSk('${s.name}')">&#x1F4C4; ${s.name}</div>`).join(''):'<em style="color:#9ca3af">No skills yet</em>';
}
function newSkill(){_editSk=null;document.getElementById('sk-name').value='';document.getElementById('sk-content').value='';const e=document.getElementById('seditor');e.classList.add('show');e.scrollIntoView({behavior:'smooth',block:'nearest'});}
async function editSk(name){
  const r=await fetch('/api/skills/'+name).then(x=>x.json()).catch(()=>null);
  if(!r)return toast('Load failed','err');
  _editSk=name;document.getElementById('sk-name').value=name;document.getElementById('sk-content').value=r.content;
  const e=document.getElementById('seditor');e.classList.add('show');e.scrollIntoView({behavior:'smooth',block:'nearest'});
}
async function saveSkill(){
  const name=document.getElementById('sk-name').value.trim();
  if(!name)return toast('Name required','err');
  await fetch('/api/skills/'+name,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:document.getElementById('sk-content').value})});
  toast('Skill saved');closeSk();loadSkills();
}
async function delSkill(){
  const name=document.getElementById('sk-name').value.trim();
  if(!name||!confirm('Delete "'+name+'"?'))return;
  await fetch('/api/skills/'+name,{method:'DELETE'});
  toast('Deleted');closeSk();loadSkills();
}
function closeSk(){document.getElementById('seditor').classList.remove('show');}

// Memory
async function loadMemory(){const r=await fetch('/api/memory').then(x=>x.json()).catch(()=>({content:''}));document.getElementById('mem').value=r.content;}
async function saveMem(){await fetch('/api/memory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:document.getElementById('mem').value})});toast('Memory saved');}

// MCP
async function loadMcp(){
  const cfg=await getCfg();const servers=cfg.mcp_servers||[];
  document.getElementById('mlist').innerHTML=servers.length?servers.map((s,i)=>`
   <div class="mitem">
    <div><div class="mn">${s.name||'Server'+i}</div><div class="mu">${s.type==='sse'?(s.url||''):(s.command||'')+(s.args?' '+s.args.join(' '):'')}</div></div>
    <button class="btn bd btn-sm" onclick="rmMcp(${i})">Remove</button>
   </div>`).join(''):'<div style="color:#9ca3af;font-size:.88em;padding:4px">No MCP servers configured</div>';
}
function mcpType(){const t=document.getElementById('mcp-type').value;document.getElementById('mcp-sse').style.display=t==='sse'?'block':'none';document.getElementById('mcp-stdio').style.display=t==='stdio'?'block':'none';}
async function addMcp(){
  const name=document.getElementById('mcp-name').value.trim();
  const type=document.getElementById('mcp-type').value;
  if(!name)return toast('Name required','err');
  const s={name,type};
  if(type==='sse'){const url=document.getElementById('mcp-url').value.trim();if(!url)return toast('URL required','err');s.url=url;}
  else{const cmd=document.getElementById('mcp-cmd').value.trim();if(!cmd)return toast('Command required','err');s.command=cmd;const a=document.getElementById('mcp-args').value.trim();if(a)s.args=a.split(' ').filter(Boolean);const c=document.getElementById('mcp-cwd').value.trim();if(c)s.cwd=c;}
  const cfg=await getCfg();await patchCfg({mcp_servers:[...(cfg.mcp_servers||[]),s]});
  ['mcp-name','mcp-url','mcp-cmd','mcp-args','mcp-cwd'].forEach(id=>{const el=document.getElementById(id);if(el)el.value='';});
  toast('MCP server added');loadMcp();
}
async function rmMcp(i){const cfg=await getCfg();await patchCfg({mcp_servers:(cfg.mcp_servers||[]).filter((_,j)=>j!==i)});toast('Removed');loadMcp();}

// Logs
let _lines=[];let _aTimer=null;
async function loadLogs(){const r=await fetch('/api/logs').then(x=>x.json()).catch(()=>({lines:[]}));_lines=r.lines||[];filterLogs();}
function filterLogs(){const q=(document.getElementById('log-q').value||'').toLowerCase();const l=q?_lines.filter(x=>x.toLowerCase().includes(q)):_lines;const b=document.getElementById('logbox');b.textContent=l.join('\n')||'(empty)';b.scrollTop=b.scrollHeight;}
function autoRef(){const on=document.getElementById('auto-ref').checked;clearInterval(_aTimer);if(on)_aTimer=setInterval(loadLogs,3000);}
async function clearLogs(){if(!confirm('Clear all logs?'))return;await fetch('/api/logs',{method:'DELETE'});_lines=[];filterLogs();toast('Logs cleared');}

// Init
loadStatus();
setInterval(loadStatus,8000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def index(_=Depends(check_auth)):
    return HTMLResponse(content=HTML)
