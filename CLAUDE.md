# agent-memory - AI Assistant Workspace Guide

Turnkey zero-dependency two-layer memory architecture (SQLite FTS5 + Recursive Knowledge Graph) with MCP server for Claude Code, Cursor, Codex, OpenCode, Antigravity, and all major coding assistants.

## Memory Discipline (agent-memory MCP)

This repository implements the two-layer memory architecture (SessionLayer L1 + GraphLayer L2).
When operating in this codebase:
1. Call `memory_recall(query, project="agent-memory")` to check past decisions and bugfixes before modifying code.
2. Call `memory_recall_deep(query, project="agent-memory")` when architectural or cross-project context is needed.
3. Call `memory_record(text, title, project="agent-memory", category="...", supersedes="...", relations=[...])` when establishing conventions or resolving non-trivial issues.
4. Pin non-negotiable invariants using `memory_pin(key, content, category="architecture", project="agent-memory")`.

## Project Structure & Navigation

- `config.py`: Single Source of Truth (SSoT) for paths, directories, and environment variable resolution.
- `layers/session_layer.py`: L1 Working Memory (SQLite FTS5 with BM25 ranking, <2ms) & Core Memory blocks.
- `layers/graph_layer.py`: L2 Knowledge Graph (SQLite recursive CTEs, <0.5ms), Bi-Temporal Edges & Entity Aliases.
- `vault.py`: Canonical Git-friendly append-only JSONL vault (`~/.agent-memory/vault/`) & deduplication engine.
- `sync.py`: Background Git/GitHub sync & `gh` CLI automation.
- `hooks.py`: Universal lifecycle hooks dispatcher (`session-start`, `pre-compact`, `session-end`, `pre-commit`).
- `promote.py`: Automated high-signal batch prompter L1 -> L2 (`--auto`).
- `mcp_server.py`: Model Context Protocol server exposing `memory_recall`, `memory_recall_deep`, `memory_record`, `memory_promote`, `memory_sync`, `memory_pin`, `memory_unpin`, `memory_blocks`.
- `integrate.py`: Automated multi-assistant installer, hook integrator (`agent-integrate hooks`), and project scaffolder.

## Modular Rules & Context

- **Architecture Invariants**: [`rules/architecture.md`](rules/architecture.md) (Zero external pip dependencies).
- **Memory Protocol**: [`rules/memory-discipline.md`](rules/memory-discipline.md).
- **API Contracts**: [`rules/api-contracts.md`](rules/api-contracts.md).
- **Testing & QA**: [`rules/testing-qa.md`](rules/testing-qa.md).
- **Domain Glossary**: [`context/domain-glossary.md`](context/domain-glossary.md).
- **Data Model**: [`context/data-model.md`](context/data-model.md).
- **Runbook**: [`context/runbook.md`](context/runbook.md).

## Verification Commands

Always run before committing:
```bash
python3 test_offline.py && python3 eval_l1.py && python3 eval_l2.py && python3 integrate.py test
python3 stress_test.py
```
