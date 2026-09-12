# The Four Cognitive Memory Pillars (Deep Dive)

`agi-memory` is structured around four specialized cognitive memory layers, each solving a distinct dimension of agent memory with zero external dependencies and sub-millisecond local SQLite performance:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      agi-memory Cognitive Engine                        │
├────────────────────┬────────────────────┬───────────────────────────────┤
│ L1 Epistemic       │ L2 Semantic Graph  │ L3 Episodic Session History   │
│ "What have we      │ "What does it mean │ "What happened in previous    │
│  learned?"         │  & how connected?" │  agent sessions?"             │
│ (SQLite FTS5)      │ (Recursive CTEs)   │ (Timelines & Commit Deltas)   │
├────────────────────┴────────────────────┴───────────────────────────────┤
│ L4 Structural Code Graph: "How is this codebase structurally connected?"│
│ (Python stdlib AST & Streaming Regex Parser, Callers, Transitive Impact)│
└─────────────────────────────────────────────────────────────────────────┘
```

### Pillar 1: L1 Epistemic Working Memory (`SessionLayer`)
*Answers: "What decisions, bugfixes, and invariants have we learned?"*
- **Sub-millisecond BM25 Ranking**: Uses SQLite FTS5 for instant (<2ms p50, 0.56ms on 14k records) full-text retrieval across past observations and technical decisions.
- **Pinned Core Memory Blocks (`memory_pin`, `memory_unpin`, `memory_blocks`)**: Pin non-negotiable architectural invariants or operational guardrails. Pinned blocks are **unconditionally injected on session startup** and prepended to all recall responses.
- **In-Flight Conflict Detection**: Analyzes semantic overlap on writes in 5ms across 14,000 observations, prompting assistants when a new proposal contradicts established precedents.
- **Inspection & Curation APIs**: Direct APIs (`get_observation`, `delete_observation`, `list_observations`) with soft-delete / supersedence provenance.
```bash
# Pin an invariant via CLI or MCP
agi-memory pin "zero_pip_deps" "Strictly Python stdlib and sqlite3. No external pip dependencies." --category architecture
```

### Pillar 2: L2 Semantic Knowledge Graph (`GraphLayer`)
*Answers: "What does our information mean and how is it connected?"*
- **Native Recursive CTE Traversal**: Multi-hop relationship querying executed natively inside SQLite via `WITH RECURSIVE` in <0.5ms (0.65ms on 14k records) without GraphRAG or Neo4j overhead.
- **Bi-Temporal Graph Edges**: Tracks validity windows (`is_active`, `valid_from`, `valid_until`, `superseded_by`). Historical edges remain immutable while contradictory edges are deactivated.
- **Pure-SQL Entity Alias Layer**: Instant synonym and acronym canonicalization (`FCM` -> `FirebaseCloudMessaging`, `k8s` -> `Kubernetes`, `jwt` -> `JSONWebToken`) in <0.01ms (4.11M lookups/sec).
- **Automated L1 -> L2 Graph Prompter (`memory_promote` / `agi-memory promote`)**: Automatically distills and clusters high-signal observations into durable entity-relation triples.
```bash
# Preview or auto-promote candidate triples
agi-memory promote --auto --limit 25
```

### Pillar 3: L3 Episodic Session History (`EpisodicLayer`)
*Answers: "What happened during previous agent sessions?"*
- **Cross-Session Continuity**: Captures session lifecycles (start, end, duration, agent type), touched file sets, prompt events, and git commit deltas.
- **Automated Briefing Injection**: When an assistant launches, the `session-start` lifecycle hook generates an executive briefing of the most recent session's activity (<0.25ms), preventing cold-start rediscovery loops.
- **Session Timelines (`memory_timeline` / `agi-memory timeline`)**: Retrieve structured chronological histories of prior sessions and inspect what changes were made across tools.
```bash
# Inspect recent session activity and touched files
agi-memory timeline -n 5 --project my-app
```

### Pillar 4: L4 Structural Code Graph & Impact Analysis (`CodeLayer`)
*Answers: "How is this codebase structurally connected?"*
- **Zero-Dependency AST & Streaming Regex Engine**: Indexes symbols (classes, methods, functions) across Python (stdlib `ast`) and TypeScript, JavaScript, Go, Rust, and Dart (streaming regex) with incremental sha256 cache invalidation.
- **Callers & Dependencies (`code_callers`, `code_dependencies`)**: Query incoming callers (*"who calls function X?"*) and outbound dependencies (*"what does class Y depend on?"*) in 10ms without booting heavyweight LSPs.
- **Transitive Blast-Radius Impact Analysis (`code_impact`)**: Analyzes the multi-hop dependency tree to determine every symbol and file affected before you refactor or delete code.
- **Symbol Structure & Hierarchy (`code_structure`, `code_index`)**: Instantly inspect file symbol trees and trigger incremental codebase re-indexing.
```bash
# Inspect blast radius before refactoring a symbol
agi-memory impact SessionLayer --project my-app

# Inspect caller hierarchy
agi-memory callers verify_token --project my-app
```

---
