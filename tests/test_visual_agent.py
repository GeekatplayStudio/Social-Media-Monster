import pytest
from src.agents.visual_agent import VisualAgent

def test_visual_agent_checkpoint_autodetect():
    agent = VisualAgent()
    assert isinstance(agent.active_checkpoint, str)
    assert len(agent.active_checkpoint) > 0
