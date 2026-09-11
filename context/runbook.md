# Operational Runbook

## Daily Operations

### 1. Synchronizing Across Machines
When switching from Laptop to Desktop:
```bash
# Pull remote memories and reconcile local SQLite cache
agi-sync sync
# or: python3 -m agi_memory.sync sync
```

### 2. Manual Compaction & Deduplication
If large volumes of memories have been recorded:
```bash
# Deduplicate observations and graph edges, then re-index SQLite
agi-sync dedupe
# or: python3 -m agi_memory.sync dedupe
```

### 3. Promoting Working Memory to Knowledge Graph
Curate high-signal items from L1 observations into L2 triples:
```bash
# Dry run to inspect candidates
python3 -m agi_memory.promote --dry-run --project agi-memory

# Ingest top 20 durable learnings
python3 -m agi_memory.promote --project agi-memory --limit 20
```

### 4. Wire or Refresh Coding Assistants
Inspect or install MCP connections across tools:
```bash
# Check all detected tools
agi-integrate status
# or: python3 -m agi_memory.integrate status

# Reconfigure all installed tools
agi-integrate install all
```

### 5. Resolving Conflicting Decisions
When an AI assistant receives a `[Notice - Potential Overlap Found]` message during `memory_record`:
- If the new pattern overrides the older one, the assistant immediately re-invokes `memory_record` specifying `supersedes="#<id>"`.
- You can also manually supersede an observation from the CLI:
```bash
python3 -c "from agi_memory.layers.session_layer import SessionLayer; SessionLayer(project='my-app').record(text='New decision', supersedes='#1234')"
```

### 6. Querying Superseded vs Active Rules
By default, active rules are ranked ahead of superseded rules:
```bash
# Active search
agi-recall "storage" --project agi-memory
# or: python3 -m agi_memory.recall "storage" --project agi-memory

# Deep search including L2 knowledge graph
agi-recall "storage" --project agi-memory --deep
```

### 7. Running Production Stress Tests & Benchmarks
To evaluate system performance, latency distributions, and throughput:
```bash
# Execute the authentic 12-tier benchmark suite
python3 tests/stress_test.py
```

### 8. Managing Automated Lifecycle Hooks
To wire or refresh lifecycle hooks (`session-start`, `pre-compact`, `session-end`, `pre-commit`, `post-commit`):
```bash
# Install hooks for all detected tools
agi-integrate hooks all

# Target specific tool (e.g. Claude Code or Antigravity)
agi-integrate hooks claude agy git

# Target project scope
agi-integrate hooks all --scope project
```

### 9. Core Memory Pinning & Invariants
Pin critical rules so they are unconditionally injected on session startup and recall:
```bash
# Pin via Python CLI
python3 -c "from agi_memory.layers.session_layer import SessionLayer; SessionLayer(project='agi-memory').pin_block('zero_pip_deps', 'Zero external pip dependencies: strictly Python stdlib and sqlite3', category='architecture', project='agi-memory')"

# Or via MCP tools: memory_pin / memory_unpin / memory_blocks
```

### 10. Cold-Start Seeding on New Repositories
When connecting agi-memory to a newly attached project or workspace:
```bash
# Seed initial architecture, git commit rationale, and structural code graph
agi-memory bootstrap --repo .

# Or via agi-integrate
agi-integrate bootstrap /path/to/project --max-commits 25
```

### 11. Developer Observability & Memory Curation
Audit and curate stored memories from the command line:
```bash
# View recent memories in a table
agi-memory log -n 20 --project agi-memory

# Inspect observation details, facts, narrative, and concepts
agi-memory inspect 101

# Delete or supersede an observation
agi-memory delete 101
agi-memory delete 101 --hard

# Manage pinned core invariants
agi-memory pin "zero_pip_deps" "Zero external pip dependencies" --category architecture
agi-memory blocks
agi-memory unpin "zero_pip_deps"
```

### 12. Structural Code Graph & Impact Analysis
Inspect symbol structure, callers, and blast radius directly:
```bash
# Outline symbols in file or directory
agi-memory structure src/

# Find inbound callers of a function or class
agi-memory callers SessionLayer

# Find outbound dependencies of a symbol
agi-memory dependencies recall

# Analyze blast-radius impact before refactoring
agi-memory impact SessionLayer

# Incrementally index directory into code graph
agi-memory index src/
```

### 13. Episodic Session History & Timeline
Inspect what coding assistants accomplished in recent sessions:
```bash
# View recent session timeline and summaries
agi-memory timeline -n 10 --project agi-memory
```
