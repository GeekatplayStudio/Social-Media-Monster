import pytest
from src.core.db import init_db
from src.agents.visual_agent import VisualAgent
from src.agents.super_agent import SuperAgent

@pytest.fixture(autouse=True)
def setup_database():
    init_db()

def test_visual_agent_checkpoint_autodetect():
    agent = VisualAgent()
    assert isinstance(agent.active_checkpoint, str)
    assert len(agent.active_checkpoint) > 0

def test_super_agent_cycle_execution():
    super_agent = SuperAgent()
    result = super_agent.execute_cycle()
    assert "trends" in result
    assert "qa_results" in result
