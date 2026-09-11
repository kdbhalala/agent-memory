---
name: agent-memory
description: Proactively recalls session decisions, bug fixes, and architectural rules from four-pillar cognitive memory (Epistemic L1 + Semantic L2 + Episodic L3 + Structural Code Graph L4) via MCP, and promotes curated durable knowledge.
---

# Agent Memory Skill

Use this skill when starting non-trivial tasks, establishing project patterns, refactoring symbols, or debugging issues.

## Instructions
1. **Recall Prior Precedents**:
   - For fast session decisions: `memory_recall(query, project="agi-memory")`
   - For deep architectural context: `memory_recall_deep(query, project="agi-memory")`
2. **Inspect Session Timeline**:
   - Inspect prior sessions and touched files: `memory_timeline(project="agi-memory")`
3. **Inspect Code Callers & Blast-Radius**:
   - Class/function structure: `code_structure(path="src/agi_memory/layers")`
   - Inbound callers: `code_callers(symbol="SessionLayer")`
   - Outbound dependencies: `code_dependencies(symbol="recall")`
   - Refactor blast radius: `code_impact(target="SessionLayer")`
4. **Record (In-Flight Curation)**:
   - Record durable decisions: `memory_record(text, title, project="agi-memory", category="architecture", supersedes="#123", relations=[{"source": "A", "relation": "USES", "target": "B"}])`
   - If overriding an older pattern, pass `supersedes="#<id>"`.
5. **Pin Core Invariants**:
   - Pin non-negotiable architectural rules into Core Memory: `memory_pin(key="zero_pip_deps", content="Zero external pip dependencies", category="architecture", project="agi-memory")`. Pinned rules are unconditionally prepended to every recall and session startup context.
6. **Sync**:
   - Ensure multi-device synchronization: `memory_sync(action="sync")`
7. **Cold-Start Bootstrap**:
   - For newly attached repositories: `memory_bootstrap(repo=".")` to seed initial memories from Git history, README, and code symbols.

