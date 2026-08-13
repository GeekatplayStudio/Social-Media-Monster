import uvicorn
from src.core.db import init_db, log_event
from src.web.app import app

def main():
    init_db()
    print("=================================================================")
    print(" [SOCIAL MEDIA MONSTER] AUTONOMOUS AI CONTENT ENGINE")
    print("=================================================================")
    log_event("Main", "Starting Control Dashboard & MCP Server on http://127.0.0.1:8000")
    log_event("Main", "SYSTEM STATUS: HIBERNATING (IDLE). Waiting for manual UI trigger or scheduled timer.")
    
    # Run dashboard server without auto-triggering background scans
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")

if __name__ == "__main__":
    main()
