# Domain Glossary

Core concepts and terminology used throughout `agent-memory`:

- **L1 Working Memory (`SessionLayer`)**: Local SQLite FTS5 database storing granular, timestamped observations from past coding sessions. Optimized for sub-2ms BM25 keyword and phrase retrieval.
- **L2 Knowledge Graph (`GraphLayer`)**: Native SQLite knowledge graph storing entity nodes (`graph_nodes`) and semantic relationship triples (`graph_edges`). Queried via recursive Common Table Expressions (`WITH RECURSIVE`) in <0.5ms.
- **Triple**: An atomic knowledge statement formatted as `(Subject, Predicate, Object, Fact)`, e.g. `(AuthService, USES, Redis, "AuthService caches tokens in Redis")`.
- **Vault (`~/.agent-memory/vault/`)**: The Git-friendly canonical data store consisting of append-only JSONL files (`observations.jsonl`, `graph.jsonl`, `promoted.json`).
- **Compaction / Deduplication**: Process of removing redundant observations, identical hashes, noise (`NO_SIGNAL`), and duplicate graph edges to prevent database bloat over time.
- **Debounced Sync**: Background synchronization mechanism that batches rapid writes (e.g. within 3 seconds) into a single atomic Git commit and push, avoiding commit spam.
- **Materialization**: Process of generating or updating the local SQLite cache from the canonical JSONL files upon pulling from remote.
- **In-Flight Knowledge Graph Synthesis**: Semantic triple extraction performed directly by the host coding assistant's active model during regular tool calling, eliminating the need for external LLM daemons, additional API keys, or background processing.
- **Conflict Steering**: Real-time (<1ms) FTS5 collision detection executed during `memory_record` that returns advisory overlap notices directly to the assistant, prompting it to resolve conflicting rules autonomously.
- **Supersedence**: The mechanism of retiring older conventions or bugfixes when overridden by a newer decision, marking them with `[SUPERSEDED]` and downranking them in search queries.
- **Bi-Temporal Graph Edges**: Temporal provenance tracking (`valid_from`, `valid_until`, `is_active`, `superseded_by`) on L2 knowledge graph edges that archives historical relations without data loss when newer contradictory facts emerge.
- **Entity Alias / Canonicalization (`graph_aliases`)**: Pure-SQL and in-memory mapping layer that resolves synonyms, acronyms, and aliases (e.g. `FCM` -> `FirebaseCloudMessaging`) in sub-microsecond time (>6M lookups/sec, ~0.16 µs) without heavy embedding models.
- **Core Memory Blocks (`core_memory_blocks`)**: Pinned mission-critical invariants and architectural constraints that are unconditionally prepended to every recall response and session startup context in <0.3ms.
- **Lifecycle Hooks**: Universal triggers (`session-start`, `pre-compact`, `session-end`, `pre-commit`) wired into coding CLIs (Claude Code, Antigravity, Cursor, Codex, Git) that proactively inject context, auto-promote memories before compression, and sync the vault on termination.
- **Cold-Start Bootstrapping (`bootstrap.py`)**: Zero-touch automated seeder that parses the repository `README.md` and high-signal Git commit history (`git log`) to initialize L1 working memory on Day 1, eliminating empty-vault churn.
- **Developer Observability & Curation CLI**: Human-in-the-loop terminal commands (`agent-memory log`, `agent-memory inspect`, `agent-memory delete`, `agent-memory bootstrap`, `agent-memory recall`, `agent-memory pin`, `agent-memory unpin`, `agent-memory blocks`) allowing developers to view, inspect, and curate memory state without needing raw SQL.
