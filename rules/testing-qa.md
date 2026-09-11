# Testing & Quality Assurance

All verification runs 100% offline without API keys, network access, or external daemons.

## Required Verification Checklist

Before committing or pushing any code changes, all 4 test suites must pass:

1. **Unit & Offline Integration Tests**:
   ```bash
   python3 test_offline.py
   ```
   Verifies layers, base classes, SQLite schema bootstrap, ranking preservation, vault export/import, deduplication/compaction, local Git sync, cold-start bootstrap, observation inspection, soft/hard deletion, and developer observability CLI.

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
   Verifies JSON-RPC 2.0 stdio communication, `initialize`, `ping`, and registration of all 9 tools:
   - `memory_recall`
   - `memory_recall_deep`
   - `memory_record`
   - `memory_promote`
   - `memory_sync`
   - `memory_pin`
   - `memory_unpin`
   - `memory_blocks`
   - `memory_bootstrap`

5. **Comprehensive 11-Tier Production Stress Test**:
   ```bash
   python3 stress_test.py
   ```
   Evaluates full production performance against real multi-thousand observation datasets:
   - L1 Working Memory latency (<8ms p50, <16ms p95 on 14k observations)
   - L2 Recursive CTE traversal (<0.5ms)
   - Pure-SQL entity alias resolution (>6M lookups/sec, ~0.16 µs)
   - Core Memory block retrieval (<0.3ms)
   - Multi-agent concurrency throughput (>150 QPS across 100 concurrent workers)
   - In-flight conflict steering & temporal supersedence
   - Lifecycle hook latency (<10ms)
   - Vault compaction throughput (>4,000 records/sec)
   - RSS memory footprint (0 MB idle RAM, 0 background daemons)
