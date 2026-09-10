"""Automatic Git synchronization engine for agent-memory vault.

Enables seamless multi-device, cross-agent memory synchronization via Git and GitHub.
Automatically creates private GitHub repositories using `gh` CLI with user permission.
Runs non-blocking background synchronization with periodic deduplication and compaction.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Optional, Tuple

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


from vault import (
    DATA_DIR,
    VAULT_DIR,
    deduplicate_and_compact,
    export_dirty_to_vault,
    get_vault_dir,
    import_from_vault,
    init_vault,
)

SYNC_CONFIG_FILE = DATA_DIR / "sync.json"
DEDUPE_INTERVAL_SECONDS = 7 * 24 * 3600  # 7 days
DEDUPE_COUNT_THRESHOLD = 50  # auto-dedupe after 50 new observations

_sync_lock = threading.Lock()
_debounce_timer: Optional[threading.Timer] = None


def load_sync_config() -> dict[str, Any]:
    """Load sync configuration from ~/.agent-memory/sync.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if SYNC_CONFIG_FILE.exists():
        try:
            return json.loads(SYNC_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "remote_url": None,
        "auto_sync": True,
        "last_sync_epoch": 0,
        "last_dedupe_epoch": 0,
        "last_sync_status": "unconfigured",
        "observations_since_dedupe": 0,
    }


