import os
import sys
import yaml
import json
from sqlmodel import SQLModel, create_engine, Session, select
from src.core.models import PersonaProfile, SystemLog, SystemSetting

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../../config/config.yaml")

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}

config = load_config()
db_path = config.get("database", {}).get("sqlite_path", "data/social_monster.db")
os.makedirs(os.path.dirname(db_path), exist_ok=True)

sqlite_url = f"sqlite:///{db_path}"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

def init_db():
    SQLModel.metadata.create_all(engine)
    migrate_columns()
    seed_defaults()

def migrate_columns():
    from sqlalchemy import text
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE verifiednews ADD COLUMN master_video_path VARCHAR"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE verifiednews ADD COLUMN master_video_prompt VARCHAR"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE postdraft ADD COLUMN media_type VARCHAR DEFAULT 'image'"))
        except Exception:
            pass
        try:
            conn.execute(text("ALTER TABLE postdraft ADD COLUMN media_path VARCHAR"))
        except Exception:
            pass
        conn.commit()

DEFAULT_EQUALIZER = {
    "seriousness": 0.2,       # -1 (Funny) to +1 (Serious)
    "formality": -0.2,        # -1 (Casual) to +1 (Formal)
    "cynicism": 0.4,          # -1 (Optimistic) to +1 (Sarcastic)
    "technical_depth": 0.6,   # -1 (Simple) to +1 (PhD Code)
    "political_stance": 0.0,  # -1 (Neutral) to +1 (Provocative)
    "pacing_length": -0.3,    # -1 (Punchy) to +1 (Deep Essay)
    "emotional_warmth": 0.1,  # -1 (Cold Analytical) to +1 (Warm)
    "storytelling_drama": 0.5,# -1 (Direct Facts) to +1 (Cinematic)
    "authority_boldness": 0.7,# -1 (Humble) to +1 (Unapologetic)
    "metaphor_density": 0.4,  # -1 (Literal) to +1 (Analogies)
    "clickbait_energy": 0.6,  # -1 (Modest) to +1 (Viral Hook)
    "tech_jargon": 0.3,       # -1 (Plain English) to +1 (Jargon)
    "action_cta": 0.5,        # -1 (Passive) to +1 (Direct CTA)
    "humor_type": 0.2,        # -1 (Dry/Dark) to +1 (Witty/Playful)
    "provocativeness": 0.4    # -1 (Consensus) to +1 (Contrarian)
}

def seed_defaults():
    with Session(engine) as session:
        presets = config.get("personas", {}).get("presets", {})
        for key, info in presets.items():
            existing = session.exec(select(PersonaProfile).where(PersonaProfile.key_name == key)).first()
            if not existing:
                persona = PersonaProfile(
                    key_name=key,
                    display_name=info.get("name", key),
                    humor_level=info.get("humor_level", 5),
                    cynicism_level=info.get("cynicism_level", 3),
                    technical_depth=info.get("technical_depth", 7),
                    political_stance=info.get("political_stance", "neutral"),
                    writing_style=info.get("writing_style", "")
                )
                session.add(persona)

        # Target search topics
        search_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "search_topics")).first()
        if not search_setting:
            default_topics = "Generative AI, Local LLMs, ComfyUI, Flux, Autonomous AI Agents, Neural Rendering"
            session.add(SystemSetting(key_name="search_topics", value=default_topics))

        # Schedule interval
        schedule_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "schedule_interval_hours")).first()
        if not schedule_setting:
            session.add(SystemSetting(key_name="schedule_interval_hours", value="6"))

        # Max articles per cycle
        max_articles_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "max_articles_per_cycle")).first()
        if not max_articles_setting:
            session.add(SystemSetting(key_name="max_articles_per_cycle", value="2"))

        # ComfyUI enabled flag
        comfy_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "comfyui_enabled")).first()
        if not comfy_setting:
            session.add(SystemSetting(key_name="comfyui_enabled", value="false"))

        # Equalizer settings JSON
        eq_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "writer_equalizer_settings")).first()
        if not eq_setting:
            session.add(SystemSetting(key_name="writer_equalizer_settings", value=json.dumps(DEFAULT_EQUALIZER)))

        # Sample user article text for voice cloning
        sample_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "sample_writing_article")).first()
        if not sample_setting:
            session.add(SystemSetting(key_name="sample_writing_article", value=""))

        session.commit()

def log_event(agent_name: str, message: str, level: str = "INFO", details: str = None):
    with Session(engine) as session:
        log_entry = SystemLog(
            agent_name=agent_name,
            log_level=level,
            message=message,
            details=details
        )
        session.add(log_entry)
        session.commit()
        
        safe_msg = message.encode(sys.stdout.encoding or 'ascii', errors='replace').decode(sys.stdout.encoding or 'ascii')
        print(f"[{level}] [{agent_name}] {safe_msg}")
