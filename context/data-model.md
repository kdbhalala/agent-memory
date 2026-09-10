# Data Model & Storage Specifications

## 1. Local SQLite Schema (`~/.agent-memory/memory.db`)

### `observations` Table (L1 Working Memory)
Stores granular session observations, tool executions, and precedents.
- `id`: INTEGER PRIMARY KEY AUTOINCREMENT
- `memory_session_id`: TEXT
- `project`: TEXT (indexed)
- `type`: TEXT (category: `decision`, `architecture`, `pattern`, `bugfix`, `convention`, or `superseded`)
- `title`: TEXT
- `subtitle`: TEXT (contains metadata and `[SUPERSEDED by #<id>]` when archived)
- `facts`: TEXT (JSON array of atomic fact strings)
- `narrative`: TEXT (Full prose context)
- `concepts`: TEXT (JSON array of tags)
- `files_read`: TEXT (JSON array)
- `files_modified`: TEXT (JSON array)
- `prompt_number`: INTEGER
- `discovery_tokens`: INTEGER
- `created_at`: TEXT (ISO8601)
- `created_at_epoch`: INTEGER (Epoch milliseconds)
- `content_hash`: TEXT (Deterministic deduplication hash)
- `generated_by_model`: TEXT
- `relevance_count`: INTEGER
- `sync_rev`: TEXT

**FTS5 Index (`observations_fts`)**:
Full-text index on `title`, `subtitle`, `facts`, `narrative`, `concepts` with SQLite `bm25()` ranking. Synchronized via `AFTER INSERT` (`observations_ai`), `AFTER DELETE` (`observations_ad`), and `AFTER UPDATE` (`observations_au`) triggers. When superseded, records are downranked in search queries behind active records.

### `graph_nodes` Table (L2 Knowledge Graph)
Stores entities and concepts.
- `id`: INTEGER PRIMARY KEY AUTOINCREMENT
- `name`: TEXT UNIQUE NOT NULL
- `entity_type`: TEXT NOT NULL DEFAULT 'concept'
- `description`: TEXT
- `project`: TEXT
- `created_at`: TEXT DEFAULT CURRENT_TIMESTAMP

### `graph_edges` Table (L2 Knowledge Graph)
Stores semantic relations and facts connecting nodes.
- `id`: INTEGER PRIMARY KEY AUTOINCREMENT
- `source`: TEXT NOT NULL (indexed)
- `relation`: TEXT NOT NULL (e.g. USES, IMPLEMENTS, DEPENDS_ON)
- `target`: TEXT NOT NULL (indexed)
- `fact`: TEXT NOT NULL
- `project`: TEXT (indexed)
- `created_at`: TEXT DEFAULT CURRENT_TIMESTAMP
- `UNIQUE(source, relation, target, fact, project)`

---

## 2. Canonical Git Vault Format (`~/.agent-memory/vault/`)

### `observations.jsonl`
Append-only, newline-delimited JSON. One observation per line:
```json
{"guid": "obs_123...", "project": "my-app", "type": "decision", "title": "JWT Auth", "narrative": "...", "facts": "...", "created_at_epoch": 1726000000}
```

### `graph.jsonl`
Append-only, newline-delimited JSON. Stores both nodes and edges:
```json
{"kind": "node", "name": "AuthService", "entity_type": "service", "description": "Core auth", "project": "my-app"}
{"kind": "edge", "source": "AuthService", "relation": "USES", "target": "Redis", "fact": "AuthService caches tokens in Redis", "project": "my-app"}
```

### `promoted.json`
JSON array of promoted observation hashes.