def save_sync_config(cfg: dict[str, Any]) -> None:
    """Save sync configuration atomically."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SYNC_CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    tmp.replace(SYNC_CONFIG_FILE)


def check_git() -> bool:
    """Check if git CLI is available."""
    return shutil.which("git") is not None


def check_gh() -> dict[str, Any]:
    """Check if GitHub CLI (gh) is installed and authenticated."""
    gh_bin = shutil.which("gh")
    if not gh_bin:
        return {"installed": False, "authenticated": False, "username": None}

    try:
        proc = subprocess.run(
            [gh_bin, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=5
        )
        # gh auth status exits 0 when authenticated
        auth_ok = (proc.returncode == 0) or ("Logged in to" in proc.stdout or "Logged in to" in proc.stderr)
        username = None
        combined = proc.stdout + "\n" + proc.stderr
        for line in combined.splitlines():
            if "account" in line.lower() and ("logged in" in line.lower() or "active account" in line.lower()):
                parts = line.strip().split()
                for i, p in enumerate(parts):
                    if p.lower() in ("account", "as"):
                        if i + 1 < len(parts):
                            username = parts[i + 1].strip("()',")
                            break
                if username:
                    break

        if not username and auth_ok:
            try:
                u_proc = subprocess.run(
                    [gh_bin, "api", "user", "-q", ".login"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if u_proc.returncode == 0 and u_proc.stdout.strip():
                    username = u_proc.stdout.strip()
            except Exception:
                pass

        return {"installed": True, "authenticated": auth_ok, "username": username}
    except Exception:
        return {"installed": True, "authenticated": False, "username": None}


def _run_git(cmd: list[str], cwd: Path, timeout: int = 15) -> tuple[int, str, str]:
    """Helper to run git commands safely."""
    try:
        proc = subprocess.run(
            ["git"] + cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", "Git command timed out"
    except Exception as e:
        return 1, "", str(e)


def _ensure_git_identity(vault_dir: Path) -> None:
    """Ensure git user.name and user.email exist locally in vault."""
    rc, name, _ = _run_git(["config", "user.name"], cwd=vault_dir)
    if rc != 0 or not name:
        _run_git(["config", "user.name", "Agent Memory"], cwd=vault_dir)
    rc, email, _ = _run_git(["config", "user.email"], cwd=vault_dir)
    if rc != 0 or not email:
        _run_git(["config", "user.email", "agent-memory@local"], cwd=vault_dir)


def init_git_repo(vault_dir: Path | str | None = None) -> tuple[bool, str]:
    """Initialize a git repository in vault_dir if not already present."""
    v_dir = init_vault(vault_dir)
    git_dir = v_dir / ".git"
    if not git_dir.exists():
        rc, out, err = _run_git(["init", "-b", "main"], cwd=v_dir)
        if rc != 0:
            # Fallback for older git without -b flag
            rc, out, err = _run_git(["init"], cwd=v_dir)
            if rc != 0:
                return False, f"git init failed: {err}"
            _run_git(["branch", "-M", "main"], cwd=v_dir)

    _ensure_git_identity(v_dir)
    return True, "Git repository initialized."


def setup_gh_repo(
    vault_dir: Path | str | None = None,
    repo_name: str = "agent-memory-vault",
    private: bool = True
) -> tuple[bool, str]:
    """Create a private GitHub repo using `gh` CLI and set it as origin remote."""
    gh_info = check_gh()
    if not gh_info["installed"]:
        return False, "GitHub CLI (gh) is not installed."
    if not gh_info["authenticated"]:
        return False, "GitHub CLI (gh) is not authenticated. Run 'gh auth login' first."

    v_dir = init_vault(vault_dir)
    init_git_repo(v_dir)

    username = gh_info["username"]
    full_repo = f"{username}/{repo_name}" if username else repo_name

    # Check if repo already exists on GitHub
    check_rc = subprocess.run(["gh", "repo", "view", full_repo], capture_output=True, text=True)
    if check_rc.returncode == 0:
        # Repo already exists
        clone_url = f"https://github.com/{full_repo}.git"
    else:
        # Create repo
        cmd = ["gh", "repo", "create", repo_name, "--description", "Personal Agent Memory Vault (Multi-Device Sync)"]
        if private:
            cmd.append("--private")
        else:
            cmd.append("--public")

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            return False, f"Failed to create GitHub repo: {res.stderr.strip()}"
        clone_url = f"https://github.com/{full_repo}.git"

    # Set remote origin
    _run_git(["remote", "remove", "origin"], cwd=v_dir)
    rc, _, err = _run_git(["remote", "add", "origin", clone_url], cwd=v_dir)
    if rc != 0:
        return False, f"Failed to add git remote: {err}"

    # Export records to vault JSONL
    export_dirty_to_vault(vault_dir=v_dir)

    # Initial commit & push
    _run_git(["add", "-A"], cwd=v_dir)
    _run_git(["commit", "-m", "feat: initialize agent-memory vault"], cwd=v_dir)
    _run_git(["branch", "-M", "main"], cwd=v_dir)
    push_rc, _, push_err = _run_git(["push", "-u", "origin", "main"], cwd=v_dir, timeout=30)

    # Save sync config
    cfg = load_sync_config()
    cfg["remote_url"] = clone_url
    cfg["auto_sync"] = True
    cfg["last_sync_epoch"] = int(time.time())
    cfg["last_sync_status"] = "synced" if push_rc == 0 else "offline_buffered"
    save_sync_config(cfg)

    msg = f"Connected to {clone_url}."
    if push_rc != 0:
        msg += f" (Initial push pending/offline: {push_err})"
    return True, msg


def setup_git_remote(
    remote_url: str,
    vault_dir: Path | str | None = None
) -> tuple[bool, str]:
    """Connect vault to an existing custom git remote URL."""
    v_dir = init_vault(vault_dir)
    init_git_repo(v_dir)

    _run_git(["remote", "remove", "origin"], cwd=v_dir)
    rc, _, err = _run_git(["remote", "add", "origin", remote_url], cwd=v_dir)
    if rc != 0:
        return False, f"Failed to add git remote: {err}"

    export_dirty_to_vault(vault_dir=v_dir)
    _run_git(["add", "-A"], cwd=v_dir)
    _run_git(["commit", "-m", "feat: initialize agent-memory vault"], cwd=v_dir)
    _run_git(["branch", "-M", "main"], cwd=v_dir)
    push_rc, _, push_err = _run_git(["push", "-u", "origin", "main"], cwd=v_dir, timeout=30)

    cfg = load_sync_config()
    cfg["remote_url"] = remote_url
    cfg["auto_sync"] = True
    cfg["last_sync_epoch"] = int(time.time())
    cfg["last_sync_status"] = "synced" if push_rc == 0 else "offline_buffered"
    save_sync_config(cfg)

    msg = f"Connected to {remote_url}."
    if push_rc != 0:
        msg += f" (Initial push pending/offline: {push_err})"
    return True, msg


def sync(
    vault_dir: Path | str | None = None,
    push: bool = True,
    pull: bool = True,
    force_dedupe: bool = False
) -> dict[str, Any]:
    """Synchronize vault with git remote, executing periodic deduplication and local re-indexing."""
    with _sync_lock:
        v_dir = init_vault(vault_dir)
        git_dir = v_dir / ".git"
        cfg = load_sync_config()

        if not git_dir.exists():
            init_git_repo(v_dir)

        # Check git remote
        _, remotes, _ = _run_git(["remote", "-v"], cwd=v_dir)
        has_remote = "origin" in remotes

        now = int(time.time())
        time_since_dedupe = now - cfg.get("last_dedupe_epoch", 0)
        uncompressed_count = cfg.get("observations_since_dedupe", 0)

        dedupe_stats = None
        if force_dedupe or time_since_dedupe > DEDUPE_INTERVAL_SECONDS or uncompressed_count > DEDUPE_COUNT_THRESHOLD:
            dedupe_stats = deduplicate_and_compact(vault_dir=v_dir)
            cfg["last_dedupe_epoch"] = now
            cfg["observations_since_dedupe"] = 0

        # Export current SQLite states into vault JSONL
        exp = export_dirty_to_vault(vault_dir=v_dir)
        cfg["observations_since_dedupe"] = cfg.get("observations_since_dedupe", 0) + exp.get("observations", 0)

        # Commit local changes
        _ensure_git_identity(v_dir)
        _run_git(["add", "-A"], cwd=v_dir)
        _, status_out, _ = _run_git(["status", "--porcelain"], cwd=v_dir)

        committed = False
        if status_out:
            c_msg = "sync: update agent memory vault [auto]"
            if dedupe_stats and dedupe_stats.get("observations_pruned", 0) > 0:
                c_msg = f"chore: compact vault ({dedupe_stats['observations_pruned']} pruned) [auto]"
            rc, _, _ = _run_git(["commit", "-m", c_msg], cwd=v_dir)
            committed = (rc == 0)

        pulled = False
        pushed = False
        sync_status = "local_only"

        if has_remote:
            # 1. Pull changes with rebase
            if pull:
                rc_pull, _, err_pull = _run_git(["pull", "--rebase", "origin", "main"], cwd=v_dir, timeout=20)
                if rc_pull == 0:
                    pulled = True
                    # Re-import newly pulled records into local SQLite
                    import_from_vault(vault_dir=v_dir)
                else:
                    # If rebase conflict or offline, abort rebase cleanly
                    _run_git(["rebase", "--abort"], cwd=v_dir)
                    sync_status = "pull_offline"

            # 2. Push changes
            if push:
                rc_push, _, err_push = _run_git(["push", "origin", "main"], cwd=v_dir, timeout=20)
                if rc_push == 0:
                    pushed = True
                    sync_status = "synced"
                else:
                    sync_status = "push_offline"
        else:
            sync_status = "no_remote"

        cfg["last_sync_epoch"] = now
        cfg["last_sync_status"] = sync_status
        save_sync_config(cfg)

        return {
            "status": sync_status,
            "committed": committed,
            "pulled": pulled,
            "pushed": pushed,
            "exported": exp,
            "dedupe": dedupe_stats,
            "remote": cfg.get("remote_url"),
            "timestamp": now,
        }


def schedule_auto_sync(vault_dir: Path | str | None = None, delay_seconds: float = 3.0) -> None:
    """Schedule non-blocking debounced auto-sync in background thread."""
    global _debounce_timer

    def _worker():
        try:
            sync(vault_dir=vault_dir, push=True, pull=True)
        except Exception:
            pass

    if _debounce_timer and _debounce_timer.is_alive():
        _debounce_timer.cancel()

    _debounce_timer = threading.Timer(delay_seconds, _worker)
    _debounce_timer.daemon = True
    _debounce_timer.start()


def sync_status() -> dict[str, Any]:
    """Retrieve current synchronization status and diagnostics."""
    v_dir = get_vault_dir()
    cfg = load_sync_config()
    git_dir = v_dir / ".git"

    is_repo = git_dir.exists()
    remotes: list[str] = []
    if is_repo:
        _, remotes_str, _ = _run_git(["remote", "-v"], cwd=v_dir)
        remotes = [line.strip() for line in remotes_str.splitlines() if line.strip()]

    gh = check_gh()
    return {
        "vault_dir": str(v_dir),
        "is_git_repo": is_repo,
        "remote_url": cfg.get("remote_url"),
        "remotes": remotes,
        "auto_sync": cfg.get("auto_sync", True),
        "last_sync_epoch": cfg.get("last_sync_epoch", 0),
        "last_sync_status": cfg.get("last_sync_status", "unconfigured"),
        "last_dedupe_epoch": cfg.get("last_dedupe_epoch", 0),
        "gh_available": gh["installed"],
        "gh_authenticated": gh["authenticated"],
        "gh_username": gh["username"],
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="agent-memory Git Synchronization CLI")
    sub = parser.add_subparsers(dest="subcommand")

    sub.add_parser("status", help="Show synchronization and vault status")
    sub.add_parser("sync", help="Trigger immediate bidirectional sync")
    sub.add_parser("dedupe", help="Force immediate deduplication and compaction")

    init_p = sub.add_parser("init", help="Initialize Git sync with remote")
    init_p.add_argument("remote_url", nargs="?", default=None, help="Remote Git repository URL")
    init_p.add_argument("--create-private", action="store_true", help="Auto-create private repo with gh")
    init_p.add_argument("--repo-name", default="agent-memory-vault", help="Repo name for --create-private")

    args = parser.parse_args()

    if args.subcommand == "status" or not args.subcommand:
        st = sync_status()
        print(f"\nagent-memory Vault Status:")
        print(f"  Directory:    {st['vault_dir']}")
        print(f"  Git Repo:     {'✓ Yes' if st['is_git_repo'] else '✗ No'}")
        print(f"  Remote URL:   {st['remote_url'] or '(none)'}")
        print(f"  Auto-sync:    {'Enabled' if st['auto_sync'] else 'Disabled'}")
        print(f"  Sync Status:  {st['last_sync_status']}")
        if st["last_sync_epoch"]:
            t_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st["last_sync_epoch"]))
            print(f"  Last Synced:  {t_str}")
        print(f"  GitHub CLI:   {'✓ Authenticated (' + st['gh_username'] + ')' if st['gh_authenticated'] else ('Installed (Not logged in)' if st['gh_available'] else 'Not Installed')}\n")
    elif args.subcommand == "sync":
        print("Synchronizing agent-memory vault...")
        res = sync(push=True, pull=True)
        print(f"Status: {res['status']}")
        if res.get("dedupe"):
            print(f"Compacted: {res['dedupe']['observations_pruned']} observations pruned.")
        print("Done.")
    elif args.subcommand == "dedupe":
        print("Deduplicating and compacting vault...")
        d = deduplicate_and_compact()
        print(f"Observations: {d['observations_before']} -> {d['observations_after']} ({d['observations_pruned']} pruned)")
        print(f"Graph items:  {d['graph_before']} -> {d['graph_after']} ({d['graph_pruned']} pruned)")
        sync(push=True, pull=False)
        print("Done.")
    elif args.subcommand == "init":
        if args.create_private:
            ok, msg = setup_gh_repo(repo_name=args.repo_name)
            print(msg)
        elif args.remote_url:
            ok, msg = setup_git_remote(args.remote_url)
            print(msg)
        else:
            ok, msg = init_git_repo()
            print(msg)


if __name__ == "__main__":
    main()
