#!/usr/bin/env bash
# Builds (if needed) and starts the SocialMediaMonster dashboard + MCP server.
#
# The build phase is automatic and idempotent: it provisions the virtual environment,
# reinstalls dependencies when requirements.txt changed, and initializes the database.
#
# The engine starts HIBERNATING. Nothing is scanned or posted until you press
# "Execute Cycle" in the dashboard.
#
# Usage:
#   ./scripts/start.sh [--port 8000] [--host 127.0.0.1] [--foreground] [--skip-build]

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
RUN_DIR="$PROJECT_ROOT/.run"
PID_FILE="$RUN_DIR/app.pid"
PORT_FILE="$RUN_DIR/app.port"
LOG_FILE="$RUN_DIR/server.log"

PORT=8000
BIND_HOST="127.0.0.1"
FOREGROUND=0
SKIP_BUILD=0

while [ $# -gt 0 ]; do
    case "$1" in
        --port)       PORT="$2"; shift 2 ;;
        --host)       BIND_HOST="$2"; shift 2 ;;
        --foreground) FOREGROUND=1; shift ;;
        --skip-build) SKIP_BUILD=1; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; MAGENTA='\033[0;35m'; NC='\033[0m'
step() { echo -e "${CYAN}==> $1${NC}"; }
ok()   { echo -e "    ${GREEN}$1${NC}"; }
warn() { echo -e "    ${YELLOW}$1${NC}"; }
die()  { echo -e "${RED}ERROR: $1${NC}" >&2; exit 1; }

echo ""
echo -e "${MAGENTA}=================================================================${NC}"
echo -e "${MAGENTA} SOCIAL MEDIA MONSTER - START${NC}"
echo -e "${MAGENTA}=================================================================${NC}"

cd "$PROJECT_ROOT"
mkdir -p "$RUN_DIR"

# --------------------------------------------------------------- Already running?
if [ -f "$PID_FILE" ]; then
    EXISTING_PID="$(cat "$PID_FILE")"
    if kill -0 "$EXISTING_PID" 2>/dev/null; then
        warn "Already running (PID $EXISTING_PID). Stop it first with ./scripts/stop.sh"
        exit 1
    fi
    rm -f "$PID_FILE"
fi

# --------------------------------------------------------------- Build phase
if [ "$SKIP_BUILD" -eq 0 ]; then
    step "Build phase"
    NEEDS_INSTALL=0

    if [ ! -x "$VENV_PYTHON" ]; then
        warn "No virtual environment found"
        NEEDS_INSTALL=1
    else
        HASH_FILE="$PROJECT_ROOT/.venv/.requirements.sha256"
        if command -v sha256sum >/dev/null 2>&1; then
            CURRENT_HASH="$(sha256sum requirements.txt | awk '{print $1}')"
        else
            CURRENT_HASH="$(shasum -a 256 requirements.txt | awk '{print $1}')"
        fi
        RECORDED_HASH="$(cat "$HASH_FILE" 2>/dev/null || echo '')"
        if [ "$CURRENT_HASH" != "$RECORDED_HASH" ]; then
            warn "requirements.txt changed since last install"
            NEEDS_INSTALL=1
        fi
    fi

    if [ "$NEEDS_INSTALL" -eq 1 ]; then
        "$PROJECT_ROOT/scripts/install.sh" || die "build failed."
    else
        ok "Environment up to date"
        "$VENV_PYTHON" -c "from src.core.db import init_db; init_db()" || die "database init failed."
        ok "Database ready"
    fi
else
    warn "Build phase skipped (--skip-build)"
    [ -x "$VENV_PYTHON" ] || die "no .venv found. Run ./scripts/install.sh first."
fi

# --------------------------------------------------------------- Port availability
if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    die "port $PORT is already in use. Use --port <other> or stop the other process."
fi

export SMM_HOST="$BIND_HOST"
export SMM_PORT="$PORT"
URL="http://${BIND_HOST}:${PORT}"

# --------------------------------------------------------------- Launch
if [ "$FOREGROUND" -eq 1 ]; then
    step "Starting in foreground at $URL  (Ctrl+C to stop)"
    echo ""
    exec "$VENV_PYTHON" "$PROJECT_ROOT/main.py"
fi

step "Starting server at $URL"
nohup "$VENV_PYTHON" "$PROJECT_ROOT/main.py" > "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"
echo "$PORT" > "$PORT_FILE"

# --------------------------------------------------------------- Readiness probe
step "Waiting for the server to become ready"
READY=0
HEALTH=""
for _ in $(seq 1 40); do
    sleep 0.5
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo -e "${RED}ERROR: server exited during startup.${NC}" >&2
        echo "--- last log lines ---" >&2
        tail -n 20 "$LOG_FILE" >&2 || true
        rm -f "$PID_FILE"
        exit 1
    fi
    if HEALTH="$(curl -fsS --max-time 3 "$URL/api/health" 2>/dev/null)"; then
        READY=1
        break
    fi
done

[ "$READY" -eq 1 ] || die "server did not answer /api/health within 20 seconds. Check $LOG_FILE"

ENGINE="rss"
echo "$HEALTH" | grep -q '"research_engine":"tavily"' && ENGINE="tavily"

echo ""
echo -e "${GREEN}=================================================================${NC}"
echo -e "${GREEN} RUNNING${NC}"
echo -e "${GREEN}=================================================================${NC}"
echo ""
echo "  Dashboard       : $URL"
echo "  MCP manifest    : $URL/api/mcp/manifest"
echo "  PID             : $SERVER_PID   (log: .run/server.log)"
if [ "$ENGINE" = "rss" ]; then
    echo "  Research engine : rss   (Tavily key not set - optional)"
else
    echo "  Research engine : tavily"
fi
echo ""
echo -e "${YELLOW}  The engine is HIBERNATING. Open the dashboard and press${NC}"
echo -e "${YELLOW}  'Execute Cycle' to run the pipeline manually.${NC}"
echo ""
echo "  Stop with: ./scripts/stop.sh"
echo ""
