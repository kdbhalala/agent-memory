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
