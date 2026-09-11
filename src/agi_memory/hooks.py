#!/usr/bin/env python3
"""Universal lifecycle hooks runner and installer for agent-memory.

Supported Lifecycle Events:
- session-start: Proactive memory context injection (pinned core blocks + top precedents)
- pre-compact:   Auto-promotion of L1 working memories into durable L2 graph before context compression
- session-end:   Instant background Git sync and compaction
- pre-commit:    Offline test suite and memory invariant validation
- post-commit:   Auto-records git commit message and diff insights into session memory

Supports:
- Claude Code (~/.claude/settings.json, .claude/settings.json)
- Antigravity CLI & IDE (~/.gemini/config/hooks.json, .agents/hooks.json)
- OpenAI Codex (.codex/, git hooks)
- Cursor (.cursor/, git hooks)
- Windsurf (.windsurfrules, git hooks)
- Aider (.aider.conf.yml, git hooks)
- Git (.git/hooks/pre-commit, post-commit, pre-push)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from agi_memory.config import DATA_DIR
except ImportError:
    from config import DATA_DIR

REPO_DIR = Path(__file__).resolve().parent
DEFAULT_HOOKS_DIR = DATA_DIR / "hooks"


def detect_python() -> str:
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


def detect_project(cwd: Path | None = None) -> str:
    """Detect current project name from environment, git root, or directory markers."""
    env_proj = os.getenv("AGENT_MEMORY_PROJECT") or os.getenv("PROJECT_NAME")
    if env_proj:
        return env_proj.strip()

    root = cwd or Path.cwd()
    # Check git root
    try:
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        if git_root:
            return Path(git_root).name
    except Exception:
        pass

    # Check config files
    for parent in [root] + list(root.parents):
        for marker in ["pyproject.toml", "package.json", "Cargo.toml", "pubspec.yaml", "go.mod"]:
            f = parent / marker
            if f.exists():
                try:
                    txt = f.read_text(encoding="utf-8")
                    m = re.search(r'name\s*=\s*["\']([^"\']+)["\']', txt)
                    if m:
                        return m.group(1).strip()
                except Exception:
                    pass
                return parent.name
        if (parent / ".git").exists():
            return parent.name

    return root.name or "global"


def ensure_hooks_dir() -> Path:
    DEFAULT_HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_HOOKS_DIR


# ============================================================================
# Hook Implementations
# ============================================================================

def hook_session_start(project: Optional[str] = None) -> None:
    """SessionStart / PreInvocation: Inject pinned blocks and top precedents into context."""
    proj = project or detect_project()
    sys.path.insert(0, str(REPO_DIR))

    pinned_blocks: List[Dict[str, Any]] = []
    recent_hits: List[str] = []

    try:
        from agi_memory.layers.session_layer import SessionLayer
    except ImportError:
        from layers.session_layer import SessionLayer
    try:
        l1 = SessionLayer(project=proj)
        pinned_blocks = l1.get_pinned_blocks(project=proj)
        hits = l1.search("architecture convention pattern decision rule invariant", limit=3)
        recent_hits = [h.text for h in hits]
    except Exception:
        pass

    if not pinned_blocks and not recent_hits:
        return

    output: List[str] = []
    output.append(f"<!-- AGENT_MEMORY_STARTUP_CONTEXT -->")
    output.append(f"# Agent Memory: Active Context & Precedents ({proj})")

    if pinned_blocks:
        output.append("\n## Pinned Core Memory (Active Invariants)")
        for b in pinned_blocks:
            k = b.get("block_key", "")
            cat = b.get("category", "system")
            c = b.get("content", "")
            output.append(f"- **[{k}]** ({cat}): {c}")

    if recent_hits:
        output.append("\n## Top Project Precedents")
        for h in recent_hits:
            output.append(f"- {h}")

    output.append("\n*Query `memory_recall` or `memory_recall_deep` for additional context.*")
    output.append(f"<!-- AGENT_MEMORY_STARTUP_CONTEXT_END -->")

    print("\n".join(output))


def hook_pre_compact(project: Optional[str] = None) -> None:
    """PreCompact: Curate high-signal working memory into L2 knowledge graph before context loss."""
    proj = project or detect_project()
    sys.path.insert(0, str(REPO_DIR))
    try:
        try:
            from agi_memory import promote
        except ImportError:
            import promote
        promoted = promote.auto_promote(limit=10, project=proj)
        if promoted:
            print(f"[agent-memory] PreCompact: Curated {len(promoted)} durable item(s) to knowledge graph.")
    except Exception:
        pass


def hook_session_end(project: Optional[str] = None) -> None:
    """SessionEnd / Stop: Commit vault and trigger background sync."""
    sys.path.insert(0, str(REPO_DIR))
    try:
        try:
            from agi_memory import sync
        except ImportError:
            import sync
        res = sync.sync(push=True, pull=True)
        if res.get("status") == "ok":
            print("[agent-memory] SessionEnd: Synced memory vault with remote.")
    except Exception:
        pass


def hook_pre_commit() -> None:
    """Git pre-commit: Verify test suite and offline invariants."""
    sys.path.insert(0, str(REPO_DIR))
    val_script = Path.cwd() / "hooks" / "validate-offline.sh"
    if not val_script.exists():
        val_script = REPO_DIR.parent.parent / "hooks" / "validate-offline.sh"
    if val_script.exists() and os.access(val_script, os.X_OK):
        ret = subprocess.call([str(val_script)])
        if ret != 0:
            sys.exit(ret)
        return

    # Fallback to tests/test_offline.py
    test_script = Path.cwd() / "tests" / "test_offline.py"
    if not test_script.exists():
        test_script = REPO_DIR.parent.parent / "tests" / "test_offline.py"
    if test_script.exists():
        py = detect_python()
        ret = subprocess.call([py, str(test_script)])
        if ret != 0:
            sys.exit(ret)


def hook_post_commit(project: Optional[str] = None) -> None:
    """Git post-commit: Record meaningful commit message into session memory."""
    proj = project or detect_project()
    sys.path.insert(0, str(REPO_DIR))

    try:
        log_out = subprocess.check_output(
            ["git", "log", "-1", "--pretty=format:%h%x1f%s%x1f%b"],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        if not log_out:
            return
        parts = log_out.split("\x1f")
        cid = parts[0]
        subject = parts[1] if len(parts) > 1 else ""
        body = parts[2].strip() if len(parts) > 2 else ""

        # Filter low-signal commits (e.g. merge, wip, bump)
        ignore_patterns = r"^(merge |wip|bump version|update changelog|temp)"
        if re.search(ignore_patterns, subject, re.I):
            return

        text = f"Commit {cid}: {subject}"
        if body:
            text += f"\n{body}"

        category = "decision"
        if re.search(r"\b(fix|bug|resolve|patch)\b", subject, re.I):
            category = "bugfix"
        elif re.search(r"\b(arch|refactor|design|layer)\b", subject, re.I):
            category = "architecture"
        elif re.search(r"\b(pattern|convention|rule)\b", subject, re.I):
            category = "pattern"

        try:
            from agi_memory.layers.session_layer import SessionLayer
        except ImportError:
            from layers.session_layer import SessionLayer
        l1 = SessionLayer(project=proj)
        l1.record(text=text, title=f"Git commit: {subject[:50]}", project=proj, category=category)
    except Exception:
        pass


# ============================================================================
# Hook Generation and Installation Helpers
# ============================================================================

def generate_shell_wrappers(hooks_dir: Path, py_path: str, repo_dir: Path) -> Dict[str, Path]:
    """Generate universal shell wrappers in ~/.agent-memory/hooks/."""
    hooks_dir.mkdir(parents=True, exist_ok=True)
    scripts = {
        "session-start": f"""#!/usr/bin/env bash
