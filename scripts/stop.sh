#!/usr/bin/env bash
# Stops the running SocialMediaMonster server.
#
# Sends an in-app emergency stop first so any running agent cycle halts cleanly, then
# terminates the recorded process. Falls back to whatever is listening on the port.
#
# Usage: ./scripts/stop.sh [--port 8000] [--force]

set -uo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$PROJECT_ROOT/.run"
PID_FILE="$RUN_DIR/app.pid"
PORT_FILE="$RUN_DIR/app.port"

PORT=0
FORCE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --port)  PORT="$2"; shift 2 ;;
        --force) FORCE=1; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; MAGENTA='\033[0;35m'; NC='\033[0m'
step() { echo -e "${CYAN}==> $1${NC}"; }
ok()   { echo -e "    ${GREEN}$1${NC}"; }
warn() { echo -e "    ${YELLOW}$1${NC}"; }

echo ""
echo -e "${MAGENTA}=================================================================${NC}"
echo -e "${MAGENTA} SOCIAL MEDIA MONSTER - STOP${NC}"
echo -e "${MAGENTA}=================================================================${NC}"

# Resolve the port: explicit flag, then the file written by start.sh, then default.
if [ "$PORT" -eq 0 ]; then
    if [ -f "$PORT_FILE" ]; then PORT="$(cat "$PORT_FILE")"; else PORT=8000; fi
fi

# --------------------------------------------------------------- Graceful agent halt
if [ "$FORCE" -eq 0 ]; then
    step "Requesting emergency stop of background agents"
    if curl -fsS --max-time 5 -X POST "http://127.0.0.1:$PORT/api/stop" >/dev/null 2>&1; then
        ok "Agents halted"
        sleep 0.7
    else
        warn "Server did not answer on port $PORT (it may already be down)"
    fi
fi

# --------------------------------------------------------------- Resolve target PID
TARGET_PID=""
if [ -f "$PID_FILE" ]; then
    RECORDED="$(cat "$PID_FILE")"
    if [ -n "$RECORDED" ] && kill -0 "$RECORDED" 2>/dev/null; then
        TARGET_PID="$RECORDED"
        ok "Found running server from PID file: $TARGET_PID"
    else
        warn "PID file is stale, cleaning up"
        rm -f "$PID_FILE"
    fi
fi

if [ -z "$TARGET_PID" ] && command -v lsof >/dev/null 2>&1; then
    TARGET_PID="$(lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -n1)"
    [ -n "$TARGET_PID" ] && ok "Found process listening on port $PORT: PID $TARGET_PID"
fi

if [ -z "$TARGET_PID" ]; then
    echo ""
    warn "Nothing to stop - no server running on port $PORT."
    echo ""
    exit 0
fi

# --------------------------------------------------------------- Terminate
step "Stopping process $TARGET_PID"
kill "$TARGET_PID" 2>/dev/null || true

STOPPED=0
for _ in $(seq 1 20); do
    sleep 0.25
    if ! kill -0 "$TARGET_PID" 2>/dev/null; then STOPPED=1; break; fi
done

if [ "$STOPPED" -eq 0 ]; then
    warn "Process did not exit on SIGTERM, sending SIGKILL"
    kill -9 "$TARGET_PID" 2>/dev/null || true
    sleep 0.5
    kill -0 "$TARGET_PID" 2>/dev/null || STOPPED=1
fi

rm -f "$PID_FILE" "$PORT_FILE"

echo ""
if [ "$STOPPED" -eq 1 ]; then
    echo -e "${GREEN}=================================================================${NC}"
    echo -e "${GREEN} STOPPED${NC}"
    echo -e "${GREEN}=================================================================${NC}"
else
    echo -e "${YELLOW}WARNING: process $TARGET_PID may still be terminating.${NC}"
fi
echo ""
