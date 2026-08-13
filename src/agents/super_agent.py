import time
from datetime import datetime
from sqlmodel import Session, select
from src.core.db import engine, init_db, log_event, load_config
from src.core.models import SystemSetting
from src.core.state_manager import TemporalStateManager
from src.agents.research_agent import ResearchAgent
from src.agents.verifier_agent import VerifierAgent
from src.agents.writer_agent import WriterAgent
from src.agents.humanizer_agent import HumanizerAgent
from src.agents.validator_agent import ValidatorAgent
from src.agents.visual_agent import VisualAgent
from src.agents.publisher_agent import PublisherAgent

class SuperAgent:
    """
    Super Agent Master Controller:
    Initializes strictly into HIBERNATING (IDLE) mode.
    Supports Emergency Stop (stop_requested) to halt all background agent tasks instantly.
    Does NOT auto-trigger unrequested scans on startup.
    """
    def __init__(self):
        init_db()
        self.config = load_config()
        self.mode = self.config.get("system", {}).get("mode", "demo")
        self.active_persona = self.config.get("personas", {}).get("active_persona", "tech_visionary")

        self.temporal_state = TemporalStateManager()
        self.stop_requested = False

        # Sub-agents
        self.research_agent = ResearchAgent()
        self.verifier_agent = VerifierAgent()
        self.writer_agent = WriterAgent()
        self.humanizer_agent = HumanizerAgent()
        self.validator_agent = ValidatorAgent()
        self.visual_agent = VisualAgent()
        self.publisher_agent = PublisherAgent()

        self.telemetry = {
            "current_stage": "HIBERNATING (IDLE)",
            "active_agent": "None",
            "active_queries": [],
            "scanned_sources": [],
            "found_articles": [],
            "formatting_status": "Ready",
            "mode": self.mode,
            "schedule_hours": self.get_schedule_hours(),
            "max_articles": self.get_max_articles(),
            "last_updated": datetime.now().isoformat()
        }

        # Clear any stale checkpoint on initialization so it stays strictly hibernating
        self.temporal_state.clear_checkpoint()

    def emergency_stop(self):
        self.stop_requested = True
        self.telemetry["current_stage"] = "STOPPED (IDLE)"
        self.telemetry["active_agent"] = "None"
        self.temporal_state.clear_checkpoint()
        log_event("SuperAgent", "EMERGENCY STOP ACTIVATED. All background agents halted immediately by user.", level="WARNING")

    def get_schedule_hours(self) -> float:
        with Session(engine) as session:
            setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "schedule_interval_hours")).first()
            if setting and setting.value:
                try:
                    return float(setting.value)
                except ValueError:
                    pass
        return 6.0

    def get_max_articles(self) -> int:
        with Session(engine) as session:
            setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "max_articles_per_cycle")).first()
            if setting and setting.value:
                try:
                    return int(setting.value)
                except ValueError:
                    pass
        return 2

    def update_mode(self, new_mode: str):
        self.mode = new_mode
        self.telemetry["mode"] = new_mode
        log_event("SuperAgent", f"System operating mode changed to: {new_mode.upper()}")

    def execute_cycle(self):
        self.stop_requested = False
        sched_hours = self.get_schedule_hours()
        max_arts = self.get_max_articles()
        
        self.telemetry["schedule_hours"] = sched_hours
        self.telemetry["max_articles"] = max_arts

        log_event("SuperAgent", f"=== STARTING PIPELINE CYCLE (MODE: {self.mode.upper()}, SCHEDULE: Every {sched_hours} hrs) ===", level="INFO")

        try:
            # Stage 1: Research Agent
            if self.stop_requested: return self._handle_stopped()
            self.telemetry["current_stage"] = "RESEARCH"
            self.telemetry["active_agent"] = "ResearchAgent"
            self.temporal_state.save_checkpoint("RESEARCH", {"queries": self.telemetry["active_queries"]})
            new_trends = self.research_agent.run()
            
            self.telemetry["active_queries"] = self.research_agent.last_scan_telemetry.get("active_queries", [])
            self.telemetry["scanned_sources"] = self.research_agent.last_scan_telemetry.get("scanned_sources", [])
            self.telemetry["found_articles"] = self.research_agent.last_scan_telemetry.get("found_articles", [])

            # Stage 2: Verifier Agent
            if self.stop_requested: return self._handle_stopped()
            self.telemetry["current_stage"] = "VERIFICATION"
            self.telemetry["active_agent"] = "VerifierAgent"
            self.temporal_state.save_checkpoint("VERIFICATION", {"trends": new_trends})
            verified_items = self.verifier_agent.run()

            # Stage 3: Writer Agent
            if self.stop_requested: return self._handle_stopped()
            self.telemetry["current_stage"] = "COPYWRITING"
            self.telemetry["active_agent"] = "WriterAgent"
            self.temporal_state.save_checkpoint("COPYWRITING", {"verified": verified_items})
            drafts = self.writer_agent.run(target_persona_key=self.active_persona)

            # Stage 4: Humanizer Agent
            if self.stop_requested: return self._handle_stopped()
            self.telemetry["current_stage"] = "HUMANIZING"
            self.telemetry["active_agent"] = "HumanizerAgent"
            self.temporal_state.save_checkpoint("HUMANIZING", {"drafts": drafts})
            optimized = self.humanizer_agent.run()

            # Stage 5: Validator & QA Agent
            if self.stop_requested: return self._handle_stopped()
            self.telemetry["current_stage"] = "QA_VALIDATION"
            self.telemetry["active_agent"] = "ValidatorAgent"
            self.temporal_state.save_checkpoint("QA_VALIDATION", {"optimized": optimized})
            qa_results = self.validator_agent.run()

            # Stage 6: Visual Studio Agent
            if self.stop_requested: return self._handle_stopped()
            self.telemetry["current_stage"] = "VISUAL_GENERATION"
            self.telemetry["active_agent"] = "VisualAgent"
            self.temporal_state.save_checkpoint("VISUAL_GENERATION", {"qa": qa_results})
            visuals = self.visual_agent.run()

            # Stage 7: Publisher Agent
            if self.stop_requested: return self._handle_stopped()
            if self.mode == "production":
                self.telemetry["current_stage"] = "PUBLISHING"
                self.telemetry["active_agent"] = "PublisherAgent"
                self.temporal_state.save_checkpoint("PUBLISHING", {"visuals": visuals})
                published = self.publisher_agent.run()
            else:
                self.telemetry["current_stage"] = "DEMO_COMPLETED"
                self.telemetry["active_agent"] = "PublisherAgent (Skipped in Demo)"
                log_event("SuperAgent", "DEMO MODE: Generated drafts and visuals. Live posting bypassed.", level="INFO")
                published = 0

            self.temporal_state.save_checkpoint("COMPLETED", {"published": published})
            self.telemetry["last_updated"] = datetime.now().isoformat()
            log_event("SuperAgent", f"=== PIPELINE CYCLE COMPLETED ===", level="SUCCESS")

            return {
                "mode": self.mode, "trends": new_trends, "verified": verified_items,
                "drafts": drafts, "optimized": optimized, "qa_results": qa_results,
                "visuals": visuals, "published": published
            }
        except Exception as e:
            self.telemetry["current_stage"] = "ERROR"
            log_event("SuperAgent", f"Error in Super Agent execution cycle: {e}", level="ERROR")
            return {"error": str(e)}

    def _handle_stopped(self):
        log_event("SuperAgent", "Pipeline execution halted due to Emergency Stop request.", level="WARNING")
        self.telemetry["current_stage"] = "STOPPED (IDLE)"
        self.telemetry["active_agent"] = "None"
        return {"status": "stopped", "message": "Pipeline halted by user"}
