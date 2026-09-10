# agent-memory Workspace Rules

## Memory Discipline (agent-memory MCP)

This repository implements the two-layer memory architecture (SessionLayer L1 + GraphLayer L2).
When operating in this codebase or pair-programming:
1. Use `agent-memory:memory_recall` to retrieve recent decisions or bugfixes.
2. Use `agent-memory:memory_recall_deep` when architectural or cross-project context is needed.
3. Test offline changes via `python test_offline.py` before committing.\n