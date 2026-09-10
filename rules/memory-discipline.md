# Agent Memory Discipline

This repository uses `agent-memory` to maintain shared, two-layer context across all coding assistants (Claude Code, Cursor, Codex, OpenCode, Antigravity, Aider, Windsurf, Cline).

## Protocols

### 1. Recall Before Assuming
Before making architectural decisions, modifying core layers, or refactoring conventions:
- Call `agent-memory:memory_recall` with relevant keywords and project name to check past decisions and bugfixes.
- If high-level architectural or cross-project context is needed, call `agent-memory:memory_recall_deep`.

### 2. Record Verified Decisions (In-Flight Curation)
When settling an architectural pattern, fixing a non-trivial bug, or establishing a convention:
- Call `agent-memory:memory_record` with:
  - `text`: Clear, concise description of the decision and reason.
  - `title`: Short title (e.g. "Unified SQLite Schema", "Zero-Dependency Rule").
  - `category`: "architecture" | "pattern" | "bugfix" | "convention" | "decision".
  - `project`: Target project name (`agent-memory`).
  - `supersedes`: (Optional) ID (`#1234`) or keywords of an older memory this overrides.
  - `relations`: (Optional) 1–2 Knowledge graph triples to store directly in L2:
    `[{"source": "Auth", "relation": "uses", "target": "JWT"}]`

### 3. Handle Conflict Steering
If `memory_record` returns a `[Notice - Potential Overlap Found]` alert pointing to an older rule:
- If your new decision overrides the older rule, immediately invoke `memory_record` with `supersedes="#<id>"` to archive the superseded precedent.

### 4. Multi-Device Sync
- All recorded memories are automatically committed and pushed in the background to your private Git vault (`~/.agent-memory/vault/`).
- To inspect sync status or force immediate compaction:
  - Run `agent-sync status` or `agent-sync sync`.
  - Or invoke the MCP tool `memory_sync`.
