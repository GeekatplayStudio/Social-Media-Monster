import pytest
from src.core.db import init_db
from src.agents.publisher_agent import PublisherAgent

def test_publisher_agent_run():
    init_db()
    agent = PublisherAgent()
    count = agent.run()
    assert isinstance(count, int)