exec "{py_path}" "{repo_dir / 'hooks.py'}" session-start "$@"
""",
        "pre-compact": f"""#!/usr/bin/env bash
exec "{py_path}" "{repo_dir / 'hooks.py'}" pre-compact "$@"
""",
        "session-end": f"""#!/usr/bin/env bash
exec "{py_path}" "{repo_dir / 'hooks.py'}" session-end "$@"
""",
        "pre-commit": f"""#!/usr/bin/env bash
exec "{py_path}" "{repo_dir / 'hooks.py'}" pre-commit "$@"
""",
        "post-commit": f"""#!/usr/bin/env bash
exec "{py_path}" "{repo_dir / 'hooks.py'}" post-commit "$@"
""",
    }

    created = {}
    for name, content in scripts.items():
        p = hooks_dir / f"{name}.sh"
        p.write_text(content, encoding="utf-8")
        try:
            p.chmod(0o755)
        except Exception:
            pass
        created[name] = p

    return created


# ============================================================================
# Assistant-Specific Hook Integrations
# ============================================================================

def install_claude_hooks(scope: str = "user", py_path: str = None) -> Tuple[bool, str]:
    """Install SessionStart, PreCompact, and SessionEnd hooks for Claude Code."""
    py = py_path or detect_python()
    hooks_py = REPO_DIR / "hooks.py"
    settings_path = Path.home() / ".claude" / "settings.json" if scope == "user" else Path.cwd() / ".claude" / "settings.json"

    data: Dict[str, Any] = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    hooks = data.setdefault("hooks", {})

    cmd_start = f'"{py}" "{hooks_py}" session-start'
    cmd_compact = f'"{py}" "{hooks_py}" pre-compact'
    cmd_end = f'"{py}" "{hooks_py}" session-end'

    def _ensure_hook(event: str, cmd: str, matcher: Optional[str] = None):
        event_list = hooks.setdefault(event, [])
        for entry in event_list:
            for h in entry.get("hooks", []):
                if cmd in h.get("command", ""):
                    return
        new_entry: Dict[str, Any] = {
            "hooks": [
                {
                    "type": "command",
                    "command": cmd
                }
            ]
        }
        if matcher:
            new_entry["matcher"] = matcher
        event_list.append(new_entry)

    _ensure_hook("SessionStart", cmd_start, matcher="startup|resume|clear|compact")
    _ensure_hook("PreCompact", cmd_compact)
    _ensure_hook("SessionEnd", cmd_end)

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True, f"Installed Claude Code hooks in {settings_path}"


def uninstall_claude_hooks(scope: str = "user") -> Tuple[bool, str]:
    settings_path = Path.home() / ".claude" / "settings.json" if scope == "user" else Path.cwd() / ".claude" / "settings.json"
    if not settings_path.exists():
        return True, "No settings file found"
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return False, "Failed to parse settings.json"

    hooks = data.get("hooks", {})
    for event in list(hooks.keys()):
        cleaned = []
        for entry in hooks[event]:
            has_agent_mem = any("hooks.py" in h.get("command", "") or "agent-memory" in h.get("command", "") for h in entry.get("hooks", []))
            if not has_agent_mem:
                cleaned.append(entry)
        if cleaned:
            hooks[event] = cleaned
        else:
            del hooks[event]

    settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True, f"Uninstalled Claude Code hooks from {settings_path}"


def install_agy_hooks(scope: str = "user", py_path: str = None) -> Tuple[bool, str]:
    """Install PreInvocation and Stop hooks for Antigravity (agy)."""
    py = py_path or detect_python()
    hooks_py = REPO_DIR / "hooks.py"
    hooks_path = Path.home() / ".gemini" / "config" / "hooks.json" if scope == "user" else Path.cwd() / ".agents" / "hooks.json"

    data: Dict[str, Any] = {}
    if hooks_path.exists():
        try:
            data = json.loads(hooks_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    cmd_start = f'"{py}" "{hooks_py}" session-start'
    cmd_end = f'"{py}" "{hooks_py}" session-end'

    data["agent-memory"] = {
        "enabled": True,
        "PreInvocation": [
            {
                "type": "command",
                "command": cmd_start
            }
        ],
        "Stop": [
            {
                "type": "command",
                "command": cmd_end
            }
        ]
    }

    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    hooks_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True, f"Installed Antigravity hooks in {hooks_path}"


def uninstall_agy_hooks(scope: str = "user") -> Tuple[bool, str]:
    hooks_path = Path.home() / ".gemini" / "config" / "hooks.json" if scope == "user" else Path.cwd() / ".agents" / "hooks.json"
    if not hooks_path.exists():
        return True, "No hooks file found"
    try:
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
    except Exception:
        return False, "Failed to parse hooks.json"

    if "agent-memory" in data:
        del data["agent-memory"]
        hooks_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True, f"Uninstalled Antigravity hooks from {hooks_path}"


def install_git_hooks(target_dir: Path | None = None, py_path: str = None) -> Tuple[bool, str]:
    """Install pre-commit, post-commit, and pre-push hooks in .git/hooks/."""
    root = target_dir or Path.cwd()
    git_dir = root / ".git"
    if not git_dir.exists():
        return False, f"No .git repository found in {root}"

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    py = py_path or detect_python()
    hooks_py = REPO_DIR / "hooks.py"

    pre_commit_content = f"""#!/usr/bin/env bash
