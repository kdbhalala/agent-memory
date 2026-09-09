# agent-memory — two-layer AI memory

* **L1 `claude-mem`** (`layers/claudemem.py`): session history, tool actions,
  decisions. Read via local worker HTTP, SQLite FTS fallback. Primary memory.
* **L2 `cognee`** (`layers/cognee_layer.py`): durable knowledge only
  (architecture, decisions, reusable fixes). Lazy import — L1 works without it.

### Quickstart (Python API)

```python
from layers.claudemem import ClaudeMemLayer
from layers.cognee_layer import CogneeLayer
from recall import recall

r = recall("auth bug", ClaudeMemLayer(), CogneeLayer())  # L2 only if L1 thin
r = recall("auth bug", ClaudeMemLayer(), CogneeLayer(), deep=True)  # force L2
```

### CLI

```bash
# Query session and durable memory directly from terminal
python recall.py "auth bug" --project my-repo
python recall.py "architecture decisions" --deep --limit 5

# Preview durable candidates (dry-run: zero LLM tokens)
python promote.py --dry-run --project my-repo

# Promote curated candidates L1 -> L2 (deduped via promoted.json)
python promote.py --project my-repo --limit 20
```

Either layer implements `layers/base.py::MemoryLayer` — replaceable.

## Wiring (MCP server: `python3 mcp_server.py`, tools: `memory_recall`, `memory_recall_deep`, `memory_record`, `memory_promote`)

| Agent | Memory capture | agent-memory MCP |
|---|---|---|
| Claude Code | plugin ✓ | `claude mcp add agent-memory` ✓ connected |
| OpenCode | plugin ✓ | `opencode.jsonc` `mcp` ✓ (restart session to load) |
| Codex | plugin + hooks ✓ | `config.toml [mcp_servers.agent-memory]` ✓ enabled |
| Copilot | installer ran (capture unconfirmed) | `copilot mcp add` ✓ listed |
| agy | `memory_record` + global skill ✓ | `~/.gemini/config/mcp_config.json` ✓ enabled |
| crush | n/a | `~/.config/crush/mcp.json` ✓ |
| pi | n/a | `pi-mcp-extension` + `~/.pi/agent/mcp.json` ✓ |

## Hands-off notes

* Capture is fully automatic wherever claude-mem hooks are installed.
* Worker autostart: `~/Library/LaunchAgents/ai.cmem.worker.plist` (survives reboot).
* Retrieval via MCP is on-demand: agents call it when relevant. First MCP call
  in interactive agents (codex etc.) asks one approval — approve once.
* `memory_promote` is manual by design (LLM cost + curation judgment).
  Verified live: codex `memory_recall` returned `#13326` end-to-end.
