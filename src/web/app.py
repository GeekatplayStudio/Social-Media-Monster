import os
import json
import urllib.request
import urllib.parse
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select, desc
from src.core.db import engine, init_db, log_event, load_config, DEFAULT_EQUALIZER
from src.core.models import PostDraft, PersonaProfile, SystemLog, SystemSetting
from src.core.security import SecurityManager
from src.agents.super_agent import SuperAgent
from src.mcp.server import SocialMediaMonsterMCP

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates/index.html")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="SocialMediaMonster Control Dashboard & MCP Server", lifespan=lifespan)

images_dir = "data/outputs/images"
avatars_dir = "data/outputs/avatars"
os.makedirs(images_dir, exist_ok=True)
os.makedirs(avatars_dir, exist_ok=True)

app.mount("/static/images", StaticFiles(directory=images_dir), name="images")
app.mount("/static/avatars", StaticFiles(directory=avatars_dir), name="avatars")

super_agent = SuperAgent()
mcp_server = SocialMediaMonsterMCP(super_agent)
security = SecurityManager()

def is_remote_auth_required() -> bool:
    with Session(engine) as session:
        setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "abstract_provider_cfg")).first()
        if setting and setting.value:
            try:
                data = json.loads(setting.value)
                return data.get("host_mode") == "remote"
            except Exception:
                pass
    return False

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>SocialMediaMonster Control Dashboard</h1>"

# Google OAuth 2.0 Authorization Route
@app.get("/auth/google/login")
def google_login():
    cfg = load_config().get("google_oauth", {})
    client_id = cfg.get("client_id", "")
    redirect_uri = cfg.get("redirect_uri", "http://127.0.0.1:8000/auth/google/callback")
    auth_url = cfg.get("auth_url", "https://accounts.google.com/o/oauth2/v2/auth")
    
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent"
    }
    url = f"{auth_url}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url)

@app.get("/auth/google/callback")
def google_callback(code: str = None):
    if not code:
        return JSONResponse({"status": "error", "message": "No authorization code received"}, status_code=400)
    
    cfg = load_config().get("google_oauth", {})
    client_id = cfg.get("client_id", "")
    client_secret = cfg.get("client_secret", "")
    redirect_uri = cfg.get("redirect_uri", "http://127.0.0.1:8000/auth/google/callback")
    token_url = cfg.get("token_url", "https://oauth2.googleapis.com/token")

    try:
        body = urllib.parse.urlencode({
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }).encode('utf-8')
        
        req = urllib.request.Request(token_url, data=body, headers={'Content-Type': 'application/x-www-form-urlencoded'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                t_data = json.loads(resp.read().decode('utf-8'))
                log_event("OAuth", f"Google OAuth login successful. User authenticated.", level="SUCCESS")
                return RedirectResponse("/")
    except Exception as e:
        log_event("OAuth", f"OAuth authentication error: {e}", level="ERROR")

    return RedirectResponse("/?auth=success")

@app.post("/api/provider-config")
def save_provider_config(data: dict):
    # Encrypt all API keys before persisting to SQLite
    data["openai_api_key"] = security.encrypt_credential(data.get("openai_api_key", ""))
    data["gemini_api_key"] = security.encrypt_credential(data.get("gemini_api_key", ""))
    data["anthropic_api_key"] = security.encrypt_credential(data.get("anthropic_api_key", ""))
    data["stability_api_key"] = security.encrypt_credential(data.get("stability_api_key", ""))
    data["comfy_org_api_key"] = security.encrypt_credential(data.get("comfy_org_api_key", ""))

    with Session(engine) as session:
        setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "abstract_provider_cfg")).first()
        val_str = json.dumps(data)
        if not setting:
            setting = SystemSetting(key_name="abstract_provider_cfg", value=val_str)
        else:
            setting.value = val_str
        session.add(setting)
        session.commit()
        log_event("WebDashboard", f"Saved & encrypted Abstract Provider configuration (Host: {data.get('host_mode', 'local').upper()})", level="SUCCESS")
    return {"status": "provider_config_saved", "host_mode": data.get("host_mode", "local")}

@app.post("/api/stop")
def stop_all_agents():
    super_agent.emergency_stop()
    return {"status": "stopped", "message": "Emergency Stop activated. All agents halted."}

@app.get("/api/image-provider")
def get_image_provider():
    with Session(engine) as session:
        setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "active_image_provider")).first()
        return {"provider": setting.value if setting else "comfyui_local"}

@app.post("/api/image-provider")
def set_image_provider(data: dict):
    provider = data.get("provider", "comfyui_local")
    with Session(engine) as session:
        setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "active_image_provider")).first()
        if not setting:
            setting = SystemSetting(key_name="active_image_provider", value=provider)
        else:
            setting.value = provider
        session.add(setting)
        session.commit()
        log_event("WebDashboard", f"Active Image Generation Provider changed to: {provider.upper()}", level="INFO")
    return {"status": "provider_saved", "provider": provider}

@app.get("/api/equalizer")
def get_equalizer():
    with Session(engine) as session:
        setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "writer_equalizer_settings")).first()
        if setting and setting.value:
            try:
                return json.loads(setting.value)
            except Exception:
                pass
        return DEFAULT_EQUALIZER

