# Operational Runbook

## Daily Operations

### 1. Synchronizing Across Machines
When switching from Laptop to Desktop:
```bash
# Pull remote memories and reconcile local SQLite cache
agent-sync sync
```

### 2. Manual Compaction & Deduplication
If large volumes of memories have been recorded:
```bash
# Deduplicate observations and graph edges, then re-index SQLite
agent-sync dedupe
```

### 3. Promoting Working Memory to Knowledge Graph
Curate high-signal items from L1 observations into L2 triples:
```bash
# Dry run to inspect candidates
python3 promote.py --dry-run --project agent-memory

# Ingest top 20 durable learnings
python3 promote.py --project agent-memory --limit 20
```

### 4. Wire or Refresh Coding Assistants
Inspect or install MCP connections across tools:
```bash
# Check all detected tools
python3 integrate.py status

# Reconfigure all installed tools
python3 integrate.py install all
```

### 5. Resolving Conflicting Decisions
When an AI assistant receives a `[Notice - Potential Overlap Found]` message during `memory_record`:
- If the new pattern overrides the older one, the assistant immediately re-invokes `memory_record` specifying `supersedes="#<id>"`.
- You can also manually supersede an observation from the CLI:
```bash
python3 -c "from layers.session_layer import SessionLayer; SessionLayer(project='my-app').record(text='New decision', supersedes='#1234')"
```

### 6. Querying Superseded vs Active Rules
By default, active rules are ranked ahead of superseded rules:
```bash
# Active search
python3 recall.py "storage" --project agent-memory

# Deep search including L2 knowledge graph
python3 recall.py "storage" --project agent-memory --deep
```

### 7. Running Production Stress Tests & Benchmarks
To evaluate system performance, latency distributions, and throughput:
```bash
# Execute the authentic 11-tier benchmark suite
python3 stress_test.py
```

### 8. Managing Automated Lifecycle Hooks
To wire or refresh lifecycle hooks (`session-start`, `pre-compact`, `session-end`, `pre-commit`):
```bash
# Install hooks for all detected tools
agent-integrate hooks all

# Target specific tool (e.g. Claude Code or Antigravity)
agent-integrate hooks claude agy git

# Target project scope
agent-integrate hooks all --scope project
```

### 9. Core Memory Pinning & Invariants
Pin critical rules so they are unconditionally injected on session startup and recall:
```bash
# Pin via Python CLI
python3 -c "from layers.session_layer import SessionLayer; SessionLayer(project='agent-memory').pin_block('zero_pip_deps', 'Zero external pip dependencies: strictly Python stdlib and sqlite3', category='architecture', project='agent-memory')"

# Or via MCP tools: memory_pin / memory_unpin / memory_blocks
```
