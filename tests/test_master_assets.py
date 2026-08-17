"""
One master asset per story, reused by every draft - and no two stories sharing artwork.
"""
import pytest
from sqlmodel import Session, select, delete

from src.core.db import init_db, engine
from src.core.models import VerifiedNews, PostDraft, TrendItem
from src.core.article_analysis import build_visual_brief
from src.agents.visual_agent import VisualAgent


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    with Session(engine) as session:
        session.exec(delete(PostDraft))
        session.exec(delete(VerifiedNews))
        session.exec(delete(TrendItem))
        session.commit()
    yield


def _story_with_drafts(headline, facts, platforms):
    with Session(engine) as session:
        news = VerifiedNews(trend_id=1, headline=headline, verified_facts=facts,
                            key_takeaways="Impact line.")
        session.add(news)
        session.commit()
        for p in platforms:
            session.add(PostDraft(
                verified_news_id=news.id, platform=p, persona_key="tech_visionary",
                headline=headline, content=facts, status="approved",
            ))
        session.commit()
        return news.id


# --------------------------------------------------------------- reuse

def test_one_image_is_shared_by_every_draft_of_a_story(monkeypatch, tmp_path):
    """
    Rendering per draft meant a story on 10 channels cost 10 renders and showed a
    different picture on each network.
    """
    platforms = ["twitter", "linkedin", "reddit", "wordpress", "telegram"]
    story_id = _story_with_drafts("Chip foundry expands capacity",
                                  "The plant adds two lines in 2027.", platforms)

    agent = VisualAgent()
    agent.output_dir = str(tmp_path)
    renders = {"count": 0}

    def fake_render(headline, content, platform, save_path):
        renders["count"] += 1
        with open(save_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    monkeypatch.setattr(agent, "_dispatch_comfyui_prompt", lambda *a, **k: False)
    monkeypatch.setattr(agent, "_render_vibrant_article_card", fake_render)

    agent.generate_master_image_for_story(story_id, force=True)

    assert renders["count"] == 1, "one render per story, not per draft"

    with Session(engine) as session:
        story = session.get(VerifiedNews, story_id)
        drafts = session.exec(select(PostDraft).where(PostDraft.verified_news_id == story_id)).all()
        assert story.master_image_path
        assert {d.image_path for d in drafts} == {story.master_image_path}
        assert len(drafts) == len(platforms)


def test_existing_master_is_reused_without_re_rendering(monkeypatch, tmp_path):
    story_id = _story_with_drafts("Chip foundry expands capacity", "Facts.", ["twitter", "linkedin"])
    agent = VisualAgent()
    agent.output_dir = str(tmp_path)

    def fake_render(headline, content, platform, save_path):
        with open(save_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    monkeypatch.setattr(agent, "_dispatch_comfyui_prompt", lambda *a, **k: False)
    monkeypatch.setattr(agent, "_render_vibrant_article_card", fake_render)
    agent.generate_master_image_for_story(story_id, force=True)

    # A second pass without force must not render again.
    calls = {"n": 0}
    def counting_render(*a, **k):
        calls["n"] += 1
        return fake_render(*a, **k)
    monkeypatch.setattr(agent, "_render_vibrant_article_card", counting_render)

    agent.generate_master_image_for_story(story_id)
    assert calls["n"] == 0, "an existing master image should be reused, not re-rendered"


def test_per_post_button_regenerates_the_story_master(monkeypatch, tmp_path):
    story_id = _story_with_drafts("Chip foundry expands capacity", "Facts.", ["twitter", "linkedin", "reddit"])
    with Session(engine) as session:
        draft_id = session.exec(select(PostDraft)).first().id

    agent = VisualAgent()
    agent.output_dir = str(tmp_path)
    monkeypatch.setattr(agent, "_dispatch_comfyui_prompt", lambda *a, **k: False)
    monkeypatch.setattr(agent, "_render_vibrant_article_card",
                        lambda h, c, p, sp: open(sp, "wb").write(b"\x89PNG\r\n\x1a\n" + b"0" * 64))

    agent.generate_single_test_image(draft_id)

    with Session(engine) as session:
        drafts = session.exec(select(PostDraft).where(PostDraft.verified_news_id == story_id)).all()
        paths = {d.image_path for d in drafts}
    assert len(paths) == 1, "regenerating from one post must update every post of the story"
    assert paths.pop().startswith("master_story_")


# --------------------------------------------------------------- no repetition

def test_two_stories_sharing_a_concept_get_different_scenes():
    """Both are hardware stories, so the concept matches - the staging must still differ."""
    a = build_visual_brief("Graphics card makers warn of looming shortage",
                           "Budget GPUs face the squeeze as supply tightens.")
    b = build_visual_brief("GPU squeeze hits simulation workloads",
                           "Siemens routes around constrained accelerator supply.")

    assert a["concept"] == b["concept"] == "hardware"
    assert (a["moment"], a["vantage"], a["palette"]) != (b["moment"], b["vantage"], b["palette"])

    prompt_a = VisualAgent._build_vivid_comfy_prompt(
        "Graphics card makers warn of looming shortage", "Budget GPUs face the squeeze.", "16:9")
    prompt_b = VisualAgent._build_vivid_comfy_prompt(
        "GPU squeeze hits simulation workloads", "Siemens routes around supply.", "16:9")
    assert prompt_a != prompt_b


def test_staging_is_stable_for_the_same_story():
    """Same story must render the same way on a re-run."""
    first = build_visual_brief("Regulators fine a cloud provider", "A penalty was issued.")
    second = build_visual_brief("Regulators fine a cloud provider", "A penalty was issued.")
    assert first["moment"] == second["moment"]
    assert first["vantage"] == second["vantage"]


def test_many_stories_produce_varied_staging():
    headlines = [f"Company {i} announces a new accelerator chip" for i in range(12)]
    combos = {
        (build_visual_brief(h, "It ships next year.")["moment"],
         build_visual_brief(h, "It ships next year.")["vantage"])
        for h in headlines
    }
    assert len(combos) >= 5, f"staging barely varies across stories: {len(combos)} distinct"


# --------------------------------------------------------------- comfy failure handling

def test_comfy_error_is_reported_immediately(monkeypatch):
    """A failed graph used to burn the whole poll budget before falling back."""
    agent = VisualAgent.__new__(VisualAgent)
    agent.server_address = "127.0.0.1:8188"
    agent.comfy_poll_interval = 0.01
    agent.config = {}

    history = {
        "abc123": {
            "status": {
                "status_str": "error",
                "messages": [["execution_error", {
                    "node_type": "CLIPTextEncode",
                    "exception_message": "ERROR: clip input is invalid: None\nmore detail",
                }]],
            },
            "outputs": {},
        }
    }

    class FakeResponse:
        status = 200
        def read(self):
            import json as _json
            return _json.dumps(history).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr("src.agents.visual_agent.urllib.request.urlopen", lambda *a, **k: FakeResponse())

    assert agent._await_comfy_output("abc123", "unused.png", attempts=500) is False


def test_comfy_error_reason_names_the_failing_node():
    status = {"messages": [["execution_error", {
        "node_type": "VAEDecode", "exception_message": "size mismatch\ntraceback"}]]}
    reason = VisualAgent._comfy_error_reason(status)
    assert "VAEDecode" in reason and "size mismatch" in reason
