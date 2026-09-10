# agent-memory Integrations Guide

Turnkey cross-agent memory integration for leading AI coding CLIs and IDEs.

`agent-memory` exposes a unified Model Context Protocol (MCP) server that connects your AI coding assistants to a shared two-layer memory backend:
- **L1 (`claude-mem`)**: Rapid, zero-token session working memory (<0.1s). Captures recent decisions, bugfixes, tool executions, and file-level constraints.
- **L2 (`cognee`)**: Durable semantic knowledge graph for architectural principles, long-term trade-offs, and cross-project rules.

All tools share the same memory: an architectural pattern recorded in Claude Code is instantly recallable in Cursor, Codex, OpenCode, Antigravity, or Aider.

---

## Quickstart: Automated Setup with `integrate.py`

The repository includes a zero-dependency CLI (`integrate.py`) that detects installed coding assistants on your system, inspects their configuration, and wires the MCP server and proactive memory rules automatically.

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
Verifies `initialize`, `ping`, and tools registration (`memory_recall`, `memory_recall_deep`, `memory_record`, `memory_promote`).

---

## The Four Standard MCP Tools

Every integrated tool gains access to four tools:

| MCP Tool | Primary Use | Example Query / Action |
|---|---|---|
| `memory_recall` | Fast L1 working memory search | `{"query": "auth migration", "project": "my-app"}` |
| `memory_recall_deep` | Deep L1 + L2 knowledge graph search | `{"query": "state management architecture"}` |
| `memory_record` | Record verified decisions & patterns | `{"text": "Always pass project parameter to worker HTTP search", "title": "Worker search scoping"}` |
| `memory_promote` | Curate session learnings into L2 Cognee | `{"project": "my-app", "limit": 20}` |

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
3. **Architectural Permanence**: High-signal decisions can be curated into Cognee L2 (`memory_promote`), preserving context across weeks and months.
