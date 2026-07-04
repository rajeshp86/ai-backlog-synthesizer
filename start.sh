#!/usr/bin/env bash
# =============================================================================
# Backlog Synthesizer — start everything in one command
#
# Usage:
#   chmod +x start.sh
#   ./start.sh
#
# What it does:
#   1. Activates the Python 3.13 venv (has mcp + all deps)
#   2. Loads .env
#   3. Starts Streamlit on port 8502
#
# Press Ctrl+C to stop.
# =============================================================================

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

info() { echo -e "${CYAN}[start]${NC} $*"; }
ok()   { echo -e "${GREEN}[start]${NC} $*"; }
warn() { echo -e "${YELLOW}[start]${NC} $*"; }

# ── 1. Pick best available venv (highest Python version wins) ───────────────
# requirements.txt uses PEP 508 markers so mcp installs automatically on 3.10+.
# Priority: venv313 > venv312 > venv311 > venv310 > venv (3.9 fallback)
VENV=""
for _candidate in .venv venv313 venv312 venv311 venv310 venv; do
    if [ -f "$ROOT/$_candidate/bin/activate" ]; then
        VENV="$ROOT/$_candidate"
        break
    fi
done

if [ -z "$VENV" ]; then
    echo "ERROR: No venv found."
    echo "Create one: python3.13 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

_PY_VER=$("$VENV/bin/python" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "?")
if "$VENV/bin/python" -c "import mcp" 2>/dev/null; then
    ok "Using $VENV (Python $_PY_VER + MCP packages)"
else
    warn "Using $VENV (Python $_PY_VER) — MCP unavailable. Upgrade to Python 3.10+ for full MCP support."
fi

source "$VENV/bin/activate"
ok "Activated $VENV"

# ── 2. Load .env ─────────────────────────────────────────────────────────────
if [ -f "$ROOT/.env" ]; then
    set -a
    source "$ROOT/.env"
    set +a
    ok "Loaded .env"
else
    warn ".env not found — using system environment variables only"
fi

# ── 3. Start Streamlit ───────────────────────────────────────────────────────
PORT="${PORT:-8502}"
info "Starting Streamlit on http://localhost:${PORT} …"
echo ""
echo -e "  ${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${GREEN}  Backlog Synthesizer${NC}"
echo -e "  ${GREEN}  http://localhost:${PORT}${NC}"
echo -e "  ${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

cd "$ROOT"
exec streamlit run app.py \
    --server.port "$PORT" \
    --server.headless true \
    --browser.gatherUsageStats false
