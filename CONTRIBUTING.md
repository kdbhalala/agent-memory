# Contributing to agi-memory

Thank you for your interest in contributing to `agi-memory`!

`agi-memory` provides a unified, zero-dependency four-pillar cognitive memory framework (Epistemic, Semantic, Episodic, Structural Code Graph) with a 15-tool MCP server for AI coding assistants (Claude Code, Cursor, Windsurf, Codex, OpenCode, Antigravity, Aider, Goose, Cline, Roo Code, Crush, Pi).

---

## Development Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/kdbhalala/agi-memory.git
   cd agi-memory
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
python3 tests/test_offline.py && python3 tests/eval_l1.py && python3 tests/eval_l2.py && agi-integrate test

# Run the adversarial robustness suite (hostile input, corruption, concurrency)
python3 tests/chaos_test.py

# Run the comprehensive 12-tier authentic stress test benchmark
python3 tests/stress_test.py

# Check integration detection across assistants
agi-integrate status
```

**Rule**: All PRs must pass `python3 tests/test_offline.py && python3 tests/eval_l1.py && python3 tests/eval_l2.py && agi-integrate test && python3 tests/chaos_test.py && python3 tests/stress_test.py` before submission.

---

## Architecture Principles

1. **Zero External Dependencies**: The core MCP server, L1 working memory, L2 knowledge graph, L3 episodic layer, L4 structural code graph, and CLI must rely solely on the Python standard library and built-in `sqlite3`. Do not add required dependencies to `pyproject.toml`.
2. **Speed & Efficiency**: Retrieval should remain sub-millisecond (<2ms L1, <0.5ms L2, <0.25ms L3, <0.5ms L4) to avoid slowing down agent coding loops.
3. **Graceful Degradation**: If an optional layer or background worker is offline, the system must degrade cleanly without throwing unhandled exceptions.
4. **Tool Independence**: Any new agent integration must work across platforms (Linux, macOS, Windows).
5. **Byte-for-Byte Assistant Parity**: `CLAUDE.md` and `AGENTS.md` must remain 100% byte-for-byte identical at all times (`diff -u CLAUDE.md AGENTS.md` must be empty).

---

## Submitting a Pull Request

1. Fork the repository and create a feature branch from `main`.
2. Ensure your changes follow PEP 8 and include offline tests in `tests/test_offline.py`.
3. Verify that `python3 tests/test_offline.py` and `agi-integrate test` pass.
4. Submit a Pull Request with a clear description of the problem solved and test results.
