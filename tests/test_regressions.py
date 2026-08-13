"""
Regression tests for the defects fixed in the content-quality pass.

Each test pins one specific bug so it cannot silently return.
"""
import os
import pytest
from sqlmodel import Session, select, delete

from src.core.db import init_db, engine
from src.core.models import TrendItem, VerifiedNews, PostDraft
from src.core.llm_client import LLMClient, PLATFORM_LIMITS
from src.core.security import SecurityManager
from src.agents.visual_agent import VisualAgent
from src.agents.validator_agent import ValidatorAgent
from src.agents.writer_agent import WriterAgent


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    with Session(engine) as session:
        for model in (PostDraft, VerifiedNews, TrendItem):
            session.exec(delete(model))
        session.commit()
    yield


# --------------------------------------------------------------- fallback contamination

def test_fallback_never_injects_an_unrelated_hardcoded_story():
    """The synthesizer used to paste a fixed Tailscale/SQLite story into every post."""
    client = LLMClient()
    out = client.generate(
        "Headline: EU opens antitrust probe into cloud AI pricing\n"
        "Verified Facts: The Commission sent questionnaires to three hyperscalers in March.\n"
        "Key Takeaways: Procurement teams should expect new disclosure duties.\n",
        platform="linkedin",
    )
    lowered = out.lower()
    assert "tailscale" not in lowered
    assert "write-ahead logging" not in lowered
    assert "sqlite" not in lowered
    assert "antitrust" in lowered or "commission" in lowered


def test_rewrite_task_preserves_the_callers_text():
    """Humanizing a post must not swap in a different story."""
    client = LLMClient()
    original = (
        "Redis 8 ships a vector set type. It indexes embeddings inline with the keyspace. "
        "Early benchmarks put recall at 0.94 for a one million vector corpus."
    )
    out = client.generate(
        f"Original Text:\n{original}\n\nTask: Rewrite to remove robotic patterns.",
        platform="linkedin",
        task="rewrite",
    )
    assert "Redis" in out
    assert "tailscale" not in out.lower()


def test_image_prompt_task_never_returns_a_social_post():
    """image_prompt used to be produced by the article synthesizer, hashtags and all."""
    client = LLMClient()
    out = client.generate(
        "Article Headline: Meta open sources a 400B parameter model\n"
        "Post Content Summary: Weights released under a research licence.\n"
        "Task: Create a ComfyUI concept prompt.",
        task="image_prompt",
    )
    assert "#" not in out
    assert "http" not in out.lower()


# --------------------------------------------------------------- platform handling

@pytest.mark.parametrize("platform", ["twitter", "linkedin", "reddit", "wordpress", "instagram"])
def test_generated_copy_respects_platform_character_limits(platform):
    client = LLMClient()
    out = client.generate(
        "Headline: A very long running technical story about distributed systems\n"
        "Verified Facts: " + ("The cluster rebalanced shards across nine regions. " * 40) + "\n"
        "Key Takeaways: Capacity planning matters.\n",
        platform=platform,
    )
    assert len(out) <= PLATFORM_LIMITS[platform]


def test_each_platform_produces_distinct_copy():
    """Every channel used to collapse to the same twitter-shaped output."""
    client = LLMClient()
    prompt = (
        "Headline: Postgres 18 lands asynchronous IO\n"
        "Verified Facts: The release adds io_uring support on Linux. Throughput rose 2.3x on NVMe.\n"
        "Key Takeaways: Storage bound workloads benefit most.\n"
    )
    outputs = {p: client.generate(prompt, platform=p) for p in ["twitter", "linkedin", "reddit", "wordpress"]}
    assert len(set(outputs.values())) == len(outputs)


# --------------------------------------------------------------- image prompts

def test_image_prompts_are_story_specific():
    """Three keyword branches used to return one of three fixed strings."""
    a = VisualAgent._build_vivid_comfy_prompt(
        "OpenAI ships Sora 2 with 4K video generation", "Physics aware rendering.", "16:9")
    b = VisualAgent._build_vivid_comfy_prompt(
        "Rust 1.90 stabilises async closures", "Language team lands the feature.", "16:9")
    assert a != b
    assert "sora" in a.lower()
    assert "rust" in b.lower()


def test_image_prompt_honours_aspect_ratio():
    wide = VisualAgent._build_vivid_comfy_prompt("Story headline here", "body", "16:9")
    tall = VisualAgent._build_vivid_comfy_prompt("Story headline here", "body", "4:5")
    assert "cinematic" in wide
    assert "vertical" in tall


def test_corrupt_image_payload_is_rejected_not_reported_as_success(tmp_path):
    """Providers used to report SUCCESS without ever writing a decodable file."""
    target = str(tmp_path / "out.png")
    assert VisualAgent._write_image_bytes(b"this is not an image", target) is False
    assert not os.path.exists(target)
    assert VisualAgent._write_image_bytes(b"", target) is False


