import pytest
from src.core.db import init_db
from src.mcp.server import SocialMediaMonsterMCP

def test_mcp_server_manifest_and_calls():
    init_db()
    mcp = SocialMediaMonsterMCP()
    manifest = mcp.get_tools_manifest()
    assert isinstance(manifest, list)
    assert len(manifest) >= 4
    
    status_resp = mcp.call_tool("get_system_status")
    assert "mode" in status_resp
