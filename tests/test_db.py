import pytest
from src.core.db import init_db, log_event, load_config

def test_db_init_and_log():
    init_db()
    log_event("TestAgent", "Testing DB initialization and safe event logging", level="INFO")
    cfg = load_config()
    assert isinstance(cfg, dict)