def test_visual_agent_rejects_a_social_post_stored_as_an_image_prompt():
    assert VisualAgent._is_usable_prompt("⚡ TECH BREAKDOWN: something\n\n#SQLite #DevOps") is False
    assert VisualAgent._is_usable_prompt(
        "16-bit SNES-era RPG pixel art depicting a data vault of glowing crystal cores, "
        "isometric composition, dithered shading, dark matte background."
    ) is True


# --------------------------------------------------------------- QA gate & pipeline state

def test_validator_approves_clean_drafts_so_publisher_has_work():
    """Nothing ever reached 'approved', so PublisherAgent always found zero drafts."""
    with Session(engine) as session:
        news = VerifiedNews(trend_id=1, headline="Test story", verified_facts="Facts.", key_takeaways="Impact.")
        session.add(news)
        session.commit()
        session.add(PostDraft(
            verified_news_id=news.id, platform="linkedin", persona_key="tech_visionary",
            headline="Test story",
            content="A clear human sentence about the release. It lands today with measurable gains for teams.",
            ai_detection_score=0.1, status="humanized",
        ))
        session.commit()

    result = ValidatorAgent().run()
    assert result["approved"] == 1

    with Session(engine) as session:
        assert session.exec(select(PostDraft)).first().status == "approved"


def test_validator_holds_degenerate_drafts_for_review():
    with Session(engine) as session:
        news = VerifiedNews(trend_id=1, headline="Test story", verified_facts="Facts.", key_takeaways="Impact.")
        session.add(news)
        session.commit()
        session.add(PostDraft(
            verified_news_id=news.id, platform="twitter", persona_key="tech_visionary",
            headline="Test story", content="too short", ai_detection_score=0.1, status="humanized",
        ))
        session.commit()

    result = ValidatorAgent().run()
    assert result["held_for_review"] == 1


def test_writer_does_not_redraft_the_same_news_twice():
    """The writer re-drafted every verified item on every cycle, multiplying duplicates."""
    with Session(engine) as session:
        session.add(VerifiedNews(
            trend_id=1, headline="Kubernetes 1.34 enables in-place pod resize",
            verified_facts="The feature graduates to beta. Restart-free vertical scaling is supported.",
            key_takeaways="Fewer disruptive restarts for stateful workloads.",
        ))
        session.commit()

    writer = WriterAgent()
    first = writer.run()
    second = writer.run()

    assert first > 0
    assert second == 0, "verified news was drafted a second time"


# --------------------------------------------------------------- security

def test_credentials_round_trip_and_are_not_stored_in_clear():
    sec = SecurityManager()
    plain = "tvly-dev-abcdefghijklmnopqrstuvwxyz123456"
    encrypted = sec.encrypt_credential(plain)
    assert encrypted.startswith("ENC:")
    assert plain not in encrypted
    assert sec.decrypt_credential(encrypted) == plain


def test_legacy_xor_credentials_still_decrypt():
    """Existing records written by the previous build must remain readable."""
    sec = SecurityManager()
    legacy = sec._legacy_cipher("sk-legacy-value-1234567890", decrypt=False)
    assert legacy.startswith("ENC:")
    assert not legacy.startswith("ENC:v2:")
    assert sec.decrypt_credential(legacy) == "sk-legacy-value-1234567890"


# --------------------------------------------------------------- provider resilience

def test_unreachable_provider_is_probed_once_not_once_per_call(monkeypatch):
    """
    A refused connect costs seconds on Windows and the pipeline makes one call per post
    per stage, so retrying a dead provider every time stalled whole cycles.
    """
    from src.core import llm_client as mod

    mod._CIRCUIT.reset()
    attempts = {"count": 0}

    def boom(self, prompt, system_prompt, cfg):
        attempts["count"] += 1
        mod._CIRCUIT.trip(self._endpoint_id("ollama", cfg))
        return ""

    monkeypatch.setattr(mod.LLMClient, "_call_ollama", boom)

    client = mod.LLMClient()
    prompt = "Headline: A story\nVerified Facts: Something concrete happened today.\n"
    for _ in range(5):
        assert client.generate(prompt, platform="twitter")

    assert attempts["count"] == 1, "dead provider was re-probed on every call"
    mod._CIRCUIT.reset()


def test_circuit_breaker_reopens_after_cooldown(monkeypatch):
    from src.core.llm_client import ProviderCircuitBreaker

    breaker = ProviderCircuitBreaker()
    monkeypatch.setattr(ProviderCircuitBreaker, "COOLDOWN_SECONDS", 0.0)
    breaker.trip("ollama@local")
    assert breaker.is_open("ollama@local") is False


def test_tavily_key_is_redacted_from_output():
    sec = SecurityManager()
    text = "debug dump key=tvly-dev-AbCdEfGhIjKlMnOpQrStUvWx1234"
    assert "tvly-dev-AbCdEfGhIjKlMnOpQrStUvWx1234" not in sec.sanitize_output_payload(text)
