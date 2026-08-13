import pytest
from src.agents.humanizer_agent import HumanizerAgent

def test_humanizer_agent_tropes_and_ctr():
    agent = HumanizerAgent()
    cleaned = agent._remove_ai_tropes("We delve into this testament to AI")
    assert "delve into" not in cleaned
    score = agent._calculate_ctr_score("10 Secrets of Local LLMs", "Content text")
    assert score > 60.0
