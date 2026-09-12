#!/usr/bin/env python3
"""Backward-compatible entry point for agi-memory MCP server.

Delegates directly to src/agi_memory/mcp_server.py so that existing configurations,
relative path invocations, and older assistant configs continue to work seamlessly.
"""
import sys
from pathlib import Path

# Ensure src/ is in sys.path
_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agi_memory.mcp_server import main

if __name__ == "__main__":
    main()