# agent-memory pre-commit hook
"{py}" "{hooks_py}" pre-commit
"""
    post_commit_content = f"""#!/usr/bin/env bash
# agent-memory post-commit hook
"{py}" "{hooks_py}" post-commit &
"""
    pre_push_content = f"""#!/usr/bin/env bash
# agent-memory pre-push hook
"{py}" "{hooks_py}" session-end &
"""

    def _write_hook(name: str, content: str):
        hp = hooks_dir / name
        if hp.exists():
            curr = hp.read_text(encoding="utf-8")
            if "agent-memory" in curr:
                return
            content = curr.rstrip() + "\n\n" + content
        hp.write_text(content, encoding="utf-8")
        try:
            hp.chmod(0o755)
        except Exception:
            pass

    _write_hook("pre-commit", pre_commit_content)
    _write_hook("post-commit", post_commit_content)
    _write_hook("pre-push", pre_push_content)

    return True, f"Installed Git hooks in {hooks_dir}"


def uninstall_git_hooks(target_dir: Path | None = None) -> Tuple[bool, str]:
    root = target_dir or Path.cwd()
    git_dir = root / ".git"
    if not git_dir.exists():
        return True, "No .git directory"

    hooks_dir = git_dir / "hooks"
    for name in ["pre-commit", "post-commit", "pre-push"]:
        hp = hooks_dir / name
        if hp.exists():
            try:
                lines = hp.read_text(encoding="utf-8").splitlines()
                filtered = [l for l in lines if "hooks.py" not in l and "agent-memory" not in l]
                has_meaningful_code = any(l.strip() and not l.startswith("#!") for l in filtered)
                if has_meaningful_code:
                    hp.write_text("\n".join(filtered) + "\n", encoding="utf-8")
                else:
                    hp.unlink()
            except Exception:
                pass
    return True, f"Uninstalled Git hooks from {hooks_dir}"


def install_all_hooks(scope: str = "user", py_path: str = None) -> Dict[str, Tuple[bool, str]]:
    """Install lifecycle hooks across all detected and supported assistants and git."""
    py = py_path or detect_python()
    ensure_hooks_dir()
    generate_shell_wrappers(DEFAULT_HOOKS_DIR, py, REPO_DIR)

    results: Dict[str, Tuple[bool, str]] = {}
    results["claude"] = install_claude_hooks(scope=scope, py_path=py)
    results["agy"] = install_agy_hooks(scope=scope, py_path=py)

    git_res = install_git_hooks(py_path=py)
    if git_res[0]:
        results["git"] = git_res

    return results


def uninstall_all_hooks(scope: str = "user") -> Dict[str, Tuple[bool, str]]:
    results: Dict[str, Tuple[bool, str]] = {}
    results["claude"] = uninstall_claude_hooks(scope=scope)
    results["agy"] = uninstall_agy_hooks(scope=scope)
    results["git"] = uninstall_git_hooks()
    return results


# ============================================================================
# Main Entry Point
# ============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agent-memory-hooks",
        description="Lifecycle hook dispatcher and installer for agent-memory."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    # Lifecycle event commands
    p_start = subparsers.add_parser("session-start", help="Inject active context and precedents")
    p_start.add_argument("--project", "-p", help="Project name override")

    p_compact = subparsers.add_parser("pre-compact", help="Promote high-signal L1 memories before compaction")
    p_compact.add_argument("--project", "-p", help="Project name override")

    p_end = subparsers.add_parser("session-end", help="Commit vault and trigger background Git sync")
    p_end.add_argument("--project", "-p", help="Project name override")

    subparsers.add_parser("pre-commit", help="Verify offline test suite before commit")
    
    p_post_commit = subparsers.add_parser("post-commit", help="Record commit summary to session memory")
    p_post_commit.add_argument("--project", "-p", help="Project name override")

    # Hook installation management
    p_install = subparsers.add_parser("install", help="Install lifecycle hooks for tools")
    p_install.add_argument("tools", nargs="*", default=["all"], help="Tool names (claude, agy, git, all)")
    p_install.add_argument("--scope", choices=["user", "project"], default="user", help="Scope: user or project")
    p_install.add_argument("--python", help="Override Python executable path")

    p_uninstall = subparsers.add_parser("uninstall", help="Uninstall lifecycle hooks for tools")
    p_uninstall.add_argument("tools", nargs="*", default=["all"], help="Tool names (claude, agy, git, all)")
    p_uninstall.add_argument("--scope", choices=["user", "project"], default="user", help="Scope: user or project")

    args = parser.parse_args()

    if args.action == "session-start":
        hook_session_start(getattr(args, "project", None))
    elif args.action == "pre-compact":
        hook_pre_compact(getattr(args, "project", None))
    elif args.action == "session-end":
        hook_session_end(getattr(args, "project", None))
    elif args.action == "pre-commit":
        hook_pre_commit()
    elif args.action == "post-commit":
        hook_post_commit(getattr(args, "project", None))
    elif args.action == "install":
        tools = [t.lower() for t in args.tools]
        if "all" in tools:
            res = install_all_hooks(scope=args.scope, py_path=args.python)
            for k, (ok, msg) in res.items():
                print(f"[{'✓' if ok else '✗'}] {k:10}: {msg}")
        else:
            for t in tools:
                if t in ("claude", "claude-code"):
                    ok, msg = install_claude_hooks(scope=args.scope, py_path=args.python)
                elif t in ("agy", "antigravity"):
                    ok, msg = install_agy_hooks(scope=args.scope, py_path=args.python)
                elif t == "git":
                    ok, msg = install_git_hooks(py_path=args.python)
                else:
                    ok, msg = False, f"Unknown hook tool: {t}"
                print(f"[{'✓' if ok else '✗'}] {t:10}: {msg}")
    elif args.action == "uninstall":
        tools = [t.lower() for t in args.tools]
        if "all" in tools:
            res = uninstall_all_hooks(scope=args.scope)
            for k, (ok, msg) in res.items():
                print(f"[{'✓' if ok else '✗'}] {k:10}: {msg}")
        else:
            for t in tools:
                if t in ("claude", "claude-code"):
                    ok, msg = uninstall_claude_hooks(scope=args.scope)
                elif t in ("agy", "antigravity"):
                    ok, msg = uninstall_agy_hooks(scope=args.scope)
                elif t == "git":
                    ok, msg = uninstall_git_hooks()
                else:
                    ok, msg = False, f"Unknown hook tool: {t}"
                print(f"[{'✓' if ok else '✗'}] {t:10}: {msg}")


if __name__ == "__main__":
    main()
