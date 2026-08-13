import json
from datetime import datetime
from sqlmodel import Session, select
from src.core.db import engine, log_event
from src.core.models import SystemSetting

class TemporalStateManager:
    """
    Temporal-like Persistent State & Worker Restoration Engine:
    Persists pipeline stage checkpoints, active worker state, and task payloads into SQLite.
    Restores workers and execution state seamlessly if the server restarts or webpage closes.
    """
    def __init__(self):
        pass

    def save_checkpoint(self, stage: str, worker_data: dict):
        with Session(engine) as session:
            payload = {
                "stage": stage,
                "timestamp": datetime.now().isoformat(),
                "worker_data": worker_data
            }
            setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "temporal_checkpoint")).first()
            val_str = json.dumps(payload)
            if not setting:
                setting = SystemSetting(key_name="temporal_checkpoint", value=val_str)
            else:
                setting.value = val_str
            session.add(setting)
            session.commit()
            log_event("TemporalState", f"Saved state checkpoint: [{stage}]", level="INFO")

    def restore_checkpoint(self) -> dict:
        with Session(engine) as session:
            setting = session.exec(select(SystemSetting).where(SystemSetting.key_name == "temporal_checkpoint")).first()
            if setting and setting.value:
                try:
                    data = json.loads(setting.value)
                    log_event("TemporalState", f"Restored worker state checkpoint from [{data.get('stage')}] ({data.get('timestamp')})", level="SUCCESS")
                    return data
                except Exception as e:
                    log_event("TemporalState", f"Failed to restore checkpoint: {e}", level="ERROR")
        return {"stage": "IDLE", "worker_data": {}}

    def clear_checkpoint(self):
        self.save_checkpoint("IDLE", {})
