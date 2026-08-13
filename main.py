import os
import uvicorn
from src.core.db import init_db, log_event
from src.web.app import app


def main():
    init_db()

    # Host and port are overridable so the start/stop scripts (and container runtimes)
    # can bind somewhere other than the default without editing source.
    host = os.environ.get("SMM_HOST", "127.0.0.1")
    port = int(os.environ.get("SMM_PORT", "8000"))
    log_level = os.environ.get("SMM_LOG_LEVEL", "info")

    print("=================================================================")
    print(" [SOCIAL MEDIA MONSTER] AUTONOMOUS AI CONTENT ENGINE")
    print("=================================================================")
    log_event("Main", f"Starting Control Dashboard & MCP Server on http://{host}:{port}")
    log_event("Main", "SYSTEM STATUS: HIBERNATING (IDLE). Waiting for manual UI trigger or scheduled timer.")

    # Run dashboard server without auto-triggering background scans
    uvicorn.run(app, host=host, port=port, log_level=log_level)


if __name__ == "__main__":
    main()
