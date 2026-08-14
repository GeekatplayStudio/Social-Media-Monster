import os
import pytest
from sqlmodel import Session, select
from src.core.db import engine, init_db
from src.core.models import TrendItem, VerifiedNews, PostDraft, SystemSetting
from src.agents.visual_agent import VisualAgent
from fastapi.testclient import TestClient
from src.web.app import app

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    os.environ["SKIP_LOCAL_COMFYUI"] = "1"
    init_db()
    with Session(engine) as session:
        # Clear existing test records if any
        session.exec(select(PostDraft)).all()
    yield
    os.environ.pop("SKIP_LOCAL_COMFYUI", None)

def test_video_prompt_builder():
    agent = VisualAgent()
    prompt = agent._build_vivid_video_prompt(
        headline="Breakthrough in Autonomous Video AI Models",
        content="Open source video diffusion models now render 9:16 vertical 60fps video directly on local GPU clusters.",
        aspect_ratio="9:16"
    )
    assert "9:16" in prompt
    assert "vertical" in prompt.lower()
    assert len(prompt) > 50

def test_generate_master_video_attaches_to_all_drafts():
    with Session(engine) as session:
        trend = TrendItem(title="Test Video Trend", url="http://example.com", source="RSS", summary="Test video summary")
        session.add(trend)
        session.commit()
        session.refresh(trend)

        story = VerifiedNews(
            trend_id=trend.id,
            headline="New 9:16 AI Video Model Releases",
            verified_facts="Open source model renders fast vertical video.",
            key_takeaways="Fast vertical video rendering"
        )
        session.add(story)
        session.commit()
        session.refresh(story)

        # Create 3 drafts under the same story
        draft1 = PostDraft(verified_news_id=story.id, platform="twitter", persona_key="tech_visionary", headline=story.headline, content="Post 1")
        draft2 = PostDraft(verified_news_id=story.id, platform="instagram", persona_key="tech_visionary", headline=story.headline, content="Post 2")
        draft3 = PostDraft(verified_news_id=story.id, platform="linkedin", persona_key="tech_visionary", headline=story.headline, content="Post 3")
        session.add_all([draft1, draft2, draft3])
        session.commit()
        story_id = story.id

    agent = VisualAgent()
    output_path = agent.generate_master_video_for_story(story_id)
    assert output_path != ""
    assert os.path.exists(output_path)
    assert output_path.endswith(".mp4")

    # Verify that ALL drafts under story_id now have media_type = "video" and media_path = output_path filename
    with Session(engine) as session:
        story_db = session.get(VerifiedNews, story_id)
        assert story_db.master_video_path is not None
        assert "master_story_" in story_db.master_video_path

        drafts = session.exec(select(PostDraft).where(PostDraft.verified_news_id == story_id)).all()
        assert len(drafts) == 3
        for d in drafts:
            assert d.media_type == "video"
            assert d.media_path == story_db.master_video_path

def test_media_mode_api_endpoints():
    # Test GET media mode
    res = client.get("/api/media-mode")
    assert res.status_code == 200
    data = res.json()
    assert "media_mode" in data
    assert "video_provider" in data

    # Test POST media mode
    res_post = client.post("/api/media-mode", json={"media_mode": "video", "video_provider": "ffmpeg_template"})
    assert res_post.status_code == 200
    assert res_post.json()["media_mode"] == "video"

    # Verify persistence via GET
    res_get = client.get("/api/media-mode")
    assert res_get.json()["media_mode"] == "video"
    assert res_get.json()["video_provider"] == "ffmpeg_template"
