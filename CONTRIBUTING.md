# Contributing to agent-memory

Thank you for your interest in contributing to `agent-memory`!

`agent-memory` provides a unified, zero-dependency two-layer memory architecture for AI coding assistants (Claude Code, Cursor, Windsurf, Codex, OpenCode, Antigravity, Aider, Goose, Cline, Roo Code, Crush, Pi).

---

## Development Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/kdbhalala/agent-memory.git
   cd agent-memory
   ```

2. **Create a Virtual Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install Package in Editable Mode**:
   ```bash
   pip install -e .
   ```

---

## Running Tests

All core functionality is zero-dependency and tested offline:

```bash
# Run the complete offline test suite (layers, SQLite FTS5, graph engine, integrate)
python3 test_offline.py && python3 eval_l1.py && python3 eval_l2.py && python3 integrate.py test

# Run the comprehensive 11-tier authentic stress test benchmark
python3 stress_test.py

# Check integration detection across assistants
python3 integrate.py status
```

**Rule**: All PRs must pass `python3 test_offline.py && python3 eval_l1.py && python3 eval_l2.py && python3 integrate.py test && python3 stress_test.py` before submission.

---

## Architecture Principles

1. **Zero External Dependencies**: The core MCP server, L1 working memory, L2 knowledge graph, and `integrate.py` CLI must rely solely on the Python standard library and built-in `sqlite3`. Do not add required dependencies to `pyproject.toml`.
2. **Speed & Efficiency**: Retrieval should remain sub-millisecond to avoid slowing down agent coding loops.
3. **Graceful Degradation**: If an optional layer or background worker is offline, the system must degrade cleanly without throwing unhandled exceptions.
4. **Tool Independence**: Any new agent integration must work across platforms (Linux, macOS, Windows).
5. **Byte-for-Byte Assistant Parity**: `CLAUDE.md` and `AGENTS.md` must remain 100% byte-for-byte identical at all times (`diff -u CLAUDE.md AGENTS.md` must be empty).

---

## Submitting a Pull Request

1. Fork the repository and create a feature branch from `main`.
2. Ensure your changes follow PEP 8 and include offline tests in `test_offline.py`.
3. Verify that `python test_offline.py` and `python integrate.py test` pass.
4. Submit a Pull Request with a clear description of the problem solved and test results.
