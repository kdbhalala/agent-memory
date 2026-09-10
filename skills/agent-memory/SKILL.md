---
name: agent-memory
description: Proactively recalls session decisions, bug fixes, and architectural rules from two-layer memory (SessionLayer L1 + GraphLayer L2) via MCP, and promotes curated durable knowledge.
---

# Agent Memory Skill

Use this skill when starting non-trivial tasks, establishing project patterns, or debugging issues.

## Instructions
1. **Recall**:
   - For fast session decisions: `memory_recall(query, project="agent-memory")`
   - For deep architectural context: `memory_recall_deep(query, project="agent-memory")`
2. **Record (In-Flight Curation)**:
   - Record durable decisions: `memory_record(text, title, project="agent-memory", category="architecture", supersedes="#123", relations=[{"source": "A", "relation": "USES", "target": "B"}])`
   - If overriding an older pattern, pass `supersedes="#<id>"`.
   - If `[Notice - Potential Overlap Found]` is returned, resolve conflicts by calling `memory_record` with `supersedes`.
3. **Sync**:
   - Ensure multi-device synchronization: `memory_sync(action="sync")`
