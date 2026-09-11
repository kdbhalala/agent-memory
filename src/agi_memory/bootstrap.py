"""Zero-touch cold-start memory seeder for agent-memory (stdlib only, zero dependencies).

Extracts high-signal architectural context, README invariants, and key git commit rationale
into L1 SessionLayer so developers and AI assistants start with working memory from moment zero.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional

try:
    from agi_memory.config import get_default_db
    from agi_memory.layers.session_layer import SessionLayer
except ImportError:
    try:
        from config import get_default_db
        from layers.session_layer import SessionLayer
    except ImportError:
        from .config import get_default_db
        from .layers.session_layer import SessionLayer


def detect_project_name(repo_path: Path) -> str:
    """Detect project name from package manifests, git remote, or folder name."""
    # 1. pyproject.toml
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
            if m:
                return m.group(1).strip()
        except Exception:
            pass

    # 2. package.json
    pkg = repo_path / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
            if isinstance(data, dict) and data.get("name"):
                return str(data["name"]).strip().split("/")[-1]
        except Exception:
            pass

    # 3. Cargo.toml
    cargo = repo_path / "Cargo.toml"
    if cargo.exists():
        try:
            content = cargo.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
            if m:
                return m.group(1).strip()
        except Exception:
            pass

    # 4. pubspec.yaml
    pubspec = repo_path / "pubspec.yaml"
    if pubspec.exists():
        try:
            content = pubspec.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'^\s*name\s*:\s*([a-zA-Z0-9_-]+)', content, re.MULTILINE)
            if m:
                return m.group(1).strip()
        except Exception:
            pass

    # 5. Git remote origin
    try:
        res = subprocess.run(["git", "remote", "get-url", "origin"],
                             cwd=repo_path, capture_output=True, text=True, timeout=3)
        if res.returncode == 0 and res.stdout.strip():
            raw = res.stdout.strip().rstrip("/")
            if raw.endswith(".git"):
                raw = raw[:-4]
            candidate = raw.split("/")[-1].split(":")[-1]
            if candidate:
                return candidate
    except Exception:
        pass

    # Fallback: folder name
    return repo_path.resolve().name


def extract_readme_context(repo_path: Path) -> dict | None:
    """Find and extract core architecture, purpose, and rules from README."""
    for name in ["README.md", "readme.md", "README", "README.rst"]:
        f = repo_path / name
        if f.exists():
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
                if not lines:
                    continue
                title_line = ""
                content_chunks = []
                for line in lines[:120]:
                    s = line.strip()
                    if not title_line and s.startswith("#"):
                        title_line = s.lstrip("#").strip()
                    elif s and not s.startswith("[!") and not s.startswith("<!--"):
                        content_chunks.append(s)
                summary = "\n".join(content_chunks[:35])
                if not title_line:
                    title_line = f"{repo_path.name} Overview"
                return {
                    "title": f"Architecture Overview: {title_line}",
                    "text": summary[:1500],
                    "category": "architecture"
                }
            except Exception:
                pass
    return None


def extract_git_commits(repo_path: Path, max_commits: int = 25) -> list[dict]:
    """Extract high-signal commits (feat, fix, refactor, perf, architecture) from git log."""
    try:
        cmd = [
            "git", "log", f"-n{max_commits * 2}",
            "--pretty=format:%H%x1f%an%x1f%ad%x1f%s%x1f%b%x1e",
            "--date=short"
        ]
        res = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=5)
        if res.returncode != 0 or not res.stdout:
            return []
    except Exception:
        return []

    raw_commits = res.stdout.split("\x1e")
    results = []
    for raw in raw_commits:
        parts = raw.strip().split("\x1f")
        if len(parts) < 4:
            continue
        commit_hash = parts[0].strip()
        author = parts[1].strip()
        date = parts[2].strip()
        subject = parts[3].strip()
        body = parts[4].strip() if len(parts) > 4 else ""

        if not subject:
            continue

        lower_subj = subject.lower()
        # Filter low-signal noise
        if lower_subj.startswith("merge "):
            continue
        if any(lower_subj.startswith(p) for p in ["wip", "chore(deps)", "bump version", "release v", "v0.", "v1."]):
            continue

        # Classify category
        category = "decision"
        if any(lower_subj.startswith(p) for p in ["fix:", "fix(", "bugfix:", "hotfix:"]):
            category = "bugfix"
        elif any(lower_subj.startswith(p) for p in ["feat:", "feat(", "feature:"]):
            category = "decision"
        elif any(lower_subj.startswith(p) for p in ["refactor:", "refactor(", "arch:", "architecture:"]):
            category = "architecture"
        elif any(lower_subj.startswith(p) for p in ["perf:", "perf("]):
            category = "pattern"
        elif "breaking" in lower_subj or "breaking change" in body.lower():
            category = "architecture"

        full_text = f"Git commit {commit_hash[:8]} on {date} by {author}:\n{subject}"
        if body:
            full_text += f"\n\n{body}"

        results.append({
            "hash": commit_hash[:8],
            "subject": subject,
            "title": subject[:80],
            "text": full_text[:1200],
            "category": category,
            "date": date,
            "author": author,
        })
        if len(results) >= max_commits:
            break
    return results


def bootstrap_project(repo_dir: str | Path = ".", max_commits: int = 20,
                      project: str | None = None,
                      db_path: Path | str | None = None) -> dict:
    """Bootstrap initial working memories from Git history and README.md.

    Idempotent: skips observations that are already present.
    """
    repo_path = Path(repo_dir).resolve()
    proj = project or detect_project_name(repo_path)
    l1 = SessionLayer(project=proj, db_path=db_path)

    created_ids = []
    readme_bootstrapped = False
    commits_bootstrapped = 0

    # Retrieve existing observation titles for idempotency
    existing = l1.list_observations(limit=150, project=proj)
    existing_titles = {obs["title"].lower() for obs in existing}

    # 1. Seed README architecture
    readme_info = extract_readme_context(repo_path)
    if readme_info:
        full_title = f"[{proj}] {readme_info['title']}"
        if full_title.lower() not in existing_titles:
            rec = l1.record(
                text=readme_info["text"],
                title=full_title,
                project=proj,
                category=readme_info["category"]
            )
            if rec.get("id"):
                created_ids.append(rec["id"])
                readme_bootstrapped = True
                existing_titles.add(full_title.lower())

    # 2. Seed High-signal Git Commits
    commits = extract_git_commits(repo_path, max_commits=max_commits)
    for c in commits:
        full_title = f"[{proj}] {c['title']}"
        if full_title.lower() in existing_titles or c["hash"] in str(existing_titles):
            continue
        rec = l1.record(
            text=c["text"],
            title=full_title,
            project=proj,
            category=c["category"]
        )
        if rec.get("id"):
            created_ids.append(rec["id"])
            commits_bootstrapped += 1
            existing_titles.add(full_title.lower())

    return {
        "project": proj,
        "repo_dir": str(repo_path),
        "created_count": len(created_ids),
        "ids": created_ids,
        "readme_bootstrapped": readme_bootstrapped,
        "commits_bootstrapped": commits_bootstrapped,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="agent-memory bootstrap",
        description="Bootstrap initial memories from Git history and README.md"
    )
    parser.add_argument("--repo", default=".", help="Target repository directory (default: .)")
    parser.add_argument("--project", default=None, help="Project name override")
    parser.add_argument("--max-commits", type=int, default=20, help="Max git commits to parse (default: 20)")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")

    args = parser.parse_args(argv)
    res = bootstrap_project(
        repo_dir=args.repo,
        max_commits=args.max_commits,
        project=args.project
    )

    if args.json:
        print(json.dumps(res, indent=2))
        return

    count = res["created_count"]
    proj = res["project"]
    if count == 0:
        print(f"[✓] Project '{proj}' already up-to-date (no new bootstrap memories needed).")
    else:
        parts = []
        if res["readme_bootstrapped"]:
            parts.append("1 README architecture")
        if res["commits_bootstrapped"]:
            parts.append(f"{res['commits_bootstrapped']} git commits")
        detail = f" ({', '.join(parts)})" if parts else ""
        print(f"[✓] Bootstrapped {count} memories for project '{proj}'{detail}.")


if __name__ == "__main__":
    main()
