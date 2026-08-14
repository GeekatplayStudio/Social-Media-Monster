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
from src.core.llm_client import _CIRCUIT
from src.core.platforms import PlatformCredentialStore, PLATFORM_SPECS
from src.core.channel_clients import test_channel
from src.agents.super_agent import SuperAgent
from src.mcp.server import SocialMediaMonsterMCP

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates/index.html")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="SocialMediaMonster Control Dashboard & MCP Server", lifespan=lifespan)

images_dir = "data/outputs/images"
videos_dir = "data/outputs/videos"
avatars_dir = "data/outputs/avatars"
os.makedirs(images_dir, exist_ok=True)
os.makedirs(videos_dir, exist_ok=True)
os.makedirs(avatars_dir, exist_ok=True)

app.mount("/static/images", StaticFiles(directory=images_dir), name="images")
app.mount("/static/videos", StaticFiles(directory=videos_dir), name="videos")
app.mount("/static/avatars", StaticFiles(directory=avatars_dir), name="avatars")

super_agent = SuperAgent()
mcp_server = SocialMediaMonsterMCP(super_agent)
security = SecurityManager()
platform_store = PlatformCredentialStore()

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

CREDENTIAL_FIELDS = (
    "openai_api_key", "gemini_api_key", "anthropic_api_key",
    "stability_api_key", "comfy_org_api_key", "tavily_api_key",
)


@app.post("/api/provider-config")
def save_provider_config(data: dict):
    # Encrypt all API keys before persisting to SQLite. An empty submitted field keeps
    # the stored key rather than wiping it, so the UI can show masked placeholders.
    existing = {}
    with Session(engine) as session:
        prior = session.exec(select(SystemSetting).where(SystemSetting.key_name == "abstract_provider_cfg")).first()
        if prior and prior.value:
            try:
                existing = json.loads(prior.value)
            except Exception:
                existing = {}

    for field in CREDENTIAL_FIELDS:
        submitted = (data.get(field) or "").strip()
        if submitted:
            data[field] = security.encrypt_credential(submitted)
        else:
            data[field] = existing.get(field, "")

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

    # Credentials or endpoint may have changed - retry providers that were marked down.
    _CIRCUIT.reset()
    return {"status": "provider_config_saved", "host_mode": data.get("host_mode", "local")}

# ----------------------------------------------------------------- Channel Connections

@app.get("/api/platforms")
def list_platforms():
    """
    Connection status for all 9 channels. Secret values are never included - only a
    per-field 'is_set' flag so the UI can render a masked placeholder.
    """
    return {"platforms": platform_store.describe_all()}


@app.get("/api/platforms/{platform}")
def get_platform(platform: str):
    try:
        return platform_store.describe(platform)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown platform '{platform}'")


@app.post("/api/platforms/{platform}")
def save_platform(platform: str, data: dict):
    """Blank secret fields keep the stored value, so nothing has to be re-typed."""
    try:
        return platform_store.save_credentials(platform, data)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown platform '{platform}'")


@app.post("/api/platforms/{platform}/test")
def test_platform(platform: str):
    """Live credential check against the channel's own API."""
    try:
        spec = PLATFORM_SPECS[platform]
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown platform '{platform}'")

    creds = platform_store.get_credentials(platform)
    result = test_channel(platform, creds)
    platform_store.record_test_result(platform, result.ok, result.message, result.account)
    return {
        "platform": platform,
        "label": spec["label"],
        **result.as_dict(),
        "connection": platform_store.describe(platform),
    }


@app.post("/api/platforms/{platform}/toggle")
def toggle_platform(platform: str, data: dict):
    try:
        return platform_store.set_enabled(platform, bool(data.get("enabled", True)))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown platform '{platform}'")


@app.post("/api/platforms/{platform}/disconnect")
def disconnect_platform(platform: str):
    try:
        return platform_store.disconnect(platform)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown platform '{platform}'")


@app.get("/api/platforms-readiness")
def platforms_readiness():
    return {"channels": super_agent.publisher_agent.connection_report()}


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