@app.post("/api/equalizer")
def save_equalizer(data: dict):
    with Session(engine) as session:
        setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "writer_equalizer_settings")).first()
        val_str = json.dumps(data)
        if not setting:
            setting = SystemSetting(key_name="writer_equalizer_settings", value=val_str)
        else:
            setting.value = val_str
        session.add(setting)
        session.commit()
        log_event("WebDashboard", f"Updated 15-band AI Writer Equalizer profile settings")
    return {"status": "equalizer_saved", "profile": data}

@app.get("/api/sample-article")
def get_sample_article():
    with Session(engine) as session:
        setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "sample_writing_article")).first()
        return {"sample_article": setting.value if setting else ""}

@app.post("/api/sample-article")
def save_sample_article(data: dict):
    sample_str = data.get("sample_article", "")
    with Session(engine) as session:
        setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "sample_writing_article")).first()
        if not setting:
            setting = SystemSetting(key_name="sample_writing_article", value=sample_str)
        else:
            setting.value = sample_str
        session.add(setting)
        session.commit()
        log_event("WebDashboard", "Saved user sample article for AI author voice cloning")
    return {"status": "sample_saved", "sample_article": sample_str}

@app.get("/api/topics")
def get_topics():
    with Session(engine) as session:
        setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "search_topics")).first()
        return {"topics": setting.value if setting else "Generative AI, Local LLMs, ComfyUI, Flux, AI Agents"}

@app.post("/api/topics")
def save_topics(data: dict):
    topics_str = data.get("topics", "")
    with Session(engine) as session:
        setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "search_topics")).first()
        if not setting:
            setting = SystemSetting(key_name="search_topics", value=topics_str)
        else:
            setting.value = topics_str
        session.add(setting)
        session.commit()
    return {"status": "saved", "topics": topics_str}

@app.get("/api/schedule")
def get_schedule():
    with Session(engine) as session:
        h_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "schedule_interval_hours")).first()
        m_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "max_articles_per_cycle")).first()
        c_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "comfyui_enabled")).first()
        return {
            "hours": h_setting.value if h_setting else "6",
            "max_posts": m_setting.value if m_setting else "2",
            "comfyui_enabled": c_setting.value.lower() == "true" if c_setting else False
        }

@app.post("/api/schedule")
def save_schedule(data: dict):
    hours_str = str(data.get("hours", "6"))
    max_posts_str = str(data.get("max_posts", "2"))
    comfy_enabled_str = str(data.get("comfyui_enabled", "false"))
    
    with Session(engine) as session:
        h_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "schedule_interval_hours")).first()
        if not h_setting:
            h_setting = SystemSetting(key_name="schedule_interval_hours", value=hours_str)
        else:
            h_setting.value = hours_str
        session.add(h_setting)

        m_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "max_articles_per_cycle")).first()
        if not m_setting:
            m_setting = SystemSetting(key_name="max_articles_per_cycle", value=max_posts_str)
        else:
            m_setting.value = max_posts_str
        session.add(m_setting)

        c_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "comfyui_enabled")).first()
        if not c_setting:
            c_setting = SystemSetting(key_name="comfyui_enabled", value=comfy_enabled_str)
        else:
            c_setting.value = comfy_enabled_str
        session.add(c_setting)

        session.commit()
        log_event("WebDashboard", f"Updated settings: Every {hours_str} hours, Max {max_posts_str} posts per run, Bulk Images: {comfy_enabled_str.upper()}")
    return {"status": "schedule_saved", "hours": hours_str, "max_posts": max_posts_str, "comfyui_enabled": comfy_enabled_str}

@app.post("/api/posts/{post_id}/generate-image")
def generate_single_test_image(post_id: int):
    image_path = super_agent.visual_agent.generate_single_test_image(post_id)
    return {"status": "generated" if image_path else "error", "image_path": os.path.basename(image_path)}

@app.post("/api/posts/{post_id}/generate-article")
def generate_single_test_article(post_id: int):
    result = super_agent.writer_agent.generate_single_test_article(post_id)
    return result

@app.post("/api/scan")
def trigger_scan_only(background_tasks: BackgroundTasks):
    super_agent.stop_requested = False
    background_tasks.add_task(super_agent.research_agent.run)
    return {"status": "scan_started"}

@app.get("/api/logs")
def get_logs():
    with Session(engine) as session:
        logs = session.exec(select(SystemLog).order_by(desc(SystemLog.id)).limit(25)).all()
        return logs

@app.get("/api/telemetry")
def get_telemetry():
    return super_agent.telemetry

@app.get("/api/posts")
def get_posts():
    with Session(engine) as session:
        posts = session.exec(select(PostDraft).order_by(desc(PostDraft.id)).limit(15)).all()
        result = []
        for p in posts:
            p_dict = p.model_dump()
            if p_dict.get("image_path"):
                p_dict["image_path"] = p_dict["image_path"].replace("\\", "/").split("/")[-1]
            result.append(p_dict)
        return result

@app.post("/api/mode")
def update_mode(data: dict):
    new_mode = data.get("mode", "demo")
    super_agent.update_mode(new_mode)
    return {"status": "mode_updated", "mode": new_mode}

@app.post("/api/trigger")
def trigger_cycle(background_tasks: BackgroundTasks):
    super_agent.stop_requested = False
    background_tasks.add_task(super_agent.execute_cycle)
    return {"status": "triggered"}

@app.get("/api/mcp/manifest")
def get_mcp_manifest():
    return mcp_server.get_tools_manifest()

@app.post("/api/mcp/call")
def call_mcp_tool(data: dict):
    name = data.get("name")
    args = data.get("arguments", {})
    return mcp_server.call_tool(name, args)
