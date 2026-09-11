# Memory & Code Graph Discipline (agi-memory MCP)

This repository implements the four cognitive memory pillars (Epistemic L1 + Semantic L2 + Episodic L3 + Structural Code L4) to maintain shared context across all coding assistants (Claude Code, Cursor, Codex, OpenCode, Antigravity, Aider, Windsurf, Cline).

## Protocols

### 1. Recall Prior Precedents Before Assuming
Before making architectural decisions, modifying core layers, or refactoring conventions:
- Call `memory_recall(query, project="agi-memory")` with relevant keywords to check past decisions and bugfixes.
- If high-level architectural or cross-project context is needed, call `memory_recall_deep(query, project="agi-memory")`.

### 2. Inspect Session Timeline & Touched Files
Before starting work on an ongoing feature or resuming after interruptions:
- Call `memory_timeline(project="agi-memory")` to inspect what was accomplished in prior sessions, which files were touched, and recent commit hashes.

### 3. Inspect Code Callers & Blast-Radius Impact
Before refactoring, renaming, or deleting functions, methods, or classes:
- Call `code_structure(path)` to view class and function hierarchies in modules.
- Call `code_callers(symbol)` to discover all inbound callers.
- Call `code_dependencies(symbol)` to discover all outbound dependencies.
- Call `code_impact(target)` to evaluate the upstream blast radius and affected files before making destructive changes.

### 4. Record Verified Decisions (In-Flight Curation)
When settling an architectural pattern, fixing a non-trivial bug, or establishing a convention:
- Call `memory_record` with:
  - `text`: Clear, concise description of the decision and reason.
  - `title`: Short title (e.g. "Unified SQLite Schema", "Zero-Dependency Rule").
  - `category`: "architecture" | "pattern" | "bugfix" | "convention" | "decision".
  - `project`: Target project name (`agi-memory`).
  - `supersedes`: (Optional) ID (`#1234`) or keywords of an older memory this overrides.
  - `relations`: (Optional) 1–2 Knowledge graph triples to store directly in L2:
    `[{"source": "AuthService", "relation": "USES", "target": "SecureStorage"}]`

### 5. Handle Conflict Steering
If `memory_record` returns a `[Notice - Potential Overlap Found]` alert pointing to an older rule:
- If your new decision overrides the older rule, immediately invoke `memory_record` with `supersedes="#<id>"` to archive the superseded precedent.

### 6. Core Memory Pinning
For non-negotiable architectural invariants (e.g., zero external pip dependencies, test verification commands):
- Call `memory_pin(key, content, category="architecture", project="agi-memory")` so the rule is permanently pinned to Core Memory and automatically injected on session startup and every recall query.
- Use `memory_unpin(key)` if a constraint is retired or refactored.

### 7. Multi-Device Sync
- All recorded memories are automatically committed and pushed in the background to your private Git vault (`~/.agi-memory/vault/`).
- To inspect sync status or force immediate compaction:
  - Run `agi-sync status` or `agi-sync sync`.
  - Or invoke the MCP tool `memory_sync(action="sync")`.

### 8. Cold-Start Bootstrapping
When attaching an assistant to a newly cloned or initialized workspace:
- Call `memory_bootstrap(repo=".")` or run `agi-memory bootstrap` to seed initial working memories and structural code graph directly from repository README, Git history, and source files.

