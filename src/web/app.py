import os
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select, desc
from src.core.db import engine, init_db, log_event, load_config, DEFAULT_EQUALIZER
from src.core.models import PostDraft, PersonaProfile, SystemLog, SystemSetting
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

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if os.path.exists(TEMPLATE_PATH):
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>SocialMediaMonster Control Dashboard</h1>"

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
    return {"status": "generated" if image_path else "error", "image_path": image_path}

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
        return posts

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
