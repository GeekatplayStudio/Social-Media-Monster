import pytest
from src.core.db import init_db
from src.agents.verifier_agent import VerifierAgent

def test_verifier_agent_run():
    init_db()
    agent = VerifierAgent()
    count = agent.run()
    assert isinstance(count, int)
