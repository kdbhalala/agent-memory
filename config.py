"""Configuration and path resolution for agent-memory.

Single Source of Truth (SSoT) for paths, directories, and environment variable resolution.
Zero external dependencies (stdlib only).
"""
from __future__ import annotations

import os
from pathlib import Path

# Base directories
DATA_DIR = Path(os.environ.get("AGENT_MEMORY_DIR", Path.home() / ".agent-memory"))
VAULT_DIR = Path(os.environ.get("AGENT_MEMORY_VAULT", DATA_DIR / "vault"))
DEFAULT_DB = Path(os.environ.get("AGENT_MEMORY_DB", DATA_DIR / "memory.db"))
SESSION_DB = DEFAULT_DB
GRAPH_DB = Path(os.environ.get("AGENT_MEMORY_GRAPH_DB", DEFAULT_DB))
LEGACY_CLAUDE_MEM_DB = Path(os.environ.get("CLAUDE_MEM_DB", Path.home() / ".claude-mem" / "claude-mem.db"))
CLAUDE_MEM_DB = LEGACY_CLAUDE_MEM_DB
SYNC_CONFIG_FILE = DATA_DIR / "sync.json"
DEFAULT_STATE_FILE = Path(os.environ.get("AGENT_MEMORY_STATE", DATA_DIR / "promoted.json"))


def get_data_dir() -> Path:
    """Return active data directory, respecting AGENT_MEMORY_DIR."""
    env = os.environ.get("AGENT_MEMORY_DIR")
    target = Path(env) if env else Path.home() / ".agent-memory"
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_vault_dir(vault_dir: Path | str | None = None) -> Path:
    """Return active vault directory, respecting AGENT_MEMORY_VAULT or argument."""
    if vault_dir:
        target = Path(vault_dir)
    else:
        env = os.environ.get("AGENT_MEMORY_VAULT")
        target = Path(env) if env else get_data_dir() / "vault"
    target.mkdir(parents=True, exist_ok=True)
    return target


def get_default_db() -> Path:
    """Resolve active database path dynamically.

    Priority:
    1. AGENT_MEMORY_DB env var
    2. CLAUDE_MEM_DB env var
    3. Legacy ~/.claude-mem/claude-mem.db if exists
    4. ~/.agent-memory/memory.db (DEFAULT_DB)
    """
    env_path = os.getenv("AGENT_MEMORY_DB") or os.getenv("CLAUDE_MEM_DB")
    if env_path:
        return Path(env_path)
    if LEGACY_CLAUDE_MEM_DB.exists():
        return LEGACY_CLAUDE_MEM_DB
    env_dir = os.environ.get("AGENT_MEMORY_DIR")
    base = Path(env_dir) if env_dir else Path.home() / ".agent-memory"
    return base / "memory.db"


def get_graph_db() -> Path:
    """Resolve active graph database path dynamically."""
    env_path = os.getenv("AGENT_MEMORY_GRAPH_DB")
    if env_path:
        return Path(env_path)
    return get_default_db()


def get_state_path() -> Path:
    """Resolve state file path dynamically for promotion tracking."""
    env = os.environ.get("AGENT_MEMORY_STATE")
    if env:
        return Path(env)
    v_dir = get_vault_dir()
    vault_state = v_dir / "promoted.json"
    if vault_state.parent.exists():
        return vault_state
    return get_data_dir() / "promoted.json"
