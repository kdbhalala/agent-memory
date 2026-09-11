#!/usr/bin/env bash
# Hook: Verify that tests pass offline before commits or pushes
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$SCRIPT_DIR/src:$PYTHONPATH"

echo "==> Running offline test suite..."
python3 "$SCRIPT_DIR/tests/test_offline.py"

echo "==> Running L1 & L2 evaluations..."
python3 "$SCRIPT_DIR/tests/eval_l1.py"
python3 "$SCRIPT_DIR/tests/eval_l2.py"

echo "==> Verifying MCP handshake..."
python3 -m agi_memory.integrate test

echo "==> All offline validation checks passed!"
