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

## Turnkey CLI & IDE Integrations

Connect all your AI coding assistants to the same shared memory in seconds:

```bash
# Check detected tools and configuration status
python integrate.py status

# Install MCP server config & memory rules to all detected tools
python integrate.py install all

# Verify MCP server protocol handshake (initialize, ping, tools/list)
python integrate.py test
```

See [INTEGRATIONS.md](INTEGRATIONS.md) for full tool-by-tool copy-paste configs and manual setup instructions.

## Wiring (MCP server: `python3 mcp_server.py`)

Tools exposed: `memory_recall`, `memory_recall_deep`, `memory_record`, `memory_promote`.

| Assistant / Environment | Type | agent-memory MCP | Proactive Memory Rules |
|---|---|---|---|
| Claude Code | CLI | `~/.claude.json` ✓ | `~/.claude/CLAUDE.md` ✓ |
| Cursor | IDE | `~/.cursor/mcp.json` ✓ | `~/.cursor/rules/agent-memory.mdc` ✓ |
| OpenAI Codex | CLI | `~/.codex/config.toml` ✓ | `~/.codex/AGENTS.md` ✓ |
| OpenCode | CLI | `~/.config/opencode/opencode.jsonc` ✓ | `~/.config/opencode/rules.md` ✓ |
| Antigravity (`agy`) | CLI/IDE | `~/.gemini/config/mcp_config.json` ✓ | `~/.gemini/config/skills/agent-memory/` ✓ |
| Windsurf | IDE | `~/.codeium/windsurf/mcp_config.json` ✓ | `~/.windsurfrules` ✓ |
| Aider | CLI | `~/.aider.conf.yml` ✓ | `~/.aider.conventions.md` ✓ |
| Goose | CLI | `~/.config/goose/config.yaml` ✓ | `~/.config/goose/hints.md` ✓ |
| Cline / Roo Code | VS Code | `cline_mcp_settings.json` ✓ | `.clinerules` / `.roomodes` ✓ |
| Crush | CLI | `~/.config/crush/mcp.json` ✓ | n/a |
| Pi | CLI | `~/.pi/agent/mcp.json` ✓ | n/a |

## Hands-off notes

* Capture is fully automatic wherever claude-mem hooks are installed.
* Any agent can record newly established patterns via `memory_record`, instantly syncing with all others.
* Worker autostart: `~/Library/LaunchAgents/ai.cmem.worker.plist` (survives reboot).
* Retrieval via MCP is on-demand: agents call it when relevant.
* `memory_promote` is manual by design (LLM cost + curation judgment).