@app.get("/api/media-mode")
def get_media_mode():
    with Session(engine) as session:
        mode_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "active_media_mode")).first()
        provider_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "active_video_provider")).first()
        return {
            "media_mode": mode_setting.value if mode_setting else "image",
            "video_provider": provider_setting.value if provider_setting else "ffmpeg_template"
        }

@app.post("/api/media-mode")
def set_media_mode(data: dict):
    mode = data.get("media_mode", "image")
    provider = data.get("video_provider", "ffmpeg_template")
    with Session(engine) as session:
        m_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "active_media_mode")).first()
        if not m_setting:
            m_setting = SystemSetting(key_name="active_media_mode", value=mode)
        else:
            m_setting.value = mode
        session.add(m_setting)

        v_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "active_video_provider")).first()
        if not v_setting:
            v_setting = SystemSetting(key_name="active_video_provider", value=provider)
        else:
            v_setting.value = provider
        session.add(v_setting)

        session.commit()
        log_event("WebDashboard", f"Active Media Mode changed to: {mode.upper()} (Video Provider: {provider.upper()})", level="INFO")
    return {"status": "media_mode_saved", "media_mode": mode, "video_provider": provider}

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
    return {
        "status": "generated" if image_path else "error",
        "image_path": os.path.basename(image_path) if image_path else "",
    }

@app.post("/api/posts/{post_id}/generate-video")
def generate_single_test_video(post_id: int):
    with Session(engine) as session:
        draft = session.get(PostDraft, post_id)
        if not draft:
            raise HTTPException(status_code=404, detail="Post draft not found")
        verified_news_id = draft.verified_news_id

    video_path = super_agent.visual_agent.generate_master_video_for_story(verified_news_id)
    return {
        "status": "generated" if video_path else "error",
        "video_path": os.path.basename(video_path) if video_path else "",
        "verified_news_id": verified_news_id
    }


@app.post("/api/posts/{post_id}/approve")
def approve_post(post_id: int):
    """
    Final Content Manager sign-off. Without this route nothing ever reached the
    'approved' state, so the PublisherAgent had no work and the pipeline dead-ended.
    """
    with Session(engine) as session:
        post = session.get(PostDraft, post_id)
        if not post:
            raise HTTPException(status_code=404, detail="Post draft not found")
        post.status = "approved"
        session.add(post)
        session.commit()
        log_event("WebDashboard", f"Post #{post_id} ({post.platform}) approved for publication.", level="SUCCESS")

    published = 0
    if super_agent.mode == "production":
        published = super_agent.publisher_agent.run()
    return {"status": "approved", "post_id": post_id, "published": published}


@app.post("/api/posts/{post_id}/reject")
def reject_post(post_id: int):
    with Session(engine) as session:
        post = session.get(PostDraft, post_id)
        if not post:
            raise HTTPException(status_code=404, detail="Post draft not found")
        post.status = "rejected"
        session.add(post)
        session.commit()
        log_event("WebDashboard", f"Post #{post_id} ({post.platform}) rejected by operator.", level="WARNING")
    return {"status": "rejected", "post_id": post_id}


@app.post("/api/publish")
def publish_approved_posts():
    """Dispatch every approved draft through the PublisherAgent."""
    if super_agent.mode != "production":
        return {"status": "skipped", "reason": "System is in DEMO mode. Switch to PRODUCTION to publish.", "published": 0}
    published = super_agent.publisher_agent.run()
    return {"status": "published", "published": published}

@app.post("/api/posts/{post_id}/generate-article")
def generate_single_test_article(post_id: int):
    result = super_agent.writer_agent.generate_single_test_article(post_id)
    return result

@app.post("/api/scan")
def trigger_scan_only(background_tasks: BackgroundTasks):
    super_agent.stop_requested = False
    background_tasks.add_task(super_agent.research_agent.run)
    return {"status": "scan_started"}

