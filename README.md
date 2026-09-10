# agent-memory

[![CI](https://github.com/kdbhalala/agent-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/kdbhalala/agent-memory/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Dependencies](https://img.shields.io/badge/dependencies-0%20(stdlib)-brightgreen.svg)](pyproject.toml)
[![Latency](https://img.shields.io/badge/L2%20graph%20latency-0.35ms-blue.svg)](eval_l2.py)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**Zero-dependency, high-performance two-layer memory architecture (SQLite FTS5 + Native Recursive Knowledge Graph) for AI coding assistants.**

Share synchronized context, recent bugfixes, and durable architectural decisions seamlessly across **Claude Code**, **Cursor**, **Windsurf**, **OpenAI Codex**, **OpenCode**, **Antigravity CLI**, **Aider**, **Goose**, **Cline**, **Roo Code**, **Crush**, and **Pi**.

---

## Why agent-memory? (Measurable Benchmarks)

Instead of relying on heavy multi-gigabyte vector databases or external Node.js daemons, `agent-memory` brings the best concepts of **`claude-mem`** (fast session observations) and **`cognee`** (semantic knowledge graphs) directly into pure Python standard library and SQLite.

The result is **orders of magnitude faster, completely local, and zero-dependency**:

| Dimension | `claude-mem` (alone) | `cognee` (alone) | `agent-memory` (Native) | Why agent-memory Wins |
|---|---|---|---|---|
| **External Dependencies** | Node.js v20+, npm daemon, Express | 60+ pip packages (LangChain, Pydantic, Chroma) | **0 (Python stdlib only)** | No version conflicts, runs anywhere |
| **Install Disk Size** | ~80 MB (Node) + 3.1 MB bundle | ~550 MB | **< 1 MB** | **>500x smaller footprint** |
| **L1 Working Recall Latency** | ~165 ms (HTTP worker roundtrip) | n/a (heavy graph only) | **1.82 ms (SQLite FTS5)** | **~90x faster** session recall |
| **L2 Durable Graph Latency** | n/a (no graph traversal) | ~2,500 ms (vector + graph + LLM) | **0.35 ms (Recursive CTEs)** | **>7,000x faster** multi-hop traversal |
| **Cold-Start Boot Time** | Background service must be active | ~2,200 ms (engine boot) | **34.8 ms** | **>60x faster** initialization |
| **Process Memory (RAM)** | ~120 MB (Node.js daemon) | ~350 MB (Chroma/embeddings) | **34.7 MB (RSS)** | **10x less RAM usage** |
| **Query Token Cost** | $0.00 (local) | ~1,500 - 3,000 tokens / query | **$0.00 (0 LLM tokens)** | Zero cost for graph search |
| **Coding Tool Integrations** | Claude Code only (custom patch for Codex) | None (Python SDK only) | **12 Assistants Turnkey** | 1-command setup across all tools |
| **Offline Resilience** | Daemon crashes break memory | Requires API key & network | **100% Offline & Air-gapped** | Works completely without internet |

*Benchmarks measured on Apple Silicon, 100 runs per tier. Reproduce with `python eval_l1.py` and `python eval_l2.py`.*

---

## Architecture

```mermaid
graph TD
    subgraph AI Coding Assistants
        CC["Claude Code"]
        CU["Cursor"]
        CX["OpenAI Codex"]
        OC["OpenCode"]
        AG["Antigravity (agy)"]
        AD["Aider"]
        GS["Goose"]
        CL["Cline / Roo Code"]
        CR["Crush / Pi"]
    end

    MCP["agent-memory MCP Server (stdio)<br/><code>memory_recall</code> · <code>memory_recall_deep</code> · <code>memory_record</code> · <code>memory_promote</code>"]

    subgraph Native Two-Layer Storage (Zero Dependencies)
        L1["L1 Working Memory (SQLite FTS5)<br/>1.82ms · BM25 Ranking · Auto-bootstrapped"]
        L2["L2 Knowledge Graph (SQLite Recursive CTEs)<br/>0.35ms · Multi-hop Graph Traversal · Triples"]
    end

    CC & CU & CX & OC & AG & AD & GS & CL & CR <--> MCP
    MCP <--> L1
    MCP <--> L2
    L1 -. "Curated Promotion (promote.py)" .-> L2
```

1. **L1 Working Memory (`layers/session_layer.py`)**:
   - Sub-2ms full-text search with BM25 ranking over recent session observations and tool fixes.
   - Automatically self-bootstraps SQLite schema and triggers on first read/write.
   - Fully compatible with `claude-mem` worker if present, but requires zero daemons to operate.
2. **L2 Semantic Knowledge Graph (`layers/graph_layer.py`)**:
   - Native SQLite graph tables (`graph_nodes`, `graph_edges`) with full-text search (`FTS5`).
   - Sub-millisecond (0.35ms) multi-hop recursive graph traversal using SQL Common Table Expressions (`WITH RECURSIVE`).
   - Zero-token heuristic entity-relation extraction + optional direct LLM semantic extraction.

---

## Turnkey Setup in 10 Seconds

Install the package:
```bash
git clone https://github.com/kdbhalala/agent-memory.git
cd agent-memory
pip install -e .
```

### 1. Check Tool Status
Inspect which AI coding assistants are detected on your machine:
```bash
python integrate.py status
```

### 2. One-Command Turnkey Installation
Configure the MCP server and proactive memory discipline rules across all detected assistants:
```bash
python integrate.py install all
```

### 3. Verify MCP Handshake
Validate the stdio protocol and tool registrations:
```bash
python integrate.py test
```

---

## Supported Assistants Matrix

Every integrated tool gains access to `memory_recall`, `memory_recall_deep`, `memory_record`, and `memory_promote`:

| Assistant / Environment | Type | agent-memory MCP Config | Proactive Memory Discipline Rules |
|---|---|---|---|
| **Claude Code** | CLI | `~/.claude.json` ✓ | `~/.claude/CLAUDE.md` ✓ |
| **Cursor** | IDE | `~/.cursor/mcp.json` ✓ | `~/.cursor/rules/agent-memory.mdc` ✓ |
| **OpenAI Codex** | CLI | `~/.codex/config.toml` ✓ | `~/.codex/AGENTS.md` ✓ |
| **OpenCode** | CLI | `~/.config/opencode/opencode.jsonc` ✓ | `~/.config/opencode/rules.md` ✓ |
| **Antigravity (`agy`)** | CLI/IDE | `~/.gemini/config/mcp_config.json` ✓ | `~/.gemini/config/skills/agent-memory/` ✓ |
| **Windsurf** | IDE | `~/.codeium/windsurf/mcp_config.json` ✓ | `~/.windsurfrules` ✓ |
| **Aider** | CLI | `~/.aider.conf.yml` ✓ | `~/.aider.conventions.md` ✓ |
| **Goose** | CLI | `~/.config/goose/config.yaml` ✓ | `~/.config/goose/hints.md` ✓ |
| **Cline / Roo Code** | VS Code | `cline_mcp_settings.json` ✓ | `.clinerules` / `.roomodes` ✓ |
| **Crush** | CLI | `~/.config/crush/mcp.json` ✓ | Standard MCP |
| **Pi** | CLI | `~/.pi/agent/mcp.json` ✓ | Standard MCP |

*See [INTEGRATIONS.md](INTEGRATIONS.md) for full tool-by-tool manual configuration guides and copy-paste snippets.*

---

## CLI Usage

### Querying Memory
```bash
# Fast L1 Working Memory recall
python recall.py "auth bug" --project my-app

# Deep L2 Knowledge Graph recall (multi-hop traversal)
python recall.py "state management architecture" --deep --limit 5
```

### Curating Knowledge (L1 -> L2 Knowledge Graph)
```bash
# Preview durable candidates (zero tokens)
python promote.py --dry-run --project my-app

# Ingest high-signal learnings into the native knowledge graph
python promote.py --project my-app --limit 20
```

---

## Python API

```python
from layers.session_layer import SessionLayer
from layers.graph_layer import GraphLayer
from recall import recall

l1 = SessionLayer(project="my-app")
l2 = GraphLayer(project="my-app")

# Save a decision (instantly queryable across all CLI tools)
l1.record("Always use secure_storage for JWT tokens on mobile", title="JWT Storage Rule")

# Fast L1 working memory search (<2ms)
res = l1.search("JWT tokens")

# Deep multi-hop graph recall (0.35ms)
deep_res = recall("auth storage", l1, l2, deep=True)
```

---

## Running Evaluations & Tests

All tests run completely offline with zero API keys or external services:

```bash
# Run unit tests (layers, SQLite FTS5, graph traversal, installer)
python test_offline.py

# Evaluate L1 working memory retrieval accuracy (10/10, ~3.6ms)
python eval_l1.py

# Evaluate L2 knowledge graph multi-hop traversal (6/6, ~0.35ms)
python eval_l2.py
```

---

## License

MIT License. See [LICENSE](LICENSE) for details.
