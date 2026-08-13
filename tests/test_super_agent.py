import pytest
from src.core.db import init_db
from src.agents.super_agent import SuperAgent

def test_super_agent_execution_cycle():
    init_db()
    agent = SuperAgent()
    assert agent.mode == "demo"
    result = agent.execute_cycle()
    assert "trends" in result
    assert "qa_results" in result
