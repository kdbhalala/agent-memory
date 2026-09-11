# agent-memory Integrations Guide

Turnkey cross-agent memory integration for leading AI coding CLIs and IDEs.

`agent-memory` exposes a unified Model Context Protocol (MCP) server that connects your AI coding assistants to a shared two-layer memory backend:
- **L1 Working Memory (`SessionLayer`)**: Rapid, zero-token session working memory (<2ms via SQLite FTS5). Captures recent decisions, bugfixes, tool executions, and file-level constraints.
- **L2 Knowledge Graph (`GraphLayer`)**: Native SQLite knowledge graph with multi-hop recursive traversal (<0.35ms) for architectural principles, long-term trade-offs, and cross-project rules.

All tools share the same memory: an architectural pattern recorded in Claude Code is instantly recallable in Cursor, Codex, OpenCode, Antigravity, or Aider.

---

## Quickstart: Automated Setup

### Option 1: Zero-Dependency One-Line Installer
```bash
curl -fsSL https://raw.githubusercontent.com/kdbhalala/agent-memory/main/install.sh | bash
```
Installs CLI wrappers to `~/.local/bin`, initializes the vault, wires all detected assistants, and tests the MCP handshake in under 2 seconds.

### Option 2: Python Integration CLI (`integrate.py`)
The repository includes a zero-dependency CLI (`integrate.py` / `agent-integrate`) that detects installed coding assistants on your system, inspects their configuration, and wires the MCP server and proactive memory rules automatically.

### 1. Check Status
Inspect all supported tools on your machine:
```bash
python integrate.py status
```
Output:
```text
agent-memory Tool Integrations Status (scope: user)
==============================================================================
Tool                   Detected   Configured   Rules      Config Path
------------------------------------------------------------------------------
Claude Code            ✓          ✓ Yes        ✓ Yes      ~/.claude.json
Cursor                 ✓          ✓ Yes        ✓ Yes      ~/.cursor/mcp.json
Windsurf               -          ✗ No         ✗ No       ~/.codeium/windsurf/mcp_config.json
OpenAI Codex           ✓          ✓ Yes        ✓ Yes      ~/.codex/config.toml
OpenCode               ✓          ✓ Yes        ✓ Yes      ~/.config/opencode/opencode.jsonc
Antigravity CLI (agy)  ✓          ✓ Yes        ✓ Yes      ~/.gemini/config/mcp_config.json
Aider                  -          ✗ No         ✗ No       ~/.aider.conf.yml
Goose                  -          ✗ No         ✗ No       ~/.config/goose/config.yaml
Cline (VS Code)        ✓          ✗ No         ✗ No       ~/Library/Application Support/Code/...
Roo Code (VS Code)     ✓          ✗ No         ✗ No       ~/Library/Application Support/Code/...
Crush                  ✓          ✓ Yes        ✓ Yes      ~/.config/crush/mcp.json
Pi                     ✓          ✓ Yes        ✓ Yes      ~/.pi/agent/mcp.json
------------------------------------------------------------------------------
```

### 2. Install to All Detected Tools
Wire the MCP server and memory discipline rules across all detected tools in one command:
```bash
python integrate.py install all
```
Or target specific tools:
```bash
python integrate.py install claude cursor codex
```

### 3. Verify MCP Server Handshake
Run the automated stdio protocol verification:
```bash
python integrate.py test
```
Verifies `initialize`, `ping`, and tools registration (`memory_recall`, `memory_recall_deep`, `memory_record`, `memory_promote`, `memory_sync`, `memory_pin`, `memory_unpin`, `memory_blocks`, `memory_bootstrap`).

---

---

## The Standard MCP Tools

Every integrated tool gains access to 9 native tools:

| MCP Tool | Primary Use | Example Query / Action |
|---|---|---|
| `memory_recall` | Fast L1 working memory search | `{"query": "auth migration", "project": "my-app"}` |
| `memory_recall_deep` | Deep L1 + L2 knowledge graph search | `{"query": "state management architecture"}` |
| `memory_record` | In-flight curation, graph synthesis & conflict steering | `{"text": "Use SQLite FTS5", "title": "DB Arch", "category": "architecture", "supersedes": "#101", "relations": [{"source": "App", "relation": "USES", "target": "SQLite"}]}` |
| `memory_promote` | Curate session learnings into L2 Knowledge Graph | `{"project": "my-app", "limit": 20}` |
| `memory_sync` | Synchronize vault with Git/GitHub & run compaction | `{"action": "sync"}` / `{"action": "dedupe"}` |
| `memory_pin` | Pin mission-critical invariants to Core Memory | `{"key": "zero_pip_deps", "content": "Zero external pip dependencies"}` |
| `memory_unpin` | Unpin an invariant from Core Memory | `{"key": "zero_pip_deps"}` |
| `memory_blocks` | List active Core Memory blocks | `{"project": "agent-memory"}` |
| `memory_bootstrap` | Seed initial memories from Git history & README | `{"repo": ".", "project": "my-app"}` |

