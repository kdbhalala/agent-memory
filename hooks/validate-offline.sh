#!/usr/bin/env bash
# Hook: Verify that tests pass offline before commits or pushes
set -e

echo "==> Running offline test suite..."
python3 test_offline.py

echo "==> Running L1 & L2 evaluations..."
python3 eval_l1.py
python3 eval_l2.py

echo "==> Verifying MCP handshake..."
python3 integrate.py test

echo "==> All offline validation checks passed!"
