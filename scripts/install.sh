#!/usr/bin/env bash
# Installs SocialMediaMonster: virtual environment, dependencies, database.
# Safe to re-run; existing data is never deleted.
#
# Usage: ./scripts/install.sh [--force]

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PATH="$PROJECT_ROOT/.venv"
VENV_PYTHON="$VENV_PATH/bin/python"

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; MAGENTA='\033[0;35m'; NC='\033[0m'
step() { echo -e "${CYAN}==> $1${NC}"; }
ok()   { echo -e "    ${GREEN}$1${NC}"; }
warn() { echo -e "    ${YELLOW}$1${NC}"; }
die()  { echo -e "${RED}ERROR: $1${NC}" >&2; exit 1; }

echo ""
echo -e "${MAGENTA}=================================================================${NC}"
echo -e "${MAGENTA} SOCIAL MEDIA MONSTER - INSTALL${NC}"
echo -e "${MAGENTA}=================================================================${NC}"

cd "$PROJECT_ROOT"

# --------------------------------------------------------------- 1. Python check
step "Checking Python interpreter"
PYTHON_CMD=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
            PYTHON_CMD="$candidate"
            ok "Found $("$candidate" --version 2>&1) ($(command -v "$candidate"))"
            break
        fi
    fi
done
[ -n "$PYTHON_CMD" ] || die "Python 3.10+ not found on PATH."

# --------------------------------------------------------------- 2. Virtual environment
step "Preparing virtual environment (.venv)"
if [ "$FORCE" -eq 1 ] && [ -d "$VENV_PATH" ]; then
    warn "--force specified, removing existing .venv"
    rm -rf "$VENV_PATH"
fi

if [ ! -x "$VENV_PYTHON" ]; then
    "$PYTHON_CMD" -m venv "$VENV_PATH" || die "venv creation failed."
    ok "Created $VENV_PATH"
else
    ok "Reusing existing virtual environment"
fi

# --------------------------------------------------------------- 3. Dependencies
step "Installing dependencies from requirements.txt"
"$VENV_PYTHON" -m pip install --upgrade pip --quiet
"$VENV_PYTHON" -m pip install -r "$PROJECT_ROOT/requirements.txt" || die "dependency installation failed."
ok "Dependencies installed"

# Record what was installed so start.sh can detect a stale environment.
if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$PROJECT_ROOT/requirements.txt" | awk '{print $1}' > "$VENV_PATH/.requirements.sha256"
elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$PROJECT_ROOT/requirements.txt" | awk '{print $1}' > "$VENV_PATH/.requirements.sha256"
fi

# --------------------------------------------------------------- 4. Database
step "Initializing SQLite database"
"$VENV_PYTHON" -c "from src.core.db import init_db; init_db(); print('    database ready')" \
    || die "database init failed."

# --------------------------------------------------------------- 5. Encryption key
step "Checking credential encryption key"
if [ -f "$PROJECT_ROOT/.env.secret" ]; then
    ok "Existing .env.secret found (keep this file safe and out of git)"
else
    "$VENV_PYTHON" -c "from src.core.security import SecurityManager; SecurityManager()"
    chmod 600 "$PROJECT_ROOT/.env.secret" 2>/dev/null || true
    ok "Generated a new .env.secret master key"
fi

chmod +x "$PROJECT_ROOT/scripts/"*.sh 2>/dev/null || true

echo ""
echo -e "${GREEN}=================================================================${NC}"
echo -e "${GREEN} INSTALL COMPLETE${NC}"
echo -e "${GREEN}=================================================================${NC}"
echo ""
echo " Start the engine :  ./scripts/start.sh"
echo " Stop the engine  :  ./scripts/stop.sh"
echo " Run the tests    :  ./.venv/bin/python -m pytest tests/ -q"
echo ""
echo " Tavily is OPTIONAL. Without a key the ResearchAgent uses Google News RSS."
echo " To enable it, open the dashboard -> Provider Config -> Tavily Research API Key."
echo ""
