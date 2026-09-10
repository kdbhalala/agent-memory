# Architecture & System Invariants

## Core Invariants

1. **Zero External Runtime Dependencies**:
   - The framework uses strictly Python 3.10+ standard library and SQLite (`sqlite3`).
   - Never add third-party dependencies (`chromadb`, `networkx`, `requests`, `fastapi`) to runtime `dependencies` in `pyproject.toml`.

2. **Strict Layer Separation**:
   - **L1 Working Memory** ([`layers/session_layer.py`](../layers/session_layer.py)): Fast SQLite FTS5 with BM25 ranking (<2ms).
   - **L2 Knowledge Graph** ([`layers/graph_layer.py`](../layers/graph_layer.py)): SQLite recursive Common Table Expressions (`WITH RECURSIVE`) for multi-hop graph traversal (<0.5ms).
   - **Vault Storage & Compaction** ([`vault.py`](../vault.py)): Canonical append-only JSONL files in `~/.agent-memory/vault/`.
   - **Git Sync Engine** ([`sync.py`](../sync.py)): Automatic background push/pull to private GitHub repository.

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
