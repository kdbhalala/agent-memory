# Distribution: PyPI & Homebrew

`agent-memory` is distributed via two official channels: **PyPI** (universal Python/uvx runtime) and **Homebrew** (native macOS/Linux package manager).

---

## 1. PyPI Distribution (`agi-memory`)

Published to [PyPI](https://pypi.org/project/agi-memory/):
```bash
# Direct install
pip install agi-memory

# Isolated CLI installation
pipx install agi-memory

# Zero-install execution
uvx agi-memory
```

### Universal MCP Configuration (PyPI / uvx)
In any assistant config (`.cursor/mcp.json`, `claude_desktop_config.json`, `windsurf.json`):
```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "uvx",
      "args": ["agi-memory"]
    }
  }
}
```

---

## 2. Homebrew Distribution

Distributed via the Homebrew tap `kdbhalala/homebrew-tap`.

### User Installation
```bash
# Install directly from the tap
brew install kdbhalala/tap/agent-memory

# Or tap first
brew tap kdbhalala/tap
brew install agent-memory
```

### Advantages of Homebrew
- Places `agent-memory` globally on `$PATH` (`/opt/homebrew/bin/agent-memory`).
- GUI desktop clients (Cursor, Claude Desktop, Windsurf) can invoke `agent-memory` directly without path resolution or python virtual environment management:
```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "agent-memory"
    }
  }
}
```
- Upgrades are unified: `brew upgrade agent-memory`.

---

## 3. Setting Up the Tap Repository (`kdbhalala/homebrew-tap`)

To initialize the tap on GitHub:
```bash
# 1. Create the public tap repository
gh repo create kdbhalala/homebrew-tap --public --description "Homebrew Tap for agent-memory"

# 2. Clone and add the Formula
git clone https://github.com/kdbhalala/homebrew-tap.git /tmp/homebrew-tap
mkdir -p /tmp/homebrew-tap/Formula
cp Formula/agent-memory.rb /tmp/homebrew-tap/Formula/

# 3. Commit and push
cd /tmp/homebrew-tap
git add Formula/agent-memory.rb
git commit -m "feat: add agent-memory formula"
git push origin main
```

---

## 4. Release Automation

The `.github/workflows/release.yml` workflow automatically:
1. Runs the full offline test suite across all engines and layers.
2. Builds the source distribution (`.tar.gz`) and binary wheel (`.whl`).
3. Publishes to PyPI via PyPI Trusted Publishing.
4. Generates a GitHub Release with distribution assets.
