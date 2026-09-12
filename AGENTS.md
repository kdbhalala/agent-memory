# agi-memory - AI Assistant Workspace Guide

Turnkey zero-dependency four-pillar cognitive memory framework (Epistemic, Semantic, Episodic, Structural Code Graph) with MCP server for Claude Code, Cursor, Codex, OpenCode, Antigravity, and all major coding assistants.

## Memory & Code Graph Discipline (agi-memory MCP)

This repository implements the four cognitive memory pillars (Epistemic L1 + Semantic L2 + Episodic L3 + Structural Code L4).
When operating in this codebase:
1. Call `memory_recall(query, project="agi-memory")` to check past decisions and bugfixes before modifying code.
2. Call `memory_recall_deep(query, project="agi-memory")` when architectural or cross-project context is needed.
3. Call `memory_timeline(project="agi-memory")` to check what was accomplished in prior sessions and review touched files.
4. Call `code_callers(symbol)` and `code_impact(target)` before refactoring or deleting symbols to inspect blast radius.
5. Call `code_structure(path)` to inspect class and function hierarchies in modules.
6. Call `memory_record(text, title, project="agi-memory", category="...", supersedes="...", relations=[...])` when establishing conventions or resolving non-trivial issues.
7. Pin non-negotiable invariants using `memory_pin(key, content, category="architecture", project="agi-memory")`.
8. Call `memory_bootstrap(repo=".")` when operating in a newly attached workspace to seed cold-start architectural memory and code graph.

## Project Structure & Navigation

- `src/agi_memory/`: Standard Python package root containing all core modules:
  - `config.py`: Single Source of Truth (SSoT) for paths, directories, and environment variable resolution.
  - `layers/session_layer.py`: L1 Epistemic Working Memory (SQLite FTS5 with BM25 ranking, <2ms), Core Memory blocks, and inspection/deletion APIs.
  - `layers/graph_layer.py`: L2 Semantic Knowledge Graph (SQLite recursive CTEs, <0.5ms), Bi-Temporal Edges & Entity Aliases.
  - `layers/episodic_layer.py`: L3 Episodic Session History (session timelines, touched files, commit deltas, cross-session recaps).
  - `layers/code_layer.py`: L4 Structural Code Graph (Python stdlib AST & regex parser, callers, dependencies, blast-radius impact analysis).
  - `vault.py`: Canonical Git-friendly append-only JSONL vault (`~/.agi-memory/vault/`) & deduplication engine.
  - `sync.py`: Background Git/GitHub sync & `gh` CLI automation.
  - `hooks.py`: Universal lifecycle hooks dispatcher (`session-start`, `pre-compact`, `session-end`, `pre-commit`, `post-commit`).
  - `promote.py`: Automated high-signal batch prompter L1 -> L2 (`--auto`).
  - `bootstrap.py`: Zero-touch cold-start memory seeder from Git history & README (`agi-memory bootstrap`).
  - `mcp_server.py`: Model Context Protocol server exposing 15 tools (`memory_recall`, `memory_recall_deep`, `memory_record`, `memory_promote`, `memory_sync`, `memory_pin`, `memory_unpin`, `memory_blocks`, `memory_bootstrap`, `memory_timeline`, `code_structure`, `code_callers`, `code_dependencies`, `code_impact`, `code_index`) and developer observability CLI.
  - `analyze.py`: Deterministic project analysis (stack, commands, layout, schema surfaces, CI) exposed as `agi-memory analyze [--json]`.
  - `init_command.py`: Emits the `/agi-init` slash command in every assistant's native format (Claude/Cursor/OpenCode/Codex MD, Gemini TOML, Windsurf/Cline workflows, Hermes SKILL.md).
  - `integrate.py`: Automated multi-assistant installer, cold-start seeder (`agi-integrate bootstrap`), hook integrator (`agi-integrate hooks`), and project wiring (`agi-integrate init`).
- `Formula/agi-memory.rb`: Official Homebrew formula (`brew tap kdbhalala/agi-memory https://github.com/kdbhalala/agi-memory && brew install agi-memory`).

## Modular Rules & Context

- **Architecture Invariants**: [`rules/architecture.md`](rules/architecture.md) (Zero external pip dependencies).
- **Memory Protocol**: [`rules/memory-discipline.md`](rules/memory-discipline.md).
- **API Contracts**: [`rules/api-contracts.md`](rules/api-contracts.md).
- **Testing & QA**: [`rules/testing-qa.md`](rules/testing-qa.md).
- **User Documentation**: [`docs/`](docs/) — installation, pillars, architecture,
  assistants, CLI, Python API, sync, benchmarks, testing. `README.md` is the index.
- **Domain Glossary**: [`context/domain-glossary.md`](context/domain-glossary.md).
- **Data Model**: [`context/data-model.md`](context/data-model.md).
- **Runbook**: [`context/runbook.md`](context/runbook.md).

## Verification Commands

Always run before committing:
```bash
python3 tests/test_offline.py && python3 tests/eval_l1.py && python3 tests/eval_l2.py \
  && python3 tests/eval_l3.py && python3 tests/eval_l4.py && agi-integrate test
python3 tests/chaos_test.py   # adversarial: hostile input, corruption, concurrency
python3 tests/stress_test.py
```
