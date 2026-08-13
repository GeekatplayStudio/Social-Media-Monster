import pytest
from src.core.db import init_db
from src.agents.research_agent import ResearchAgent

def test_research_agent_topics_and_telemetry():
    init_db()
    agent = ResearchAgent()
    topics = agent.get_search_topics()
    assert isinstance(topics, list)
    assert len(topics) > 0