@app.get("/api/llm-status")
def llm_status():
    """
    Reports whether the configured text provider is actually usable. A silently
    unreachable endpoint or a model name that is not installed is the single biggest
    cause of weak output, so it is surfaced explicitly rather than left to the logs.
    """
    cfg = super_agent.writer_agent.llm.get_active_provider_config()
    provider = (cfg.get("provider") or "ollama").lower()
    wanted = cfg.get("model_name") or ""

    if provider != "ollama":
        key_set = bool(cfg.get(f"{provider}_api_key"))
        return {
            "provider": provider, "reachable": key_set, "models": [],
            "model_name": wanted, "model_installed": key_set,
            "detail": "API key present" if key_set else "No API key configured",
        }

    base_url = cfg.get("base_url", "http://127.0.0.1:11434").rstrip("/")
    try:
        req = urllib.request.Request(f"{base_url}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            models = [m.get("name", "") for m in json.loads(resp.read()).get("models", [])]
    except Exception as e:
        return {
            "provider": provider, "reachable": False, "models": [],
            "model_name": wanted, "model_installed": False,
            "detail": f"Cannot reach {base_url} ({e}). Run 'ollama serve'.",
        }

    # Ollama resolves a bare name to its :latest tag.
    installed = any(m == wanted or m.split(":")[0] == wanted.split(":")[0] for m in models)
    return {
        "provider": provider, "reachable": True, "models": models,
        "model_name": wanted, "model_installed": installed,
        "detail": "Ready" if installed else f"'{wanted}' is not installed. Available: {', '.join(models) or 'none'}",
    }


@app.get("/api/health")
def health_check():
    """Lightweight readiness probe used by the start script and by uptime checks."""
    from src.core.tavily_client import TavilyClient
    with Session(engine) as session:
        post_count = len(session.exec(select(PostDraft.id)).all())
    return {
        "status": "ok",
        "mode": super_agent.mode,
        "stage": super_agent.telemetry.get("current_stage"),
        "posts": post_count,
        "research_engine": "tavily" if TavilyClient().is_configured() else "rss",
    }


@app.get("/api/logs")
def get_logs():
    with Session(engine) as session:
        logs = session.exec(select(SystemLog).order_by(desc(SystemLog.id)).limit(25)).all()
        return logs

@app.get("/api/telemetry")
def get_telemetry():
    return super_agent.telemetry

@app.get("/api/posts")
def get_posts(limit: int = 60, status: str = None, platform: str = None):
    """
    The old fixed limit of 15 was smaller than a single cycle's output (9 platforms per
    story), so most generated posts were invisible and platform filters looked empty.
    """
    limit = max(1, min(limit, 500))
    with Session(engine) as session:
        query = select(PostDraft)
        if status:
            query = query.where(PostDraft.status == status)
        if platform:
            query = query.where(PostDraft.platform == platform)
        posts = session.exec(query.order_by(desc(PostDraft.id)).limit(limit)).all()

        result = []
        for p in posts:
            p_dict = p.model_dump()
            img_filename = (p_dict.get("image_path") or "").replace("\\", "/").split("/")[-1]
            media_filename = (p_dict.get("media_path") or "").replace("\\", "/").split("/")[-1]

            # Check if video file exists
            if media_filename and os.path.exists(os.path.join(videos_dir, media_filename)):
                p_dict["media_path"] = media_filename
                p_dict["media_type"] = "video"
            else:
                p_dict["media_path"] = None

            # Check if image file exists
            if img_filename and os.path.exists(os.path.join(images_dir, img_filename)):
                p_dict["image_path"] = img_filename
            else:
                p_dict["image_path"] = None

            result.append(p_dict)
        return result


@app.get("/api/provider-config")
def get_provider_config():
    """Returns provider settings with credentials masked - never the decrypted keys."""
    payload = {
        "provider": "ollama", "host_mode": "local",
        "base_url": "http://127.0.0.1:11434", "model_name": "llama3",
    }
    with Session(engine) as session:
        setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "abstract_provider_cfg")).first()
        if setting and setting.value:
            try:
                stored = json.loads(setting.value)
                payload.update({k: v for k, v in stored.items() if k not in CREDENTIAL_FIELDS})
            except Exception:
                stored = {}
        else:
            stored = {}

    for field in CREDENTIAL_FIELDS:
        payload[f"{field}_set"] = bool(stored.get(field))
    return payload

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
