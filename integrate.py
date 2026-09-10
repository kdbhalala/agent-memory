#!/usr/bin/env python3
"""agent-memory turnkey integration tool for AI coding CLIs and IDEs.

Supports:
- Claude Code
- Cursor
- Windsurf
- OpenAI Codex
- OpenCode
- Antigravity CLI (agy)
- Aider
- Goose
- Cline
- Roo Code
- Crush
- Pi

Usage:
  python integrate.py status
  python integrate.py install [TOOL ... | all] [--scope user|project]
  python integrate.py uninstall [TOOL ... | all] [--scope user|project]
  python integrate.py test
  python integrate.py generate [TOOL]
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

REPO_DIR = Path(__file__).resolve().parent
DEFAULT_SERVER = REPO_DIR / "mcp_server.py"

MEMORY_RULES_MD = """<!-- AGENT_MEMORY_DISCIPLINE_START -->
# Agent Memory Discipline (agent-memory MCP)

When working on non-trivial tasks, debugging errors, or establishing patterns:
1. **Recall Prior Precedents**: Call `memory_recall` on the `agent-memory` MCP server with relevant keywords and project name to check past decisions and established patterns before making assumptions.
2. **Deep Architecture Search**: If L1 recall is thin or high-level architecture/cross-project context is needed, use `memory_recall_deep`.
3. **Record Verified Learnings**: When settling an architectural pattern, fixing a recurring bug, or agreeing on project conventions, call `memory_record` so all coding agents stay in sync.
<!-- AGENT_MEMORY_DISCIPLINE_END -->
"""

CURSOR_RULES_MDC = """---
description: Proactive memory recall and recording using agent-memory MCP
alwaysApply: true
---

# Agent Memory Discipline (agent-memory MCP)

When starting non-trivial tasks, debugging errors, or making architectural decisions:
1. **Recall Prior Precedents**: Call `memory_recall` on `agent-memory` MCP with relevant keywords and project name to check past decisions and established patterns.
2. **Deep Search**: If L1 recall is thin or foundational architecture is involved, use `memory_recall_deep`.
3. **Record Learnings**: When settling an architectural pattern or resolving a non-trivial bug, call `memory_record` to save the decision for all agents.
"""

AIDER_RULES_MD = """<!-- AGENT_MEMORY_DISCIPLINE_START -->
# Agent Memory Discipline

Use the `agent-memory` MCP server tools before making assumptions:
- `memory_recall(query, project)`: Retrieve recent session decisions, patterns, or bug fixes.
- `memory_recall_deep(query, project)`: Retrieve durable architecture rules and decisions.
- `memory_record(text, title, project)`: Record newly resolved patterns, fixes, or rules.
<!-- AGENT_MEMORY_DISCIPLINE_END -->
"""


def detect_python() -> str:
    """Find the best python executable for the agent-memory MCP server."""
    venv_py = REPO_DIR / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    if sys.prefix != sys.base_prefix:
        prefix_py = Path(sys.prefix) / "bin" / "python"
        if prefix_py.exists():
            return str(prefix_py)
    which_py = shutil.which("python3") or shutil.which("python")
    if which_py:
        return which_py
    return sys.executable


def detect_server() -> str:
    """Path to mcp_server.py."""
    if DEFAULT_SERVER.exists():
        return str(DEFAULT_SERVER)
    return str(REPO_DIR / "mcp_server.py")


def strip_jsonc_comments(text: str) -> str:
    """Strip // and /* */ comments from JSONC without touching strings/URLs."""
    result: List[str] = []
    in_string = False
    escape = False
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if in_string:
            result.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
        else:
            if c == '"':
                in_string = True
                result.append(c)
                i += 1
            elif c == "/" and i + 1 < n and text[i + 1] == "/":
                i += 2
                while i < n and text[i] not in ("\r", "\n"):
                    i += 1
            elif c == "/" and i + 1 < n and text[i + 1] == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
            else:
                result.append(c)
                i += 1
    return "".join(result)


