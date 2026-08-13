import pytest
from src.core.db import init_db
from src.agents.writer_agent import WriterAgent

def test_writer_agent_run():
    init_db()
    agent = WriterAgent()
    count = agent.run()
    assert isinstance(count, int)
