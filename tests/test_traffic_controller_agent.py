import pytest
from src.agents.traffic_controller_agent import TrafficControllerAgent

def test_traffic_controller_policy_evaluation():
    agent = TrafficControllerAgent(max_pending_threshold=100)
    policy = agent.evaluate_traffic_policy()
    assert "allow_scan" in policy
    assert "reason" in policy
    assert "queue_count" in policy
    assert isinstance(policy["allow_scan"], bool)