---

## Lifecycle Hooks Automation (`session-start`, `pre-compact`, `session-end`, `pre-commit`)

Agent memory automatically triggers lifecycle hooks during coding assistant workflows:
1. **`session-start` / `PreInvocation`**: Proactively fetches pinned Core Memory blocks and top project precedents, injecting them directly into the assistant's starting context prompt.
2. **`pre-compact`**: Scans unpromoted high-signal working memories and clusters them into L2 knowledge graph triples right before context window compaction.
3. **`session-end` / `Stop`**: Instantly commits vault changes and triggers a background Git push to your private remote.
4. **`pre-commit`**: Validates offline test suites and memory invariants before code is committed.

### Automated Setup (Default)
Hooks are configured automatically when running `install all` or `scaffold`:
```bash
python integrate.py install all
python integrate.py scaffold .
```

### Manual Hooks Command
If you install or update coding tools after initial setup, manage hooks directly:
```bash
# Install hooks to all detected tools
agent-memory integrate hooks all
# Or with agent-integrate
agent-integrate hooks claude agy git

# Target specific tool
agent-integrate hooks agy
agent-integrate hooks claude

# Project-level scope
agent-integrate hooks all --scope project

# Uninstall hooks
agent-integrate hooks all --uninstall
```

---

## Manual Configuration by Tool

If you prefer manual configuration or need to configure a custom environment, copy and paste the snippets below. Replace `<PYTHON>` with your virtual environment's Python path (e.g. `/path/to/agent-memory/.venv/bin/python`) and `<SERVER>` with `/path/to/agent-memory/mcp_server.py`.

---

### 1. Claude Code (Anthropic CLI)

#### Option A: 1-Line CLI
```bash
claude mcp add --scope user agent-memory -- <PYTHON> <SERVER>
```

#### Option B: Config File (`~/.claude.json`)
```json
{
  "mcpServers": {
    "agent-memory": {
      "type": "stdio",
      "command": "<PYTHON>",
      "args": ["<SERVER>"],
      "env": {}
    }
  }
}
```

#### Global Rule (`~/.claude/CLAUDE.md` or workspace `CLAUDE.md`)
```markdown
# Agent Memory Discipline (agent-memory MCP)

When working on non-trivial tasks, debugging errors, or establishing patterns:
1. **Recall Prior Precedents**: Call `memory_recall` on the `agent-memory` MCP server with relevant keywords and project name to check past decisions and established patterns before making assumptions.
2. **Deep Architecture Search**: If L1 recall is thin or high-level architecture/cross-project context is needed, use `memory_recall_deep`.
3. **Record Verified Learnings**: When settling an architectural pattern, fixing a recurring bug, or agreeing on project conventions, call `memory_record` so all coding agents stay in sync.
```

---

### 2. Cursor (AI Code Editor)

#### Global Config (`~/.cursor/mcp.json`) or Project (`.cursor/mcp.json`)
```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "<PYTHON>",
      "args": ["<SERVER>"]
    }
  }
}
```

#### Rule File (`~/.cursor/rules/agent-memory.mdc`)
```markdown
---
description: Proactive memory recall and recording using agent-memory MCP
alwaysApply: true
---

# Agent Memory Discipline (agent-memory MCP)

When starting non-trivial tasks, debugging errors, or making architectural decisions:
1. **Recall Prior Precedents**: Call `memory_recall` on `agent-memory` MCP with relevant keywords and project name to check past decisions and established patterns.
2. **Deep Search**: If L1 recall is thin or foundational architecture is involved, use `memory_recall_deep`.
3. **Record Learnings**: When settling an architectural pattern or resolving a non-trivial bug, call `memory_record` to save the decision for all agents.
```

---

### 3. Windsurf (Codeium)

