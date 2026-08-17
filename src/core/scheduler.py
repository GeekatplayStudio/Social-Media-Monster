"""
Scheduler Service: Background interval post scheduler.

Manages automated recurring news collection, copywriting, visual creation,
and website publishing cycles on a configurable interval (every XXX minutes/hours).
"""
import time
import threading
from datetime import datetime, timedelta
from sqlmodel import Session, select
from src.core.db import engine, log_event
from src.core.models import SystemSetting


class SchedulerService:
    """
    Background scheduler service for SocialMediaMonster.
    """

    def __init__(self, super_agent=None):
        self.super_agent = super_agent
        self.enabled = False
        self.interval_minutes = 60.0
        self.last_run = None
        self.next_run = None

        self._thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Load persisted settings from database
        self._load_settings()

    def set_super_agent(self, super_agent):
        self.super_agent = super_agent

    def _load_settings(self):
        # This module builds its singleton at import time, which happens before
        # init_db() has created the schema on a fresh install. Missing tables must
        # leave the defaults in place rather than crash the whole application.
        try:
            self._read_settings()
        except Exception:
            pass

    def _read_settings(self):
        with Session(engine) as session:
            en_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "scheduler_enabled")).first()
            if en_setting and en_setting.value:
                self.enabled = en_setting.value.lower() == "true"

            min_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "schedule_interval_minutes")).first()
            if min_setting and min_setting.value:
                try:
                    self.interval_minutes = float(min_setting.value)
                except ValueError:
                    pass
            else:
                # Check legacy schedule_interval_hours if minutes setting not present
                h_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "schedule_interval_hours")).first()
                if h_setting and h_setting.value:
                    try:
                        self.interval_minutes = float(h_setting.value) * 60.0
                    except ValueError:
                        pass

    def get_status(self) -> dict:
        self._load_settings()
        now = datetime.now()
        next_run_iso = self.next_run.isoformat() if self.next_run else (now + timedelta(minutes=self.interval_minutes)).isoformat()
        return {
            "enabled": self.enabled,
            "interval_minutes": self.interval_minutes,
            "interval_hours": round(self.interval_minutes / 60.0, 2),
            "last_run": self.last_run.isoformat() if self.last_run else None,
            "next_run": next_run_iso,
            "is_running": self._thread is not None and self._thread.is_alive()
        }

    def update_schedule(self, enabled: bool = None, interval_minutes: float = None, interval_hours: float = None) -> dict:
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)
            
            if interval_minutes is not None and interval_minutes > 0:
                self.interval_minutes = float(interval_minutes)
            elif interval_hours is not None and interval_hours > 0:
                self.interval_minutes = float(interval_hours) * 60.0

            # Persist to database
            with Session(engine) as session:
                en_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "scheduler_enabled")).first()
                if not en_setting:
                    en_setting = SystemSetting(key_name="scheduler_enabled", value=str(self.enabled).lower())
                else:
                    en_setting.value = str(self.enabled).lower()
                session.add(en_setting)

                min_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "schedule_interval_minutes")).first()
                if not min_setting:
                    min_setting = SystemSetting(key_name="schedule_interval_minutes", value=str(self.interval_minutes))
                else:
                    min_setting.value = str(self.interval_minutes)
                session.add(min_setting)

                # Keep legacy hours setting in sync
                h_setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "schedule_interval_hours")).first()
                hours_val = str(round(self.interval_minutes / 60.0, 2))
                if not h_setting:
                    h_setting = SystemSetting(key_name="schedule_interval_hours", value=hours_val)
                else:
                    h_setting.value = hours_val
                session.add(h_setting)

                session.commit()

            self.next_run = datetime.now() + timedelta(minutes=self.interval_minutes)
            log_event("Scheduler", f"Schedule updated: Active={self.enabled}, Interval={self.interval_minutes} mins ({round(self.interval_minutes/60.0, 2)} hrs)", level="SUCCESS")

        return self.get_status()

    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return

            self._stop_event.clear()
            self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="BackgroundSchedulerThread")
            self.next_run = datetime.now() + timedelta(minutes=self.interval_minutes)
            self._thread.start()
            log_event("Scheduler", f"Background Post Scheduler started. Interval: Every {self.interval_minutes} mins.", level="INFO")

    def stop(self):
        with self._lock:
            self._stop_event.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)
            self._thread = None
            log_event("Scheduler", "Background Post Scheduler stopped.", level="INFO")

    def _worker_loop(self):
        while not self._stop_event.is_set():
            now = datetime.now()
            if self.enabled and self.next_run and now >= self.next_run:
                if self.super_agent and not getattr(self.super_agent, "stop_requested", False):
                    log_event("Scheduler", f"⏰ SCHEDULER TRIGGERED: Executing news pipeline cycle (Every {self.interval_minutes} mins)...", level="INFO")
                    try:
                        self.last_run = datetime.now()
                        self.super_agent.execute_cycle()
                    except Exception as e:
                        log_event("Scheduler", f"Error during scheduled pipeline execution: {e}", level="ERROR")
                self.next_run = datetime.now() + timedelta(minutes=self.interval_minutes)

            # Sleep in 1-second intervals to allow prompt shutdown on stop()
            time.sleep(1)


# Global singleton instance
scheduler_service = SchedulerService()
