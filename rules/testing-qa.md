# Testing & Quality Assurance

All verification runs 100% offline without API keys, network access, or external daemons.

## Required Verification Checklist

Before committing or pushing any code changes, all 4 test suites must pass:

1. **Unit & Offline Integration Tests**:
   ```bash
   python3 test_offline.py
   ```
   Verifies layers, base classes, SQLite schema bootstrap, ranking preservation, vault export/import, deduplication/compaction, and local Git sync.

2. **L1 Retrieval Evaluation**:
   ```bash
   python3 eval_l1.py
   ```
   Evaluates L1 Working Memory accuracy (10/10 target) and query latency (<5ms).

3. **L2 Knowledge Graph Evaluation**:
   ```bash
   python3 eval_l2.py
   ```
   Evaluates L2 multi-hop graph traversal accuracy (6/6 target) and latency (<1ms).

4. **MCP Handshake & Tool Protocol**:
   ```bash
   python3 integrate.py test
   ```
   Verifies JSON-RPC 2.0 stdio communication, `initialize`, `ping`, and registration of all 5 tools:
   - `memory_recall`
   - `memory_recall_deep`
   - `memory_record`
   - `memory_promote`
   - `memory_sync`
