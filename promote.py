"""Promote durable knowledge L1 -> L2. Reads claude-mem SQLite directly
(zero tokens, no worker needed), keeps only durable signals, dedupes via
state file. Pass any object with .add(text) as l2 (GraphLayer or fake).
"""
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from layers.session_layer import get_default_db

DB = get_default_db()
def get_state_path() -> Path:
    env = os.environ.get("AGENT_MEMORY_STATE")
    if env:
        return Path(env)
    vault_state = Path.home() / ".agent-memory" / "vault" / "promoted.json"
    if vault_state.parent.exists():
        return vault_state
    return Path.home() / ".agent-memory" / "promoted.json"

STATE = get_state_path()
DURABLE_TYPES = {"decision", "bugfix", "feature"}
DURABLE_CONCEPTS = {"why-it-exists", "pattern", "gotcha", "trade-off", "how-it-works"}
import re as _re
NO_SIGNAL = _re.compile(
    r"^(none[\s,]*)+$|no (?:new |technical )*(patterns|learnings|work|changes)|"
    r"nothing (new|learned)|not (yet |currently )?(identified|performed|introduced)|"
    r"no work has been performed", _re.I)


def _signal(body: str) -> bool:
    return len(body) >= 60 and not NO_SIGNAL.search(body)


def _load_state() -> set:
    return set(json.loads(STATE.read_text())) if STATE.exists() else set()


def _save_state(seen: set) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(sorted(seen)))


def collect(project: str | None = None, since_epoch: int = 0) -> list[str]:
    """Distilled candidate texts: session learnings + durable observations."""
    if not DB.exists():
        return []
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    out: list[str] = []
    q = "SELECT project, learned, completed FROM session_summaries WHERE created_at_epoch > ?"
    args: list = [since_epoch]
    if project:
        q += " AND project = ?"
        args.append(project)
    for proj, learned, completed in con.execute(q, args).fetchall():
        body = " ".join(p for p in (learned, completed) if p and p != "None").strip()
        if _signal(body):
            out.append(f"[{proj}] session learning: {body}")
    q = ("SELECT project, title, facts, concepts FROM observations "
         "WHERE created_at_epoch > ? AND type IN ('decision','bugfix','feature')")
    args = [since_epoch]
    if project:
        q += " AND project = ?"
        args.append(project)
    for proj, title, facts, concepts in con.execute(q, args).fetchall():
        tags = set((concepts or "").split(","))
        if tags & DURABLE_CONCEPTS and facts:
            out.append(f"[{proj}] {title}: {facts}")
    con.close()
    return out


def promote(l2, project: str | None = None, since_epoch: int = 0,
            limit: int | None = None) -> list[str]:
    seen = _load_state()
    fresh = [t for t in collect(project, since_epoch)
             if hashlib.sha1(t.encode()).hexdigest() not in seen]
    if limit is not None:
        fresh = fresh[:limit]
    for text in fresh:
        l2.add(text)
        seen.add(hashlib.sha1(text.encode()).hexdigest())
    _save_state(seen)
    return fresh


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Promote durable knowledge from L1 to L2.")
    parser.add_argument("--project", "-p", default=None, help="Filter by project name")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Preview candidates without invoking L2 or modifying state")
    parser.add_argument("--limit", "-l", type=int, default=None,
                        help="Max items to promote/preview")
    args = parser.parse_args()

    seen = _load_state()
    candidates = collect(args.project)
    fresh = [t for t in candidates if hashlib.sha1(t.encode()).hexdigest() not in seen]
    if args.limit:
        fresh = fresh[:args.limit]

    print(f"Total candidates: {len(candidates)} | Fresh (unpromoted): {len(fresh)}")
    if args.dry_run:
        preview_count = min(len(fresh), 5)
        if preview_count:
            print(f"\n[Dry Run] Showing {preview_count} sample candidate(s):")
            for idx, item in enumerate(fresh[:preview_count], 1):
                print(f"  {idx}. {item[:140]}...")
        else:
            print("No fresh candidates found.")
    else:
        if not fresh:
            print("Nothing new to promote.")
        else:
            from layers.graph_layer import GraphLayer
            l2 = GraphLayer(project=args.project)
            promoted = promote(l2, project=args.project, limit=args.limit)
            print(f"Successfully promoted {len(promoted)} item(s) to native knowledge graph.")
