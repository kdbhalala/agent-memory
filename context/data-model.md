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

**Data Access APIs (`SessionLayer`)**:
- `record(text, title, project, category, supersedes, relations)`: In-flight insertion with conflict detection.
- `get_observation(obs_id)`: Fetches a single observation by ID with parsed facts and narrative.
- `delete_observation(obs_id, hard=False)`: Soft-delete (marks superseded) or hard-delete from SQLite and FTS5.
- `list_observations(limit=20, project=None, include_superseded=False)`: Queries recent observations ordered by ID descending.

### `graph_nodes` Table (L2 Knowledge Graph)
Stores entities and concepts.
- `id`: INTEGER PRIMARY KEY AUTOINCREMENT
- `name`: TEXT UNIQUE NOT NULL
- `entity_type`: TEXT NOT NULL DEFAULT 'concept'
- `description`: TEXT
- `project`: TEXT
- `created_at`: TEXT DEFAULT CURRENT_TIMESTAMP

### `graph_edges` Table (L2 Bi-Temporal Knowledge Graph)
Stores semantic relations and facts connecting nodes with bi-temporal validity tracking.
- `id`: INTEGER PRIMARY KEY AUTOINCREMENT
- `source`: TEXT NOT NULL (indexed)
- `relation`: TEXT NOT NULL (e.g. USES, IMPLEMENTS, DEPENDS_ON, FORBIDS, REPLACES)
- `target`: TEXT NOT NULL (indexed)
- `fact`: TEXT NOT NULL
- `project`: TEXT (indexed)
- `created_at`: TEXT DEFAULT CURRENT_TIMESTAMP
- `is_active`: INTEGER NOT NULL DEFAULT 1 (indexed; 1 for current active knowledge, 0 when superseded)
- `valid_from`: TEXT DEFAULT CURRENT_TIMESTAMP (timestamp when relation became active)
- `valid_until`: TEXT (timestamp when relation was invalidated or superseded)
- `superseded_by`: TEXT (description or pointer to contradictory successor edge)
- `UNIQUE(source, relation, target, fact, project)`

### `graph_aliases` Table (Pure-SQL Canonicalization)
Maps synonyms, acronyms, and aliases to canonical entity names.
- `alias`: TEXT PRIMARY KEY (e.g. `"fcm"`, `"k8s"`, `"jwt"`, `"sqlite"`, `"postgres"`)
- `canonical_name`: TEXT NOT NULL (e.g. `"FirebaseCloudMessaging"`, `"Kubernetes"`, `"JSONWebToken"`)
- `category`: TEXT (e.g. `"concept"`, `"technology"`, `"api"`)
- `created_at`: TEXT DEFAULT CURRENT_TIMESTAMP

### `core_memory_blocks` Table (Pinned Invariants)
Stores non-negotiable architectural rules and guidelines injected unconditionally into session startup and recall responses.
- `id`: INTEGER PRIMARY KEY AUTOINCREMENT
- `block_key`: TEXT UNIQUE NOT NULL (e.g. `"zero_pip_deps"`, `"lifecycle_hooks"`)
- `content`: TEXT NOT NULL
- `category`: TEXT DEFAULT 'system'
- `project`: TEXT DEFAULT 'global'
- `pinned`: INTEGER DEFAULT 1 (indexed; 1 = active and injected, 0 = unpinned)
- `created_at`: TEXT DEFAULT CURRENT_TIMESTAMP
- `updated_at`: TEXT DEFAULT CURRENT_TIMESTAMP

### `episodic_sessions` & `episodic_events` Tables (L3 Episodic Memory)
Tracks agent session lifecycles, duration, touched files, events, and git commit deltas.
- **`episodic_sessions`**:
  - `session_id`: TEXT PRIMARY KEY
  - `project`: TEXT NOT NULL (indexed)
  - `agent_name`: TEXT DEFAULT 'assistant'
  - `started_at`: TEXT NOT NULL
  - `ended_at`: TEXT
  - `duration_seconds`: REAL
  - `status`: TEXT DEFAULT 'active' (`active`, `completed`, `aborted`)
  - `goal`: TEXT
  - `summary`: TEXT
  - `git_branch`: TEXT
  - `git_commit_start`: TEXT
  - `git_commit_end`: TEXT
  - `touched_files`: TEXT DEFAULT '[]' (JSON array of relative paths)
  - `metadata`: TEXT DEFAULT '{}'
- **`episodic_events`**:
  - `id`: INTEGER PRIMARY KEY AUTOINCREMENT
  - `session_id`: TEXT NOT NULL (indexed)
  - `event_type`: TEXT NOT NULL (`decision`, `commit`, `file_edit`, `bugfix`, `milestone`)
  - `summary`: TEXT NOT NULL
  - `details`: TEXT DEFAULT '{}'
  - `created_at`: TEXT NOT NULL

### `code_files`, `code_symbols`, and `code_edges` (L4 Structural Code Graph)
Zero-dependency AST and streaming regex symbol index and dependency graph.
- **`code_files`**:
  - `project`: TEXT, `file_path`: TEXT, `language`: TEXT, `sha256`: TEXT, `indexed_at`: TEXT, `symbol_count`: INTEGER
  - `UNIQUE(project, file_path)`
- **`code_symbols`** (with FTS5 `code_symbols_fts`):
  - `project`: TEXT, `file_path`: TEXT, `symbol_name`: TEXT, `symbol_type`: TEXT (`class`, `function`, `method`, `interface`, `type`), `start_line`: INTEGER, `end_line`: INTEGER, `parent_symbol`: TEXT, `signature`: TEXT, `docstring`: TEXT
- **`code_edges`**:
  - `project`: TEXT, `source_symbol`: TEXT, `target_symbol`: TEXT, `relation`: TEXT (`CALLS`, `INHERITS`, `IMPORTS`, `CONTAINS`), `file_path`: TEXT, `line_number`: INTEGER
  - `UNIQUE(project, source_symbol, target_symbol, relation, file_path, line_number)`

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
