"""Promote durable knowledge L1 -> L2. Reads claude-mem SQLite directly
(zero tokens, no worker needed), keeps only durable signals, dedupes via
state file. Pass any object with .add(text) as l2 (CogneeLayer or fake).
"""
import hashlib
import json
import sqlite3
from pathlib import Path

DB = Path.home() / ".claude-mem" / "claude-mem.db"
STATE = Path(__file__).parent / "promoted.json"
DURABLE_TYPES = {"decision", "bugfix", "feature"}
DURABLE_CONCEPTS = {"why-it-exists", "pattern", "gotcha", "trade-off", "how-it-works"}
import re as _re
NO_SIGNAL = _re.compile(
    r"^(none[\s,]*)+$|no (new |technical )?(patterns|learnings|work|changes)|"
    r"nothing (new|learned)|not (yet |currently )?(identified|performed|introduced)|"
    r"no work has been performed", _re.I)


def _signal(body: str) -> bool:
    return len(body) >= 60 and not NO_SIGNAL.search(body)


def _load_state() -> set:
    return set(json.loads(STATE.read_text())) if STATE.exists() else set()


def _save_state(seen: set) -> None:
    STATE.write_text(json.dumps(sorted(seen)))


def collect(project: str | None = None, since_epoch: int = 0) -> list[str]:
    """Distilled candidate texts: session learnings + durable observations."""
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


def promote(l2, project: str | None = None, since_epoch: int = 0) -> list[str]:
    seen = _load_state()
    fresh = [t for t in collect(project, since_epoch)
             if hashlib.sha1(t.encode()).hexdigest() not in seen]
    for text in fresh:
        l2.add(text)
        seen.add(hashlib.sha1(text.encode()).hexdigest())
    _save_state(seen)
    return fresh
