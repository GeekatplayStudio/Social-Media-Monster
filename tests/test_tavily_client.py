import json
import pytest

from src.core.db import init_db
from src.core.tavily_client import TavilyClient
from src.agents.research_agent import ResearchAgent


@pytest.fixture(autouse=True)
def setup_database(monkeypatch):
    init_db()
    # Never let these tests reach the network or pick up a real developer key.
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    yield


def test_client_reports_unconfigured_without_a_key(monkeypatch):
    client = TavilyClient()
    monkeypatch.setattr(client, "get_api_key", lambda: "")
    assert client.is_configured() is False
    assert client.search("generative ai") == []
    assert client.extract("https://example.com") == ""


def test_placeholder_key_is_not_treated_as_configured(monkeypatch):
    client = TavilyClient()
    monkeypatch.setattr(client, "get_api_key", lambda: "YOUR_TAVILY_API_KEY")
    assert client.is_configured() is False


def test_search_normalizes_results(monkeypatch):
    client = TavilyClient()
    monkeypatch.setattr(client, "get_api_key", lambda: "tvly-test-key")
    monkeypatch.setattr(client, "_post", lambda url, payload: {
        "results": [
            {"title": "Model ships", "url": "https://news.example.com/a",
             "content": "Body text", "score": 0.91, "published_date": "2026-08-01"},
            {"title": "", "url": "https://news.example.com/b", "content": "no title"},
            {"title": "No url", "url": "", "content": "dropped"},
        ]
    })

    results = client.search("ai models")
    assert len(results) == 1, "entries without a title or url must be dropped"
    assert results[0]["url"] == "https://news.example.com/a"
    assert results[0]["score"] == 0.91
    assert results[0]["source"] == "news.example.com"


def test_search_payload_requests_fresh_news(monkeypatch):
    client = TavilyClient()
    monkeypatch.setattr(client, "get_api_key", lambda: "tvly-test-key")
    captured = {}

    def fake_post(url, payload):
        captured.update({"url": url, "payload": payload})
        return {"results": []}

    monkeypatch.setattr(client, "_post", fake_post)
    client.search("local llms", max_results=4)

    assert captured["url"].endswith("/search")
    assert captured["payload"]["topic"] == "news"
    assert captured["payload"]["max_results"] == 4
    assert captured["payload"]["days"] >= 1


def test_extract_returns_body_text(monkeypatch):
    client = TavilyClient()
    monkeypatch.setattr(client, "get_api_key", lambda: "tvly-test-key")
    monkeypatch.setattr(client, "_post", lambda url, payload: {
        "results": [{"url": "https://example.com", "raw_content": "Full article body here."}],
        "failed_results": [],
    })
    assert client.extract("https://example.com") == "Full article body here."


def test_research_agent_falls_back_to_rss_when_tavily_returns_nothing(monkeypatch):
    agent = ResearchAgent()
    monkeypatch.setattr(agent.tavily, "is_configured", lambda: True)
    monkeypatch.setattr(agent.tavily, "search", lambda *a, **k: [])

    called = {}
    monkeypatch.setattr(agent, "_scan_topic_with_google_rss", lambda topic: called.setdefault(topic, 0) or 0)

    agent.last_scan_telemetry["scanned_sources"] = []
    agent._scan_topic_with_tavily("generative ai")
    assert "generative ai" in called, "an empty Tavily response must fall back to RSS"


def test_research_agent_saves_tavily_results(monkeypatch):
    agent = ResearchAgent()
    monkeypatch.setattr(agent.tavily, "is_configured", lambda: True)
    monkeypatch.setattr(agent.tavily, "search", lambda *a, **k: [{
        "title": "Anthropic ships a new model",
        "url": "https://example.com/unique-tavily-test-url",
        "content": "A long article body with real detail about the release.",
        "score": 0.87,
        "published_date": "2026-08-10",
        "source": "example.com",
    }])

    agent.last_scan_telemetry["scanned_sources"] = []
    agent.last_scan_telemetry["found_articles"] = []
    agent._scan_topic_with_tavily("anthropic")

    assert agent.last_scan_telemetry["found_articles"][0]["source"].startswith("Tavily")
