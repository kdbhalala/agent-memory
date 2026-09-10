#!/usr/bin/env bash
# ==============================================================================
# agent-memory - Turnkey Zero-Dependency Installer
# Works on macOS and Linux (bash/zsh)
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/kdbhalala/agent-memory/main/install.sh | bash
#   or from a local clone: ./install.sh
# ==============================================================================

set -e

BOLD="\033[1m"
GREEN="\033[0;32m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m" # No Color

echo -e "${BOLD}${BLUE}"
echo "========================================================================"
echo "          agent-memory: Universal AI Coding Assistant Memory            "
echo "========================================================================"
echo -e "${NC}"

# 1. Detect Python 3.10+
echo -e "${BOLD}[1/6] Checking Python runtime...${NC}"
PYTHON_BIN=""
for cmd in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        MAJOR=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null || true)
        MINOR=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || true)
        if [ "$MAJOR" = "3" ] && [ "$MINOR" -ge 10 ]; then
            PYTHON_BIN=$(command -v "$cmd")
            echo -e "  ${GREEN}✓${NC} Found Python $VER ($PYTHON_BIN)"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "  ${RED}✗ Python 3.10 or newer is required, but was not found.${NC}"
    echo "  Please install Python 3.10+ (e.g. brew install python3 or apt install python3) and retry."
    exit 1
fi

# Verify built-in sqlite3 and json
$PYTHON_BIN -c "import sqlite3, json, sys; sys.exit(0)" 2>/dev/null || {
    echo -e "  ${RED}✗ Python sqlite3 module is missing or corrupt.${NC}"
    exit 1
}

# 2. Determine installation location
INSTALL_ROOT="$HOME/.agent-memory"
SRC_DIR="$INSTALL_ROOT/src"
BIN_DIR="$HOME/.local/bin"

# Check if script is run from an existing local git clone of agent-memory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo "")"
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/mcp_server.py" ] && [ -f "$SCRIPT_DIR/integrate.py" ]; then
    TARGET_SRC="$SCRIPT_DIR"
    echo -e "\n${BOLD}[2/6] Using local repository at:${NC} $TARGET_SRC"
else
    TARGET_SRC="$SRC_DIR"
    echo -e "\n${BOLD}[2/6] Setting up source repository at:${NC} $TARGET_SRC"
    mkdir -p "$INSTALL_ROOT"
    if [ -d "$TARGET_SRC/.git" ]; then
        echo "  Updating existing installation via git pull..."
        (cd "$TARGET_SRC" && git pull --quiet origin main 2>/dev/null || true)
    else
        echo "  Cloning agent-memory repository..."
        rm -rf "$TARGET_SRC"
        git clone --depth 1 https://github.com/kdbhalala/agent-memory.git "$TARGET_SRC" --quiet
    fi
fi

# 3. Setup CLI executables in ~/.local/bin
echo -e "\n${BOLD}[3/6] Installing CLI binaries into $BIN_DIR...${NC}"
mkdir -p "$BIN_DIR"

create_wrapper() {
    local cmd_name="$1"
    local script_file="$2"
    local wrapper="$BIN_DIR/$cmd_name"

    cat <<WRAPPER > "$wrapper"
#!/usr/bin/env bash
exec "$PYTHON_BIN" "$TARGET_SRC/$script_file" "\$@"
WRAPPER
    chmod +x "$wrapper"
    echo -e "  ${GREEN}✓${NC} $cmd_name -> $TARGET_SRC/$script_file"
}

create_wrapper "agent-memory" "mcp_server.py"
create_wrapper "agent-integrate" "integrate.py"
create_wrapper "agent-hooks" "hooks.py"
create_wrapper "agent-recall" "recall.py"
create_wrapper "agent-sync" "sync.py"

# 4. Initialize Vault
echo -e "\n${BOLD}[4/6] Initializing canonical vault storage...${NC}"
"$PYTHON_BIN" -c "
import sys
sys.path.insert(0, '$TARGET_SRC')
import vault
v_dir = vault.init_vault()
print(f'  ✓ Vault initialized at {v_dir}')
"

# 5. Run Turnkey Multi-Assistant Integration & Hooks
echo -e "\n${BOLD}[5/6] Detecting and configuring coding assistants...${NC}"
"$PYTHON_BIN" "$TARGET_SRC/integrate.py" install all --python "$PYTHON_BIN" --server "$TARGET_SRC/mcp_server.py"

# 6. Verify stdio MCP Protocol Handshake
echo -e "\n${BOLD}[6/6] Verifying MCP server stdio protocol...${NC}"
"$PYTHON_BIN" "$TARGET_SRC/integrate.py" test --python "$PYTHON_BIN" --server "$TARGET_SRC/mcp_server.py"

# Check PATH
PATH_OK=false
case ":$PATH:" in
    *":$BIN_DIR:"*) PATH_OK=true ;;
esac

echo -e "\n${BOLD}${GREEN}========================================================================${NC}"
echo -e "${BOLD}${GREEN}           agent-memory successfully installed and active!             ${NC}"
echo -e "${BOLD}${GREEN}========================================================================${NC}"

if [ "$PATH_OK" = false ]; then
    echo -e "\n${YELLOW}Notice: $BIN_DIR is not in your current PATH.${NC}"
    echo "Add it to your shell configuration file (~/.zshrc or ~/.bashrc):"
    echo -e "  ${BOLD}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
fi

echo -e "\nQuick Verification Commands:"
echo -e "  ${BOLD}agent-integrate status${NC}     # Check assistant status"
echo -e "  ${BOLD}agent-recall \"auth\"${NC}        # Query working memory"
echo -e "  ${BOLD}agent-sync status${NC}          # Check Git vault sync"
echo ""
