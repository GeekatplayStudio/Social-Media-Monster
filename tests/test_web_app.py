import pytest
from fastapi.testclient import TestClient
from src.web.app import app

def test_web_app_endpoints():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    
    topics_res = client.get("/api/topics")
    assert topics_res.status_code == 200
    assert "topics" in topics_res.json()
    
    mcp_res = client.get("/api/mcp/manifest")
    assert mcp_res.status_code == 200
    assert isinstance(mcp_res.json(), list)
