import pytest
import time
from unittest.mock import MagicMock
from sqlmodel import Session, select

from src.core.db import init_db, engine
from src.core.models import TrendItem, VerifiedNews, PostDraft, SystemSetting
from src.core.platforms import PlatformCredentialStore
from src.agents.research_agent import ResearchAgent
from src.agents.verifier_agent import VerifierAgent
from src.agents.writer_agent import WriterAgent
from src.core.scheduler import SchedulerService


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    with Session(engine) as session:
        session.exec(select(TrendItem)).all()
        for t in session.exec(select(TrendItem)).all():
            session.delete(t)
        for v in session.exec(select(VerifiedNews)).all():
            session.delete(v)
        for p in session.exec(select(PostDraft)).all():
            session.delete(p)
        session.commit()
    yield


def test_autoagent_endpoint_is_prefilled_but_not_armed_without_a_key():
    """
    The endpoint is pre-filled for convenience, but seeding must NOT ship a signing key.
    A hardcoded fallback would publish the shared secret in the repository and enable a
    live channel with it, letting anyone who read the source sign requests to the site.
    """
    store = PlatformCredentialStore()
    creds = store.get_credentials("autoagent")

    assert creds["base_url"] == "https://www.vladimirchopine.com/ai-news/api"
    assert creds["secret_key"] == "", "no signing key may be seeded from source"

    summary = store.describe("autoagent")
    assert summary["configured"] is False, "a channel without a key is not configured"
    assert summary["enabled"] is False, "it must stay disarmed until a real key is entered"


def test_autoagent_is_armed_once_a_real_key_is_supplied():
    store = PlatformCredentialStore()
    store.save_credentials("autoagent", {
        "base_url": "https://www.vladimirchopine.com/ai-news/api",
        "secret_key": "a" * 64,
    })
    store.set_enabled("autoagent", True)

    summary = store.describe("autoagent")
    assert summary["configured"] is True
    assert summary["enabled"] is True
    assert store.get_credentials("autoagent")["secret_key"] == "a" * 64


def test_canonical_url_deduplication():
    url1 = "https://techcrunch.com/2026/08/16/new-ai-model/?utm_source=rss&utm_medium=feed"
    url2 = "https://techcrunch.com/2026/08/16/new-ai-model"

    canon1 = ResearchAgent._canonical_url(url1)
    canon2 = ResearchAgent._canonical_url(url2)
    assert canon1 == canon2
    assert "utm_source" not in canon1

    agent = ResearchAgent()
    is_new1, id1 = agent._save_trend_item("Unique AI Model Announcement", url1, "RSS", "Summary 1")
    is_new2, id2 = agent._save_trend_item("Unique AI Model Announcement", url2, "RSS", "Summary 2")

    assert is_new1 is True
    assert is_new2 is False
    assert id1 == id2


def test_title_deduplication():
    agent = ResearchAgent()
    url1 = "https://siteA.com/article1"
    url2 = "https://siteB.com/article2"
    title = "Breakthrough in Autonomous AI Code Agents"

    is_new1, id1 = agent._save_trend_item(title, url1, "Site A", "Summary A")
    is_new2, id2 = agent._save_trend_item(title, url2, "Site B", "Summary B")

    assert is_new1 is True
    assert is_new2 is False
    assert id1 == id2


def test_verifier_duplicate_headline_prevention():
    with Session(engine) as session:
        t1 = TrendItem(title="Breakthrough in Neural Rendering", url="https://a.com", source="RSS", summary="Summary text 1", processed=False)
        t2 = TrendItem(title="Breakthrough in Neural Rendering", url="https://b.com", source="RSS", summary="Summary text 2", processed=False)
        session.add_all([t1, t2])
        session.commit()

    verifier = VerifierAgent()
    # Mock LLM fact extraction to avoid external API calls
    verifier._extract_facts = MagicMock(return_value=("Fact 1", "Takeaway 1"))
    verifier._resolve_source_text = MagicMock(return_value="Detailed article text over 40 characters long for verification.")

    verified_count = verifier.run()
    assert verified_count == 1

    with Session(engine) as session:
        items = session.exec(select(VerifiedNews)).all()
        assert len(items) == 1
        assert items[0].headline == "Breakthrough in Neural Rendering"


def test_scheduler_service_controls():
    service = SchedulerService()
    status = service.get_status()

    assert "enabled" in status
    assert "interval_minutes" in status
    assert "next_run" in status

    # Update schedule
    updated = service.update_schedule(enabled=True, interval_minutes=45.0)
    assert updated["enabled"] is True
    assert updated["interval_minutes"] == 45.0
    assert updated["interval_hours"] == 0.75

    # Test start and stop
    service.start()
    assert service._thread is not None
    assert service._thread.is_alive()

    service.stop()
    assert service._thread is None
