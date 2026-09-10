# Domain Glossary

Core concepts and terminology used throughout `agent-memory`:

- **L1 Working Memory (`SessionLayer`)**: Local SQLite FTS5 database storing granular, timestamped observations from past coding sessions. Optimized for sub-2ms BM25 keyword and phrase retrieval.
- **L2 Knowledge Graph (`GraphLayer`)**: Native SQLite knowledge graph storing entity nodes (`graph_nodes`) and semantic relationship triples (`graph_edges`). Queried via recursive Common Table Expressions (`WITH RECURSIVE`) in <0.5ms.
- **Triple**: An atomic knowledge statement formatted as `(Subject, Predicate, Object, Fact)`, e.g. `(AuthService, USES, Redis, "AuthService caches tokens in Redis")`.
- **Vault (`~/.agent-memory/vault/`)**: The Git-friendly canonical data store consisting of append-only JSONL files (`observations.jsonl`, `graph.jsonl`, `promoted.json`).
- **Compaction / Deduplication**: Process of removing redundant observations, identical hashes, noise (`NO_SIGNAL`), and duplicate graph edges to prevent database bloat over time.
- **Debounced Sync**: Background synchronization mechanism that batches rapid writes (e.g. within 3 seconds) into a single atomic Git commit and push, avoiding commit spam.
- **Materialization**: Process of generating or updating the local SQLite cache from the canonical JSONL files upon pulling from remote.
