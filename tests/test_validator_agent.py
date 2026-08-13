import pytest
from src.agents.validator_agent import ValidatorAgent

def test_validator_agent_trope_check():
    agent = ValidatorAgent()
    assert agent._contains_ai_tropes("We delve into this tapestry") == True
    assert agent._contains_ai_tropes("Clean natural human text") == False
