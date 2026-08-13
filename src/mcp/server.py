import json
from typing import Dict, Any, List
from sqlmodel import Session, select, desc
from src.core.db import engine, log_event
from src.core.models import PostDraft, PersonaProfile, SystemLog, SystemSetting
from src.agents.super_agent import SuperAgent

class SocialMediaMonsterMCP:
    """
    Model Context Protocol (MCP) Server Interface:
    Exposes standardized agent tools for external LLMs, subagents, and IDE protocol tools.
    """
    def __init__(self, super_agent: SuperAgent = None):
        self.super_agent = super_agent if super_agent else SuperAgent()

    def get_tools_manifest(self) -> List[Dict[str, Any]]:
        """
        Returns the MCP tools manifest describing available agent tools.
        """
        return [
            {
                "name": "get_system_status",
                "description": "Get current SocialMediaMonster mode, active persona, and live telemetry radar state.",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "trigger_scan",
                "description": "Trigger targeted internet search across Google News RSS and tech feeds for specific subjects.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topics": {"type": "string", "description": "Comma-separated topics to search for"}
                    }
                }
            },
            {
                "name": "trigger_full_cycle",
                "description": "Execute a complete end-to-end Super Agent pipeline cycle (Research -> Verify -> Write -> Validate -> ComfyUI -> Publish).",
                "parameters": {"type": "object", "properties": {}}
            },
            {
                "name": "list_posts",
                "description": "List generated social media posts with CTR scores, AI humanization scores, and platforms.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "description": "Filter by status: draft, approved, published"}
                    }
                }
            },
            {
                "name": "approve_post",
                "description": "Approve a post draft by ID for publication.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "post_id": {"type": "integer", "description": "ID of post to approve"}
                    },
                    "required": ["post_id"]
                }
            }
        ]

    def call_tool(self, name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Executes an MCP tool invocation by name.
        """
        arguments = arguments or {}
        log_event("MCP_Server", f"Tool call received: {name}({arguments})")

        if name == "get_system_status":
            return {
                "mode": self.super_agent.mode,
                "telemetry": self.super_agent.telemetry,
                "persona": self.super_agent.active_persona
            }

        elif name == "trigger_scan":
            topics = arguments.get("topics")
            if topics:
                with Session(engine) as session:
                    setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "search_topics")).first()
                    if setting:
                        setting.value = topics
                        session.add(setting)
                        session.commit()
            count = self.super_agent.research_agent.run()
            return {"status": "scan_completed", "items_found": count}

        elif name == "trigger_full_cycle":
            result = self.super_agent.execute_cycle()
            return {"status": "cycle_completed", "result": result}

        elif name == "list_posts":
            target_status = arguments.get("status")
            with Session(engine) as session:
                query = select(PostDraft)
                if target_status:
                    query = query.where(PostDraft.status == target_status)
                posts = session.exec(query.order_by(desc(PostDraft.id)).limit(10)).all()
                return {"posts": [p.dict() for p in posts]}

        elif name == "approve_post":
            post_id = arguments.get("post_id")
            with Session(engine) as session:
                post = session.get(PostDraft, post_id)
                if post:
                    post.status = "approved"
                    session.add(post)
                    session.commit()
                    if self.super_agent.mode == "production":
                        self.super_agent.publisher_agent.run()
                    return {"status": "approved", "post_id": post_id}
            return {"error": "Post not found"}

        return {"error": f"Unknown tool: {name}"}
