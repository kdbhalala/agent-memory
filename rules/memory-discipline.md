# Agent Memory Discipline

This repository uses `agent-memory` to maintain shared, two-layer context across all coding assistants (Claude Code, Cursor, Codex, OpenCode, Antigravity, Aider, Windsurf, Cline).

## Protocols

### 1. Recall Before Assuming
Before making architectural decisions, modifying core layers, or refactoring conventions:
- Call `agent-memory:memory_recall` with relevant keywords and project name to check past decisions and bugfixes.
- If high-level architectural or cross-project context is needed, call `agent-memory:memory_recall_deep`.

### 2. Record Verified Decisions
When settling an architectural pattern, fixing a non-trivial bug, or establishing a convention:
- Call `agent-memory:memory_record` with:
  - `text`: Clear, concise description of the decision and reason.
  - `title`: Short title (e.g. "Unified SQLite Schema", "Zero-Dependency Rule").
  - `project`: Target project name (`agent-memory`).

### 3. Multi-Device Sync
- All recorded memories are automatically committed and pushed in the background to your private Git vault (`~/.agent-memory/vault/`).
- To inspect sync status or force immediate compaction:
  - Run `agent-sync status` or `agent-sync sync`.
  - Or invoke the MCP tool `memory_sync`.
