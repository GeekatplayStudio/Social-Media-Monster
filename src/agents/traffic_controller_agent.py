from sqlmodel import Session, select
from src.core.db import engine, log_event
from src.core.models import PostDraft

class TrafficControllerAgent:
    """
    Traffic Controller Agent:
    Monitors approved post queues and system activity to eliminate unnecessary web traffic.
    Prevents background ResearchAgent web scanning when draft quotas are already met or when
    the Final Content Manager (ValidatorAgent) has already accepted ready-to-publish articles.
    """
    def __init__(self, max_pending_threshold: int = 5):
        self.max_pending_threshold = max_pending_threshold

    def should_allow_web_scan(self) -> bool:
        policy = self.evaluate_traffic_policy()
        return policy.get("allow_scan", True)

    def evaluate_traffic_policy(self) -> dict:
        with Session(engine) as session:
            ready_posts = session.exec(select(PostDraft).where(PostDraft.approved == True)).all()
            unapproved_posts = session.exec(select(PostDraft).where(PostDraft.approved == False)).all()
            total_queue = len(ready_posts) + len(unapproved_posts)

            # If we already have sufficient quality articles accepted, halt web traffic
            if total_queue >= self.max_pending_threshold:
                log_event("TrafficControllerAgent", f"🛑 UNNECESSARY TRAFFIC PREVENTED: Queue has {total_queue} articles. Web scanning disabled to preserve bandwidth.", level="WARNING")
                return {
                    "allow_scan": False,
                    "reason": f"Draft queue quota met ({total_queue}/{self.max_pending_threshold}). Network scans suspended.",
                    "queue_count": total_queue
                }

            log_event("TrafficControllerAgent", f"🟢 TRAFFIC PERMITTED: Active queue count ({total_queue}/{self.max_pending_threshold}). Web scanning allowed.", level="INFO")
            return {
                "allow_scan": True,
                "reason": "Queue below threshold. Research scan permitted.",
                "queue_count": total_queue
            }