def read_json_safe(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        try:
            return json.loads(raw, strict=False)
        except Exception:
            clean = strip_jsonc_comments(raw)
            return json.loads(clean, strict=False)
    except Exception:
        return None


def write_json_safe(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def append_rules_safe(path: Path, rules_text: str, marker: str = "AGENT_MEMORY_DISCIPLINE_START") -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        content = path.read_text(encoding="utf-8")
        if marker in content or "Agent Memory Discipline" in content:
            return False  # Already installed
        new_content = content.rstrip() + "\n\n" + rules_text.strip() + "\n"
    else:
        new_content = rules_text.strip() + "\n"
    path.write_text(new_content, encoding="utf-8")
    return True


def remove_rules_safe(path: Path, marker_start: str = "<!-- AGENT_MEMORY_DISCIPLINE_START -->",
                      marker_end: str = "<!-- AGENT_MEMORY_DISCIPLINE_END -->") -> bool:
    if not path.exists():
        return False
    content = path.read_text(encoding="utf-8")
    if marker_start in content and marker_end in content:
        pattern = re.compile(rf"{re.escape(marker_start)}.*?{re.escape(marker_end)}\n?", re.DOTALL)
        new_content = pattern.sub("", content)
        path.write_text(new_content.strip() + "\n", encoding="utf-8")
        return True
    return False


def inject_yaml_subdict(text: str, parent_key: str, child_key: str, child_lines: List[str]) -> str:
    """Inject child_key and its indented block under parent_key in YAML text."""
    lines = text.splitlines()
    parent_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith(parent_key + ":"):
            parent_idx = i
            break

    indent = "  "
    formatted = [indent + l for l in child_lines]

    if parent_idx == -1:
        if text.strip():
            return text.rstrip() + f"\n\n{parent_key}:\n" + "\n".join(formatted) + "\n"
        return f"{parent_key}:\n" + "\n".join(formatted) + "\n"

    for j in range(parent_idx + 1, len(lines)):
        line = lines[j]
        if line and not line.startswith(" ") and not line.startswith("\t"):
            break
        if line.strip().startswith(child_key + ":"):
            return text

    new_lines = lines[:parent_idx + 1] + formatted + lines[parent_idx + 1:]
    return "\n".join(new_lines) + "\n"


def remove_yaml_subdict(text: str, parent_key: str, child_key: str) -> str:
    """Remove child_key block under parent_key in YAML text."""
    lines = text.splitlines()
    parent_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith(parent_key + ":"):
            parent_idx = i
            break
    if parent_idx == -1:
        return text

    child_start = -1
    for j in range(parent_idx + 1, len(lines)):
        line = lines[j]
        if line and not line.startswith(" ") and not line.startswith("\t"):
            break
        if line.strip().startswith(child_key + ":"):
            child_start = j
            break

    if child_start == -1:
        return text

    child_end = len(lines)
    for k in range(child_start + 1, len(lines)):
        line = lines[k]
        if line and not line.startswith(" ") and not line.startswith("\t"):
            child_end = k
            break
        indent_level = len(line) - len(line.lstrip())
        if indent_level <= 2 and line.strip() and not line.strip().startswith("#"):
            child_end = k
            break

    new_lines = lines[:child_start] + lines[child_end:]
    return "\n".join(new_lines) + "\n"


class ToolIntegration:
    """Base class for tool integrations."""
    name: str
    display_name: str

    def is_detected(self) -> bool:
        raise NotImplementedError

    def is_configured(self, scope: str = "user") -> bool:
        raise NotImplementedError

    def are_rules_installed(self, scope: str = "user") -> bool:
        raise NotImplementedError

    def get_config_path(self, scope: str = "user") -> Path:
        raise NotImplementedError

    def get_rules_path(self, scope: str = "user") -> Optional[Path]:
        raise NotImplementedError

    def install(self, py_path: str, srv_path: str, scope: str = "user") -> Tuple[bool, str]:
        raise NotImplementedError

    def uninstall(self, scope: str = "user") -> Tuple[bool, str]:
        raise NotImplementedError

    def generate_config(self, py_path: str, srv_path: str) -> str:
        raise NotImplementedError

    def generate_rules(self) -> str:
        return MEMORY_RULES_MD.strip()


class ClaudeCodeIntegration(ToolIntegration):
    name = "claude"
    display_name = "Claude Code"

    def is_detected(self) -> bool:
        return shutil.which("claude") is not None or (Path.home() / ".claude.json").exists()

    def get_config_path(self, scope: str = "user") -> Path:
        return Path.home() / ".claude.json" if scope == "user" else Path.cwd() / ".claude.json"

    def get_rules_path(self, scope: str = "user") -> Optional[Path]:
        return Path.home() / ".claude" / "CLAUDE.md" if scope == "user" else Path.cwd() / "CLAUDE.md"

    def is_configured(self, scope: str = "user") -> bool:
        cfg = read_json_safe(self.get_config_path(scope))
        return cfg is not None and "agent-memory" in cfg.get("mcpServers", {})

    def are_rules_installed(self, scope: str = "user") -> bool:
        p = self.get_rules_path(scope)
        if not p or not p.exists():
            return False
        return "Agent Memory Discipline" in p.read_text(encoding="utf-8")

    def install(self, py_path: str, srv_path: str, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path) or {}
        if "mcpServers" not in cfg:
            cfg["mcpServers"] = {}
        cfg["mcpServers"]["agent-memory"] = {
            "type": "stdio",
            "command": py_path,
            "args": [srv_path],
            "env": {}
        }
        write_json_safe(cfg_path, cfg)

        rules_path = self.get_rules_path(scope)
        if rules_path:
            append_rules_safe(rules_path, MEMORY_RULES_MD)

        return True, f"Configured {cfg_path} and rules at {rules_path}"

    def uninstall(self, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path)
        if cfg and "mcpServers" in cfg and "agent-memory" in cfg["mcpServers"]:
            del cfg["mcpServers"]["agent-memory"]
            write_json_safe(cfg_path, cfg)
        rules_path = self.get_rules_path(scope)
        if rules_path:
            remove_rules_safe(rules_path)
        return True, f"Removed from {cfg_path}"

    def generate_config(self, py_path: str, srv_path: str) -> str:
        return json.dumps({
            "mcpServers": {
                "agent-memory": {
                    "type": "stdio",
                    "command": py_path,
                    "args": [srv_path],
                    "env": {}
                }
            }
        }, indent=2)


class CursorIntegration(ToolIntegration):
    name = "cursor"
    display_name = "Cursor"

    def is_detected(self) -> bool:
        return (Path.home() / ".cursor").exists() or shutil.which("cursor") is not None or Path("/Applications/Cursor.app").exists()

    def get_config_path(self, scope: str = "user") -> Path:
        return Path.home() / ".cursor" / "mcp.json" if scope == "user" else Path.cwd() / ".cursor" / "mcp.json"

    def get_rules_path(self, scope: str = "user") -> Optional[Path]:
        return Path.home() / ".cursor" / "rules" / "agent-memory.mdc" if scope == "user" else Path.cwd() / ".cursor" / "rules" / "agent-memory.mdc"

    def is_configured(self, scope: str = "user") -> bool:
        cfg = read_json_safe(self.get_config_path(scope))
        return cfg is not None and "agent-memory" in cfg.get("mcpServers", {})

    def are_rules_installed(self, scope: str = "user") -> bool:
        p = self.get_rules_path(scope)
        return p is not None and p.exists()

    def install(self, py_path: str, srv_path: str, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path) or {}
        if "mcpServers" not in cfg:
            cfg["mcpServers"] = {}
        cfg["mcpServers"]["agent-memory"] = {
            "command": py_path,
            "args": [srv_path]
        }
        write_json_safe(cfg_path, cfg)

        rules_path = self.get_rules_path(scope)
        if rules_path:
            rules_path.parent.mkdir(parents=True, exist_ok=True)
            rules_path.write_text(CURSOR_RULES_MDC.strip() + "\n", encoding="utf-8")

        return True, f"Configured {cfg_path} and rule at {rules_path}"

    def uninstall(self, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path)
        if cfg and "mcpServers" in cfg and "agent-memory" in cfg["mcpServers"]:
            del cfg["mcpServers"]["agent-memory"]
            write_json_safe(cfg_path, cfg)
        rules_path = self.get_rules_path(scope)
        if rules_path and rules_path.exists():
            rules_path.unlink()
        return True, f"Removed from {cfg_path}"

    def generate_config(self, py_path: str, srv_path: str) -> str:
        return json.dumps({
            "mcpServers": {
                "agent-memory": {
                    "command": py_path,
                    "args": [srv_path]
                }
            }
        }, indent=2)

    def generate_rules(self) -> str:
        return CURSOR_RULES_MDC.strip()


class WindsurfIntegration(ToolIntegration):
    name = "windsurf"
    display_name = "Windsurf"

    def is_detected(self) -> bool:
        return (Path.home() / ".codeium" / "windsurf").exists() or shutil.which("windsurf") is not None or Path("/Applications/Windsurf.app").exists()

    def get_config_path(self, scope: str = "user") -> Path:
        return Path.home() / ".codeium" / "windsurf" / "mcp_config.json" if scope == "user" else Path.cwd() / ".codeium" / "windsurf" / "mcp_config.json"

    def get_rules_path(self, scope: str = "user") -> Optional[Path]:
        return Path.home() / ".windsurfrules" if scope == "user" else Path.cwd() / ".windsurfrules"

    def is_configured(self, scope: str = "user") -> bool:
        cfg = read_json_safe(self.get_config_path(scope))
        return cfg is not None and "agent-memory" in cfg.get("mcpServers", {})

    def are_rules_installed(self, scope: str = "user") -> bool:
        p = self.get_rules_path(scope)
        return p is not None and p.exists() and "Agent Memory Discipline" in p.read_text(encoding="utf-8")

    def install(self, py_path: str, srv_path: str, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path) or {}
        if "mcpServers" not in cfg:
            cfg["mcpServers"] = {}
        cfg["mcpServers"]["agent-memory"] = {
            "command": py_path,
            "args": [srv_path]
        }
        write_json_safe(cfg_path, cfg)

        rules_path = self.get_rules_path(scope)
        if rules_path:
            append_rules_safe(rules_path, MEMORY_RULES_MD)

        return True, f"Configured {cfg_path} and rules at {rules_path}"

    def uninstall(self, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path)
        if cfg and "mcpServers" in cfg and "agent-memory" in cfg["mcpServers"]:
            del cfg["mcpServers"]["agent-memory"]
            write_json_safe(cfg_path, cfg)
        rules_path = self.get_rules_path(scope)
        if rules_path:
            remove_rules_safe(rules_path)
        return True, f"Removed from {cfg_path}"

    def generate_config(self, py_path: str, srv_path: str) -> str:
        return json.dumps({
            "mcpServers": {
                "agent-memory": {
                    "command": py_path,
                    "args": [srv_path]
                }
            }
        }, indent=2)


class CodexIntegration(ToolIntegration):
    name = "codex"
    display_name = "OpenAI Codex"

    def is_detected(self) -> bool:
        return shutil.which("codex") is not None or (Path.home() / ".codex").exists()

    def get_config_path(self, scope: str = "user") -> Path:
        return Path.home() / ".codex" / "config.toml" if scope == "user" else Path.cwd() / ".codex" / "config.toml"

    def get_rules_path(self, scope: str = "user") -> Optional[Path]:
        return Path.home() / ".codex" / "AGENTS.md" if scope == "user" else Path.cwd() / "AGENTS.md"

    def is_configured(self, scope: str = "user") -> bool:
        p = self.get_config_path(scope)
        if not p.exists():
            return False
        content = p.read_text(encoding="utf-8")
        return "[mcp_servers.agent-memory]" in content

    def are_rules_installed(self, scope: str = "user") -> bool:
        p = self.get_rules_path(scope)
        return p is not None and p.exists() and ("Agent Memory Discipline" in p.read_text(encoding="utf-8") or "agent-memory" in p.read_text(encoding="utf-8"))

    def install(self, py_path: str, srv_path: str, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        content = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""

        snippet = f'\n[mcp_servers.agent-memory]\ncommand = "{py_path}"\nargs = ["{srv_path}"]\n'
        if "[mcp_servers.agent-memory]" not in content:
            content = content.rstrip() + "\n" + snippet
            cfg_path.write_text(content, encoding="utf-8")

        rules_path = self.get_rules_path(scope)
        if rules_path:
            append_rules_safe(rules_path, MEMORY_RULES_MD)

        return True, f"Configured {cfg_path} and rules at {rules_path}"

    def uninstall(self, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        if cfg_path.exists():
            content = cfg_path.read_text(encoding="utf-8")
            pattern = re.compile(r'\[mcp_servers\.agent-memory\]\s*command\s*=\s*".*?"\s*args\s*=\s*\[.*?\]\n?', re.DOTALL)
            new_content = pattern.sub("", content)
            cfg_path.write_text(new_content, encoding="utf-8")
        rules_path = self.get_rules_path(scope)
        if rules_path:
            remove_rules_safe(rules_path)
        return True, f"Removed from {cfg_path}"

    def generate_config(self, py_path: str, srv_path: str) -> str:
        return f'[mcp_servers.agent-memory]\ncommand = "{py_path}"\nargs = ["{srv_path}"]'


class OpenCodeIntegration(ToolIntegration):
    name = "opencode"
    display_name = "OpenCode"

    def is_detected(self) -> bool:
        return shutil.which("opencode") is not None or (Path.home() / ".config" / "opencode").exists()

    def get_config_path(self, scope: str = "user") -> Path:
        user_jsonc = Path.home() / ".config" / "opencode" / "opencode.jsonc"
        user_json = Path.home() / ".config" / "opencode" / "opencode.json"
        if scope == "user":
            return user_jsonc if user_jsonc.exists() else user_json
        proj_jsonc = Path.cwd() / "opencode.jsonc"
        return proj_jsonc if proj_jsonc.exists() else Path.cwd() / "opencode.json"

    def get_rules_path(self, scope: str = "user") -> Optional[Path]:
        return Path.home() / ".config" / "opencode" / "rules.md" if scope == "user" else Path.cwd() / "AGENTS.md"

    def is_configured(self, scope: str = "user") -> bool:
        cfg = read_json_safe(self.get_config_path(scope))
        return cfg is not None and "agent-memory" in cfg.get("mcp", {})

    def are_rules_installed(self, scope: str = "user") -> bool:
        p = self.get_rules_path(scope)
        return p is not None and p.exists() and "Agent Memory Discipline" in p.read_text(encoding="utf-8")

    def install(self, py_path: str, srv_path: str, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path) or {}
        if "mcp" not in cfg:
            cfg["mcp"] = {}
        cfg["mcp"]["agent-memory"] = {
            "type": "local",
            "command": [py_path, srv_path],
            "enabled": True
        }

        rules_path = self.get_rules_path(scope)
        if rules_path:
            append_rules_safe(rules_path, MEMORY_RULES_MD)
            if scope == "user":
                instructions = cfg.setdefault("instructions", [])
                rules_str = str(rules_path)
                if rules_str not in instructions:
                    instructions.append(rules_str)

        write_json_safe(cfg_path, cfg)
        return True, f"Configured {cfg_path} and rules at {rules_path}"

    def uninstall(self, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path)
        if cfg and "mcp" in cfg and "agent-memory" in cfg["mcp"]:
            del cfg["mcp"]["agent-memory"]
            write_json_safe(cfg_path, cfg)
        rules_path = self.get_rules_path(scope)
        if rules_path:
            remove_rules_safe(rules_path)
        return True, f"Removed from {cfg_path}"

    def generate_config(self, py_path: str, srv_path: str) -> str:
        return json.dumps({
            "mcp": {
                "agent-memory": {
                    "type": "local",
                    "command": [py_path, srv_path],
                    "enabled": True
                }
            }
        }, indent=2)


class AntigravityIntegration(ToolIntegration):
    name = "agy"
    display_name = "Antigravity CLI (agy)"

    def is_detected(self) -> bool:
        return shutil.which("agy") is not None or (Path.home() / ".gemini").exists()

    def get_config_path(self, scope: str = "user") -> Path:
        return Path.home() / ".gemini" / "config" / "mcp_config.json"

    def get_rules_path(self, scope: str = "user") -> Optional[Path]:
        return Path.home() / ".gemini" / "GEMINI.md" if scope == "user" else Path.cwd() / "AGENTS.md"

    def get_skill_path(self) -> Path:
        return Path.home() / ".gemini" / "config" / "skills" / "agent-memory" / "SKILL.md"

    def is_configured(self, scope: str = "user") -> bool:
        cfg = read_json_safe(self.get_config_path(scope))
        return cfg is not None and "agent-memory" in cfg.get("mcpServers", {})

    def are_rules_installed(self, scope: str = "user") -> bool:
        skill_ok = self.get_skill_path().exists()
        rules_p = self.get_rules_path(scope)
        rules_ok = rules_p is not None and rules_p.exists() and ("Agent Memory" in rules_p.read_text(encoding="utf-8") or "agent-memory" in rules_p.read_text(encoding="utf-8"))
        return skill_ok or rules_ok

    def install(self, py_path: str, srv_path: str, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path) or {}
        if "mcpServers" not in cfg:
            cfg["mcpServers"] = {}
        cfg["mcpServers"]["agent-memory"] = {
            "command": py_path,
            "args": [srv_path],
            "disabled": False
        }
        write_json_safe(cfg_path, cfg)

        rules_path = self.get_rules_path(scope)
        if rules_path:
            append_rules_safe(rules_path, MEMORY_RULES_MD)

        return True, f"Configured {cfg_path}"

    def uninstall(self, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path)
        if cfg and "mcpServers" in cfg and "agent-memory" in cfg["mcpServers"]:
            del cfg["mcpServers"]["agent-memory"]
            write_json_safe(cfg_path, cfg)
        return True, f"Removed from {cfg_path}"

    def generate_config(self, py_path: str, srv_path: str) -> str:
        return json.dumps({
            "mcpServers": {
                "agent-memory": {
                    "command": py_path,
                    "args": [srv_path],
                    "disabled": False
                }
            }
        }, indent=2)


class AiderIntegration(ToolIntegration):
    name = "aider"
    display_name = "Aider"

    def is_detected(self) -> bool:
        return shutil.which("aider") is not None or (Path.home() / ".aider.conf.yml").exists()

    def get_config_path(self, scope: str = "user") -> Path:
        return Path.home() / ".aider.conf.yml" if scope == "user" else Path.cwd() / ".aider.conf.yml"

    def get_rules_path(self, scope: str = "user") -> Optional[Path]:
        return Path.home() / ".aider.conventions.md" if scope == "user" else Path.cwd() / "CONVENTIONS.md"

    def is_configured(self, scope: str = "user") -> bool:
        p = self.get_config_path(scope)
        if not p.exists():
            return False
        content = p.read_text(encoding="utf-8")
        return "agent-memory:" in content

    def are_rules_installed(self, scope: str = "user") -> bool:
        p = self.get_rules_path(scope)
        return p is not None and p.exists() and "agent-memory" in p.read_text(encoding="utf-8")

    def install(self, py_path: str, srv_path: str, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        content = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""

        child_lines = [
            "agent-memory:",
            f"  command: {py_path}",
            "  args:",
            f"    - {srv_path}"
        ]
        new_content = inject_yaml_subdict(content, "mcp-servers", "agent-memory", child_lines)
        cfg_path.write_text(new_content, encoding="utf-8")

        rules_path = self.get_rules_path(scope)
        if rules_path:
            append_rules_safe(rules_path, AIDER_RULES_MD)

        return True, f"Configured {cfg_path} and conventions at {rules_path}"

    def uninstall(self, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        if cfg_path.exists():
            content = cfg_path.read_text(encoding="utf-8")
            new_content = remove_yaml_subdict(content, "mcp-servers", "agent-memory")
            cfg_path.write_text(new_content, encoding="utf-8")
        rules_path = self.get_rules_path(scope)
        if rules_path:
            remove_rules_safe(rules_path)
        return True, f"Removed from {cfg_path}"

    def generate_config(self, py_path: str, srv_path: str) -> str:
        return f"mcp-servers:\n  agent-memory:\n    command: {py_path}\n    args:\n      - {srv_path}"

    def generate_rules(self) -> str:
        return AIDER_RULES_MD.strip()


class GooseIntegration(ToolIntegration):
    name = "goose"
    display_name = "Goose"

    def is_detected(self) -> bool:
        return shutil.which("goose") is not None or (Path.home() / ".config" / "goose").exists()

    def get_config_path(self, scope: str = "user") -> Path:
        return Path.home() / ".config" / "goose" / "config.yaml" if scope == "user" else Path.cwd() / ".goosehints"

    def get_rules_path(self, scope: str = "user") -> Optional[Path]:
        return Path.home() / ".config" / "goose" / "hints.md" if scope == "user" else Path.cwd() / ".goosehints"

    def is_configured(self, scope: str = "user") -> bool:
        p = self.get_config_path(scope)
        if not p.exists():
            return False
        content = p.read_text(encoding="utf-8")
        return "agent-memory:" in content

    def are_rules_installed(self, scope: str = "user") -> bool:
        p = self.get_rules_path(scope)
        return p is not None and p.exists() and "Agent Memory" in p.read_text(encoding="utf-8")

    def install(self, py_path: str, srv_path: str, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        content = cfg_path.read_text(encoding="utf-8") if cfg_path.exists() else ""

        child_lines = [
            "agent-memory:",
            "  type: stdio",
            f"  cmd: {py_path}",
            "  args:",
            f"    - {srv_path}",
            "  enabled: true"
        ]
        new_content = inject_yaml_subdict(content, "extensions", "agent-memory", child_lines)
        cfg_path.write_text(new_content, encoding="utf-8")

        rules_path = self.get_rules_path(scope)
        if rules_path:
            append_rules_safe(rules_path, MEMORY_RULES_MD)

        return True, f"Configured {cfg_path} and hints at {rules_path}"

    def uninstall(self, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        if cfg_path.exists():
            content = cfg_path.read_text(encoding="utf-8")
            new_content = remove_yaml_subdict(content, "extensions", "agent-memory")
            cfg_path.write_text(new_content, encoding="utf-8")
        rules_path = self.get_rules_path(scope)
        if rules_path:
            remove_rules_safe(rules_path)
        return True, f"Removed from {cfg_path}"

    def generate_config(self, py_path: str, srv_path: str) -> str:
        return f"extensions:\n  agent-memory:\n    type: stdio\n    cmd: {py_path}\n    args:\n      - {srv_path}\n    enabled: true"


class ClineIntegration(ToolIntegration):
    name = "cline"
    display_name = "Cline (VS Code)"

    def _get_base_dir(self) -> Path:
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings"
        elif sys.platform == "win32":
            return Path(os.environ.get("APPDATA", "")) / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings"
        else:
            return Path.home() / ".config" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings"

    def is_detected(self) -> bool:
        return self._get_base_dir().parent.exists() or shutil.which("code") is not None

    def get_config_path(self, scope: str = "user") -> Path:
        return self._get_base_dir() / "cline_mcp_settings.json"

    def get_rules_path(self, scope: str = "user") -> Optional[Path]:
        return Path.cwd() / ".clinerules"

    def is_configured(self, scope: str = "user") -> bool:
        cfg = read_json_safe(self.get_config_path(scope))
        return cfg is not None and "agent-memory" in cfg.get("mcpServers", {})

    def are_rules_installed(self, scope: str = "user") -> bool:
        p = self.get_rules_path(scope)
        return p is not None and p.exists() and "Agent Memory Discipline" in p.read_text(encoding="utf-8")

    def install(self, py_path: str, srv_path: str, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path) or {}
        if "mcpServers" not in cfg:
            cfg["mcpServers"] = {}
        cfg["mcpServers"]["agent-memory"] = {
            "command": py_path,
            "args": [srv_path],
            "disabled": False,
            "autoApprove": []
        }
        write_json_safe(cfg_path, cfg)

        rules_path = self.get_rules_path(scope)
        if rules_path:
            append_rules_safe(rules_path, MEMORY_RULES_MD)

        return True, f"Configured {cfg_path}"

    def uninstall(self, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path)
        if cfg and "mcpServers" in cfg and "agent-memory" in cfg["mcpServers"]:
            del cfg["mcpServers"]["agent-memory"]
            write_json_safe(cfg_path, cfg)
        return True, f"Removed from {cfg_path}"

    def generate_config(self, py_path: str, srv_path: str) -> str:
        return json.dumps({
            "mcpServers": {
                "agent-memory": {
                    "command": py_path,
                    "args": [srv_path],
                    "disabled": False,
                    "autoApprove": []
                }
            }
        }, indent=2)


class RooCodeIntegration(ToolIntegration):
    name = "roo"
    display_name = "Roo Code (VS Code)"

    def _get_base_dir(self) -> Path:
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings"
        elif sys.platform == "win32":
            return Path(os.environ.get("APPDATA", "")) / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings"
        else:
            return Path.home() / ".config" / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings"

    def is_detected(self) -> bool:
        return self._get_base_dir().parent.exists() or shutil.which("code") is not None

    def get_config_path(self, scope: str = "user") -> Path:
        return self._get_base_dir() / "cline_mcp_settings.json"

    def get_rules_path(self, scope: str = "user") -> Optional[Path]:
        return Path.cwd() / ".roomodes"

    def is_configured(self, scope: str = "user") -> bool:
        cfg = read_json_safe(self.get_config_path(scope))
        return cfg is not None and "agent-memory" in cfg.get("mcpServers", {})

    def are_rules_installed(self, scope: str = "user") -> bool:
        p = self.get_rules_path(scope)
        return p is not None and p.exists() and "Agent Memory Discipline" in p.read_text(encoding="utf-8")

    def install(self, py_path: str, srv_path: str, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path) or {}
        if "mcpServers" not in cfg:
            cfg["mcpServers"] = {}
        cfg["mcpServers"]["agent-memory"] = {
            "command": py_path,
            "args": [srv_path],
            "disabled": False,
            "autoApprove": []
        }
        write_json_safe(cfg_path, cfg)

        rules_path = self.get_rules_path(scope)
        if rules_path:
            append_rules_safe(rules_path, MEMORY_RULES_MD)

        return True, f"Configured {cfg_path}"

    def uninstall(self, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path)
        if cfg and "mcpServers" in cfg and "agent-memory" in cfg["mcpServers"]:
            del cfg["mcpServers"]["agent-memory"]
            write_json_safe(cfg_path, cfg)
        return True, f"Removed from {cfg_path}"

    def generate_config(self, py_path: str, srv_path: str) -> str:
        return json.dumps({
            "mcpServers": {
                "agent-memory": {
                    "command": py_path,
                    "args": [srv_path],
                    "disabled": False,
                    "autoApprove": []
                }
            }
        }, indent=2)


class CrushIntegration(ToolIntegration):
    name = "crush"
    display_name = "Crush"

    def is_detected(self) -> bool:
        return shutil.which("crush") is not None or (Path.home() / ".config" / "crush").exists()

    def get_config_path(self, scope: str = "user") -> Path:
        return Path.home() / ".config" / "crush" / "mcp.json"

    def get_rules_path(self, scope: str = "user") -> Optional[Path]:
        return None

    def is_configured(self, scope: str = "user") -> bool:
        cfg = read_json_safe(self.get_config_path(scope))
        return cfg is not None and "agent-memory" in cfg.get("mcpServers", {})

    def are_rules_installed(self, scope: str = "user") -> bool:
        return True

    def install(self, py_path: str, srv_path: str, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path) or {}
        if "mcpServers" not in cfg:
            cfg["mcpServers"] = {}
        cfg["mcpServers"]["agent-memory"] = {
            "command": py_path,
            "args": [srv_path]
        }
        write_json_safe(cfg_path, cfg)
        return True, f"Configured {cfg_path}"

    def uninstall(self, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path)
        if cfg and "mcpServers" in cfg and "agent-memory" in cfg["mcpServers"]:
            del cfg["mcpServers"]["agent-memory"]
            write_json_safe(cfg_path, cfg)
        return True, f"Removed from {cfg_path}"

    def generate_config(self, py_path: str, srv_path: str) -> str:
        return json.dumps({
            "mcpServers": {
                "agent-memory": {
                    "command": py_path,
                    "args": [srv_path]
                }
            }
        }, indent=2)


class PiIntegration(ToolIntegration):
    name = "pi"
    display_name = "Pi"

    def is_detected(self) -> bool:
        return shutil.which("pi") is not None or (Path.home() / ".pi").exists()

    def get_config_path(self, scope: str = "user") -> Path:
        return Path.home() / ".pi" / "agent" / "mcp.json"

    def get_rules_path(self, scope: str = "user") -> Optional[Path]:
        return None

    def is_configured(self, scope: str = "user") -> bool:
        cfg = read_json_safe(self.get_config_path(scope))
        return cfg is not None and "agent-memory" in cfg.get("mcpServers", {})

    def are_rules_installed(self, scope: str = "user") -> bool:
        return True

    def install(self, py_path: str, srv_path: str, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path) or {}
        if "mcpServers" not in cfg:
            cfg["mcpServers"] = {}
        cfg["mcpServers"]["agent-memory"] = {
            "command": py_path,
            "args": [srv_path]
        }
        write_json_safe(cfg_path, cfg)
        return True, f"Configured {cfg_path}"

    def uninstall(self, scope: str = "user") -> Tuple[bool, str]:
        cfg_path = self.get_config_path(scope)
        cfg = read_json_safe(cfg_path)
        if cfg and "mcpServers" in cfg and "agent-memory" in cfg["mcpServers"]:
            del cfg["mcpServers"]["agent-memory"]
            write_json_safe(cfg_path, cfg)
        return True, f"Removed from {cfg_path}"

    def generate_config(self, py_path: str, srv_path: str) -> str:
        return json.dumps({
            "mcpServers": {
                "agent-memory": {
                    "command": py_path,
                    "args": [srv_path]
                }
            }
        }, indent=2)


INTEGRATIONS: List[ToolIntegration] = [
    ClaudeCodeIntegration(),
    CursorIntegration(),
    WindsurfIntegration(),
    CodexIntegration(),
    OpenCodeIntegration(),
    AntigravityIntegration(),
    AiderIntegration(),
    GooseIntegration(),
    ClineIntegration(),
    RooCodeIntegration(),
    CrushIntegration(),
    PiIntegration(),
]

INTEGRATION_MAP = {t.name: t for t in INTEGRATIONS}


def cmd_status(args: argparse.Namespace) -> None:
    scope = args.scope
    print(f"\nagent-memory Tool Integrations Status (scope: {scope})")
    print("=" * 78)
    print(f"{'Tool':<22} {'Detected':<10} {'Configured':<12} {'Rules':<10} {'Config Path'}")
    print("-" * 78)

    for tool in INTEGRATIONS:
        detected = "✓" if tool.is_detected() else "-"
        configured = "✓ Yes" if tool.is_configured(scope) else "✗ No"
        rules = "✓ Yes" if tool.are_rules_installed(scope) else ("n/a" if tool.get_rules_path(scope) is None else "✗ No")
        cfg_path = str(tool.get_config_path(scope))
        home_str = str(Path.home())
        if cfg_path.startswith(home_str):
            cfg_path = "~" + cfg_path[len(home_str):]
        print(f"{tool.display_name:<22} {detected:<10} {configured:<12} {rules:<10} {cfg_path}")

    print("-" * 78)
    print("Detected: CLI binary or config directory found on machine")
    print("Configured: agent-memory MCP server entry present in tool config")
    print("Rules: Memory discipline rules or skills injected\n")


def cmd_install(args: argparse.Namespace) -> None:
    py_path = args.python or detect_python()
    srv_path = args.server or detect_server()
    scope = args.scope
    targets = args.tools

    if "all" in targets:
        selected = [t for t in INTEGRATIONS if t.is_detected()]
        if not selected:
            print("No supported tools detected on host. Use explicit tool names to configure anyway.")
            return
    else:
        selected = []
        for name in targets:
            key = name.lower()
            if key not in INTEGRATION_MAP:
                print(f"Unknown tool: '{name}'. Available: {', '.join(INTEGRATION_MAP.keys())} or 'all'")
                return
            selected.append(INTEGRATION_MAP[key])

    print(f"Using Python: {py_path}")
    print(f"Using Server: {srv_path}")
    print(f"Target scope: {scope}\n")

    for tool in selected:
        success, msg = tool.install(py_path, srv_path, scope=scope)
        status_icon = "✓" if success else "✗"
        print(f"[{status_icon}] {tool.display_name:22}: {msg}")

    if not getattr(args, "skip_sync", False):
        setup_sync_interactive(
            non_interactive=getattr(args, "yes", False),
            auto_gh=getattr(args, "auto_gh", False)
        )


def setup_sync_interactive(non_interactive: bool = False, auto_gh: bool = False) -> None:
    """Detect GitHub CLI and setup seamless cross-device synchronization."""
    import sync
    import vault

    v_dir = vault.init_vault()
    vault.bootstrap_from_existing_claudemem()

    cfg = sync.load_sync_config()
    if cfg.get("remote_url"):
        print(f"\n[✓] Vault Sync: Connected to {cfg['remote_url']} (auto-sync enabled)\n")
        return

    # Check GitHub CLI
    gh_info = sync.check_gh()
    if gh_info["installed"] and gh_info["authenticated"]:
        user_str = f"@{gh_info['username']}" if gh_info['username'] else "authenticated user"
        print("\n" + "=" * 70)
        print("  Agent Memory Multi-Device Sync Setup")
        print("=" * 70)
        print(f"[✓] GitHub CLI (gh) detected: Logged in as {user_str}")
        print("Automatic Git Sync keeps your AI assistant's memories synchronized")
        print("across all your laptops and devices using a private GitHub repository.\n")

        if auto_gh:
            choice = "y"
        elif non_interactive or not sys.stdin.isatty():
            print("Non-interactive mode: initializing local vault (connect remote anytime via 'agent-integrate sync init').")
            sync.init_git_repo(v_dir)
            return
        else:
            try:
                ans = input("Create private GitHub repo 'agent-memory-vault' and enable automatic sync? [Y/n]: ").strip().lower()
                choice = ans if ans else "y"
            except (EOFError, KeyboardInterrupt):
                print()
                choice = "n"

        if choice in ("y", "yes"):
            print("Creating private GitHub repository 'agent-memory-vault'...")
            ok, msg = sync.setup_gh_repo(vault_dir=v_dir, repo_name="agent-memory-vault", private=True)
            if ok:
                print(f"[✓] {msg}")
                print("[✓] Automatic background sync enabled. All coding tools will stay in sync!\n")
            else:
                print(f"[!] {msg}")
                print("Vault initialized locally. You can connect a remote later via 'agent-integrate sync init <url>'.\n")
            return
        else:
            print("\nOptions for cross-device sync:")
            print("  1. Connect an existing Git remote URL")
            print("  2. Keep local-only for now")
            try:
                opt = input("Choice [1/2] (default: 2): ").strip()
            except (EOFError, KeyboardInterrupt):
                opt = "2"
            if opt == "1":
                try:
                    url = input("Enter Git remote URL: ").strip()
                except (EOFError, KeyboardInterrupt):
                    url = ""
                if url:
                    ok, msg = sync.setup_git_remote(url, vault_dir=v_dir)
                    print(f"[{'✓' if ok else '!'}] {msg}\n")
                    return
            print("Vault initialized locally with Git tracking. (Run 'agent-integrate sync init' anytime).\n")
            sync.init_git_repo(v_dir)
            return

    # gh not available or not logged in
    if non_interactive or not sys.stdin.isatty():
        sync.init_git_repo(v_dir)
        return

    print("\n" + "=" * 70)
    print("  Agent Memory Multi-Device Sync Setup")
    print("=" * 70)
    print("Cross-device sync allows your agents to share memory across multiple machines.")
    print("Options:")
    print("  1. Connect an existing Git remote URL (e.g. git@github.com:user/my-vault.git)")
    print("  2. Keep local-only for now")
    try:
        opt = input("Choice [1/2] (default: 2): ").strip()
    except (EOFError, KeyboardInterrupt):
        opt = "2"

    if opt == "1":
        try:
            url = input("Enter Git remote URL: ").strip()
        except (EOFError, KeyboardInterrupt):
            url = ""
        if url:
            ok, msg = sync.setup_git_remote(url, vault_dir=v_dir)
            print(f"[{'✓' if ok else '!'}] {msg}\n")
            return

    print("Vault initialized locally with Git tracking. (Run 'agent-integrate sync init' anytime).\n")
    sync.init_git_repo(v_dir)


def cmd_sync(args: argparse.Namespace) -> None:
    """Execute sync subcommands."""
    import sync
    import time
    import vault

    action = getattr(args, "action", "status") or "status"
    if action == "status":
        st = sync.sync_status()
        print(f"\nagent-memory Vault Status:")
        print(f"  Directory:    {st['vault_dir']}")
        print(f"  Git Repo:     {'✓ Yes' if st['is_git_repo'] else '✗ No'}")
        print(f"  Remote URL:   {st['remote_url'] or '(none)'}")
        print(f"  Auto-sync:    {'Enabled' if st['auto_sync'] else 'Disabled'}")
        print(f"  Sync Status:  {st['last_sync_status']}")
        if st["last_sync_epoch"]:
            t_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st["last_sync_epoch"]))
            print(f"  Last Synced:  {t_str}")
        print(f"  GitHub CLI:   {'✓ Authenticated (' + str(st['gh_username']) + ')' if st['gh_authenticated'] else ('Installed (Not logged in)' if st['gh_available'] else 'Not Installed')}\n")
    elif action == "now":
        print("Synchronizing agent-memory vault with remote Git repository...")
        res = sync.sync(push=True, pull=True)
        print(f"Sync status: {res['status']}")
        if res.get("dedupe") and res["dedupe"].get("observations_pruned", 0) > 0:
            print(f"Compaction: pruned {res['dedupe']['observations_pruned']} redundant observations.")
        print("Done.")
    elif action == "dedupe":
        print("Deduplicating and compacting memory vault...")
        d = vault.deduplicate_and_compact()
        print(f"Observations: {d['observations_before']} -> {d['observations_after']} ({d['observations_pruned']} pruned)")
        print(f"Graph items:  {d['graph_before']} -> {d['graph_after']} ({d['graph_pruned']} pruned)")
        sync.sync(push=True, pull=False)
        print("Done.")
    elif action == "init":
        if getattr(args, "create_private", False):
            ok, msg = sync.setup_gh_repo(repo_name=getattr(args, "repo_name", "agent-memory-vault"))
            print(f"[{'✓' if ok else '!'}] {msg}")
        elif getattr(args, "remote_url", None):
            ok, msg = sync.setup_git_remote(args.remote_url)
            print(f"[{'✓' if ok else '!'}] {msg}")
        else:
            setup_sync_interactive()


def cmd_uninstall(args: argparse.Namespace) -> None:
    scope = args.scope
    targets = args.tools

    if "all" in targets:
        selected = INTEGRATIONS
    else:
        selected = []
        for name in targets:
            key = name.lower()
            if key not in INTEGRATION_MAP:
                print(f"Unknown tool: '{name}'. Available: {', '.join(INTEGRATION_MAP.keys())} or 'all'")
                return
            selected.append(INTEGRATION_MAP[key])

    for tool in selected:
        if tool.is_configured(scope):
            _, msg = tool.uninstall(scope=scope)
            print(f"[✓] {tool.display_name:22}: {msg}")
        else:
            print(f"[-] {tool.display_name:22}: Not configured in {scope} scope")


def cmd_generate(args: argparse.Namespace) -> None:
    py_path = args.python or detect_python()
    srv_path = args.server or detect_server()
    name = args.tool.lower()

    if name not in INTEGRATION_MAP:
        print(f"Unknown tool: '{name}'. Available: {', '.join(INTEGRATION_MAP.keys())}")
        return

    tool = INTEGRATION_MAP[name]
    print(f"=== {tool.display_name} Configuration Snippet ===")
    print(tool.generate_config(py_path, srv_path))
    rules = tool.generate_rules()
    if rules:
        print(f"\n=== {tool.display_name} Rules Snippet ===")
        print(rules)


def cmd_test(args: argparse.Namespace) -> None:
    py_path = args.python or detect_python()
    srv_path = args.server or detect_server()

    print(f"Testing agent-memory MCP server over stdio:")
    print(f"  Command: {py_path} {srv_path}")

    try:
        proc = subprocess.Popen(
            [py_path, srv_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
    except Exception as e:
        print(f"  [✗] Failed to spawn MCP server process: {e}")
        return

    def send_rpc(req_obj: Dict[str, Any]) -> Dict[str, Any]:
        line = json.dumps(req_obj) + "\n"
        proc.stdin.write(line)
        proc.stdin.flush()
        resp_line = proc.stdout.readline()
        if not resp_line:
            raise RuntimeError(f"Server closed connection unexpectedly. Stderr: {proc.stderr.read()}")
        return json.loads(resp_line)

    try:
        # 1. Initialize
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-harness", "version": "1.0"}
            }
        }
        init_res = send_rpc(init_req)
        server_info = init_res.get("result", {}).get("serverInfo", {})
        print(f"  [✓] initialize: {server_info.get('name')} v{server_info.get('version')}")

        # 2. Ping
        ping_req = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
        ping_res = send_rpc(ping_req)
        assert ping_res.get("result") == {}, f"Unexpected ping result: {ping_res}"
        print(f"  [✓] ping: pong response received")

        # 3. List tools
        tools_req = {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}
        tools_res = send_rpc(tools_req)
        tools = [t.get("name") for t in tools_res.get("result", {}).get("tools", [])]
        expected_tools = ["memory_recall", "memory_recall_deep", "memory_record", "memory_promote", "memory_sync"]
        for exp in expected_tools:
            if exp in tools:
                print(f"  [✓] tool registered: {exp}")
            else:
                print(f"  [✗] tool missing: {exp}")

        all_ok = all(exp in tools for exp in expected_tools)
        if all_ok:
            print("\nAll MCP server handshake checks passed successfully!")
        else:
            print("\nSome tool checks failed.")

    except Exception as e:
        print(f"  [✗] MCP communication error: {e}")
    finally:
        proc.terminate()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-integrate",
        description="Turnkey integration tool for agent-memory across AI coding CLIs and IDEs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = subparsers.add_parser("status", help="Show status of detected tools and MCP wiring")
    p_status.add_argument("--scope", choices=["user", "project"], default="user", help="Check user or project config")

    # install
    p_install = subparsers.add_parser("install", help="Configure MCP server and rules for specified tools")
    p_install.add_argument("tools", nargs="+", help="Tool names (e.g. claude, cursor, codex, aider) or 'all'")
    p_install.add_argument("--scope", choices=["user", "project"], default="user", help="Install to user or project config")
    p_install.add_argument("--python", help="Override Python executable path")
    p_install.add_argument("--server", help="Override mcp_server.py path")
    p_install.add_argument("--yes", "-y", action="store_true", help="Non-interactive mode with default recommendations")
    p_install.add_argument("--auto-gh", action="store_true", help="Auto-create private GitHub repo if gh is available")
    p_install.add_argument("--skip-sync", action="store_true", help="Skip Git sync setup during install")

    # sync
    p_sync = subparsers.add_parser("sync", help="Manage multi-device Git sync and vault compaction")
    p_sync.add_argument("action", nargs="?", default="status", choices=["status", "now", "dedupe", "init"],
                        help="Action: 'status' (default), 'now' (pull & push), 'dedupe' (compact), 'init' (connect remote)")
    p_sync.add_argument("remote_url", nargs="?", default=None, help="Remote Git repository URL (for init)")
    p_sync.add_argument("--create-private", action="store_true", help="Auto-create private repo with gh (for init)")
    p_sync.add_argument("--repo-name", default="agent-memory-vault", help="Custom repo name for --create-private")

    # uninstall
    p_uninstall = subparsers.add_parser("uninstall", help="Remove MCP server and rules for specified tools")
    p_uninstall.add_argument("tools", nargs="+", help="Tool names or 'all'")
    p_uninstall.add_argument("--scope", choices=["user", "project"], default="user", help="Uninstall from user or project config")

    # test
    p_test = subparsers.add_parser("test", help="Test stdio MCP handshake with the server")
    p_test.add_argument("--python", help="Override Python executable path")
    p_test.add_argument("--server", help="Override mcp_server.py path")

    # generate
    p_gen = subparsers.add_parser("generate", help="Print configuration snippet for a tool")
    p_gen.add_argument("tool", help="Tool name (e.g. claude, cursor, codex, aider)")
    p_gen.add_argument("--python", help="Override Python executable path")
    p_gen.add_argument("--server", help="Override mcp_server.py path")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "install":
        cmd_install(args)
    elif args.command == "sync":
        cmd_sync(args)
    elif args.command == "uninstall":
        cmd_uninstall(args)
    elif args.command == "test":
        cmd_test(args)
    elif args.command == "generate":
        cmd_generate(args)


if __name__ == "__main__":
    main()
