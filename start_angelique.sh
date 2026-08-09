#!/bin/bash
# start_angelique.sh - Bootstrap Angelique autonomous companion
# Handles venv activation, MT5 bridge launch, and main application startup

set -e

# Get project directory
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$PROJECT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}🌟 Starting Angelique...${NC}"

# 1. Activate Python venv
if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}⚙️ Creating Python venv...${NC}"
    python3 -m venv .venv
fi

echo -e "${BLUE}🔧 Activating venv...${NC}"
source .venv/bin/activate

# 2. Install/upgrade dependencies
if [ "$1" = "--fresh" ] || [ "$1" = "-f" ]; then
    echo -e "${BLUE}📦 Installing fresh dependencies...${NC}"
    pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt
else
    echo -e "${BLUE}📦 Checking dependencies...${NC}"
    pip install -q -r requirements.txt 2>/dev/null || pip install -r requirements.txt
fi

# 3. Initialize data directories
if [ ! -d "data" ]; then
    echo -e "${BLUE}📁 Creating data directories...${NC}"
    mkdir -p data/chroma_memory data/logs data/generated_skills
fi

# 4. Check for MT5 bridge
LOG_DIR="$PROJECT_DIR/data/logs"
mkdir -p "$LOG_DIR"

WINE_CMD=""
WINE_ARGS=()
if command -v wine &> /dev/null; then
    WINE_CMD="wine"
    WINE_ARGS=(cmd /c python)
elif command -v wine64 &> /dev/null; then
    WINE_CMD="wine64"
    WINE_ARGS=(cmd /c python)
fi

if [ -n "$WINE_CMD" ]; then
    echo -e "${BLUE}🌉 Checking MT5 bridge...${NC}"
    BRIDGE_SCRIPT="$PROJECT_DIR/skills/trading/engine/mt5_bridge_server.py"
    if [ -f "$BRIDGE_SCRIPT" ]; then
        if ! pgrep -f "mt5_bridge_server.py" > /dev/null 2>&1; then
            echo -e "${YELLOW}🔌 Launching MT5 Bridge in Wine...${NC}"
            if command -v winepath &> /dev/null; then
                BRIDGE_SCRIPT_WIN=$(winepath -w "$BRIDGE_SCRIPT")
            else
                BRIDGE_SCRIPT_WIN="$BRIDGE_SCRIPT"
            fi
            "$WINE_CMD" "${WINE_ARGS[@]}" "$BRIDGE_SCRIPT_WIN" > "$LOG_DIR/mt5_bridge.log" 2>&1 &
            sleep 3
        else
            echo -e "${GREEN}✅ MT5 Bridge already running${NC}"
        fi
    fi
else
    echo -e "${RED}❌ Wine not available. MT5 bridge cannot be launched, and MT5 features will be disabled.${NC}"
fi

# 5. Make sure database is initialized
echo -e "${BLUE}💾 Initializing memory system...${NC}"
python3 -c "from brain.memory_manager import init_db; init_db(); print('✅ Memory system initialized')" 2>/dev/null || true

# 6. Start Angelique
echo -e "${GREEN}✨ Launching Angelique (GUI)...${NC}"
export ANGELIQUE_LAUNCHED=1
python3 launcher.py --gui

# Cleanup on exit
trap "echo -e '${BLUE}💤 Angelique shutting down...${NC}'" EXIT
