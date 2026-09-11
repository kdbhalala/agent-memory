# Architecture & System Invariants

## Core Invariants

1. **Zero External Runtime Dependencies**:
   - The framework uses strictly Python 3.10+ standard library and SQLite (`sqlite3`).
   - Never add third-party dependencies (`chromadb`, `networkx`, `requests`, `fastapi`) to runtime `dependencies` in `pyproject.toml`.

2. **Strict Layer Separation & Event-Driven Decoupling**:
   - **Configuration SSoT** ([`config.py`](../config.py)): Centralized path resolution and environment variable defaults.
   - **L1 Epistemic Working Memory** ([`layers/session_layer.py`](../layers/session_layer.py)): Fast SQLite FTS5 with BM25 ranking (<2ms), decoupled via record event listeners.
   - **L2 Semantic Knowledge Graph** ([`layers/graph_layer.py`](../layers/graph_layer.py)): SQLite recursive Common Table Expressions (`WITH RECURSIVE`) for multi-hop graph traversal (<0.5ms), decoupled via edge event listeners.
   - **L3 Episodic Session History** ([`layers/episodic_layer.py`](../layers/episodic_layer.py)): Session lifecycles, event logs, commit tracking, and cross-session startup recaps (<0.25ms).
   - **L4 Structural Code Graph** ([`layers/code_layer.py`](../layers/code_layer.py)): Python stdlib AST + streaming regex graph parser, callers, dependencies, and blast-radius impact analysis (<0.5ms).
   - **Vault Storage & Compaction** ([`vault.py`](../vault.py)): Canonical append-only JSONL files in `~/.agent-memory/vault/`.
   - **Git Sync Engine** ([`sync.py`](../sync.py)): Automatic background push/pull to private GitHub repository.
   - **Cold-Start Seeder** ([`bootstrap.py`](../bootstrap.py)): Zero-touch memory bootstrapping from Git history, `README.md`, and code symbols.
   - **Developer Observability & MCP Server** ([`mcp_server.py`](../mcp_server.py)): Dispatches 15 native MCP tools and CLI curation commands (`log`, `inspect`, `delete`, `pin`, `unpin`, `blocks`, `timeline`, `structure`, `callers`, `dependencies`, `impact`, `index`, `bootstrap`).

3. **Code vs Data Decoupling**:
   - The code repository must never store runtime databases (`*.db`, `*.sqlite`), user state (`promoted.json`), or secrets.
   - User memory data lives in `~/.agent-memory/` and `~/.agent-memory/vault/`.
   - Framework updates (`git pull` / `pip install -U`) must never touch or alter existing memories.

4. **Naming Standard**:
   - Do not name any internal files or modules after third-party packages.
   - Always use `SessionLayer` and `GraphLayer`.

5. **Host-Native In-Flight LLM Synthesis**:
   - Never require external LLM daemons, local weight downloads, or separate API keys.
   - Leverage the host assistant's active model in-flight during `memory_record` tool calls to extract L2 knowledge graph triples and identify superseded rules.

6. **Bi-Temporal Knowledge Graph & Canonicalization**:
   - L2 graph edges record temporal validity (`is_active`, `valid_from`, `valid_until`, `superseded_by`).
   - Contradictory edges automatically get invalidated without destroying historical provenance.
   - Pure-SQL entity aliasing (`graph_aliases`) canonicalizes acronyms and synonyms (e.g. `FCM` -> `FirebaseCloudMessaging`) in <0.01ms without heavyweight embedding models.

7. **Core Memory & Automated Lifecycle Hooks**:
   - Critical system invariants are stored as pinned Core Memory blocks (`core_memory_blocks`) prepended to recall queries.
   - Universal lifecycle hooks (`session-start`, `pre-compact`, `session-end`, `pre-commit`) proactively inject context, auto-promote memories before context compression, and sync the vault on session termination.

8. **Verified Performance SLAs & Production Benchmarks**:
   - Tested and verified against authentic production scale (13,989 observations, 20.61 MB vault):
     - **L1 Working Recall**: <8ms p50, <16ms p95.
     - **L2 Recursive Graph Traversal**: <0.5ms (SQL CTEs, no vector/graph DB bloat).
     - **Pure-SQL Alias Resolution**: >6M lookups/sec (<0.2 µs per canonicalization).
     - **Core Memory Retrieval**: <0.3ms for pinned system blocks.
     - **Multi-Agent Concurrency**: >150 QPS across 100 concurrent agent threads.
     - **In-Flight Conflict Detection**: <15ms across 14,000 rows.
     - **Lifecycle Hook Overhead**: <10ms for `session-start` prompt injection.
     - **Vault Compaction Throughput**: >4,000 records / second.
     - **Zero Background Daemons**: 0 MB idle background RAM. Run `python3 stress_test.py` to reproduce locally.

9. **Zero-Touch Cold-Start Seeding**:
   - Newly attached repositories and workspaces must self-bootstrap initial working memories from Git history (`git log`) and `README.md` via `bootstrap.py` without external model calls.
   - Eliminates Day-1 empty vault churn while remaining strictly idempotent.