#### Config (`~/.codeium/windsurf/mcp_config.json`)
```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "<PYTHON>",
      "args": ["<SERVER>"]
    }
  }
}
```

#### Rules (`~/.windsurfrules` or project `.windsurfrules`)
Append the standard Memory Discipline section from above.

---

### 4. OpenAI Codex CLI

#### Config (`~/.codex/config.toml`)
```toml
[mcp_servers.agent-memory]
command = "<PYTHON>"
args = ["<SERVER>"]
```

#### Instructions (`~/.codex/AGENTS.md` or project `AGENTS.md`)
Append the standard Memory Discipline section from above.

---

### 5. OpenCode CLI

#### Config (`~/.config/opencode/opencode.jsonc` or `opencode.json`)
```json
{
  "mcp": {
    "agent-memory": {
      "type": "local",
      "command": ["<PYTHON>", "<SERVER>"],
      "enabled": true
    }
  },
  "instructions": [
    "~/.config/opencode/rules.md"
  ]
}
```

#### Rules (`~/.config/opencode/rules.md`)
Append the standard Memory Discipline section from above.

---

### 6. Antigravity CLI & IDE (`agy`)

#### MCP Config (`~/.gemini/config/mcp_config.json`)
```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "<PYTHON>",
      "args": ["<SERVER>"],
      "disabled": false
    }
  }
}
```

#### Agent Skill (`~/.gemini/config/skills/agent-memory/SKILL.md`)
Created automatically by `integrate.py install agy`. Provides tool metadata and proactive guidelines to the Antigravity planner.

#### Rules (`~/.gemini/GEMINI.md` or workspace `AGENTS.md`)
Append the standard Memory Discipline section from above.

---

### 7. Aider CLI

#### Config (`~/.aider.conf.yml` or project `.aider.conf.yml`)
```yaml
mcp-servers:
  agent-memory:
    command: <PYTHON>
    args:
      - <SERVER>
```

#### Conventions (`~/.aider.conventions.md` or `CONVENTIONS.md`)
```markdown
# Agent Memory Discipline

Use the `agent-memory` MCP server tools before making assumptions:
- `memory_recall(query, project)`: Retrieve recent session decisions, patterns, or bug fixes.
- `memory_recall_deep(query, project)`: Retrieve durable architecture rules and decisions.
- `memory_record(text, title, project)`: Record newly resolved patterns, fixes, or rules.
```

---

### 8. Goose CLI

#### Config (`~/.config/goose/config.yaml`)
```yaml
extensions:
  agent-memory:
    type: stdio
    cmd: <PYTHON>
    args:
      - <SERVER>
    enabled: true
```

#### Hints (`~/.config/goose/hints.md` or project `.goosehints`)
Append the standard Memory Discipline section from above.

---

### 9. Cline & Roo Code (VS Code Extensions)

#### Settings File
- **macOS**: `~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json` (Cline) or `.../rooveterinaryinc.roo-cline/settings/cline_mcp_settings.json` (Roo Code)
- **Linux**: `~/.config/Code/User/globalStorage/...`
- **Windows**: `%APPDATA%\Code\User\globalStorage\...`

```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "<PYTHON>",
      "args": ["<SERVER>"],
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

#### Project Rules (`.clinerules` or `.roomodes`)
Append the standard Memory Discipline section from above.

---

### 10. Crush & Pi CLIs

#### Crush Config (`~/.config/crush/mcp.json`)
```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "<PYTHON>",
      "args": ["<SERVER>"]
    }
  }
}
```

#### Pi Config (`~/.pi/agent/mcp.json`)
```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "<PYTHON>",
      "args": ["<SERVER>"]
    }
  }
}
```

---

## Why Memory Discipline Rules Matter

MCP gives an agent *access* to tools, but large language models do not instinctively know to query memory on their own unless prompted. 

By injecting the **Agent Memory Discipline** rules:
1. **Zero Hallucinated Conventions**: The model actively queries `memory_recall` before making assumptions about project patterns or test setups.
2. **Immediate Cross-Tool Sync**: When an agent settles a pattern or fixes a non-trivial bug, it calls `memory_record`. The fix is immediately indexed into SQLite FTS and Chroma, making it instantly discoverable by all other agents.
3. **Architectural Permanence**: High-signal decisions can be curated into L2 Knowledge Graph (`memory_promote`), preserving context across weeks and months.
