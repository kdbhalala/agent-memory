"""L1: claude-mem session memory via local worker HTTP (read-only).

Uses the same progressive-disclosure endpoint the opencode plugin uses:
index table first, full bodies only on demand. Falls back to direct
SQLite FTS read if the worker is down.
"""
import json
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

from .base import Hit, MemoryLayer

WORKER = "http://127.0.0.1:37777"
DB = Path.home() / ".claude-mem" / "claude-mem.db"


class ClaudeMemLayer(MemoryLayer):
    name = "claude-mem"

    def __init__(self, worker: str = WORKER, project: str | None = None):
        self.worker = worker
        self.project = project

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        try:
            return self._via_worker(query, limit)
        except Exception:
            return self._via_sqlite(query, limit)

    def _via_worker(self, query: str, limit: int) -> list[Hit]:
        q = urllib.parse.urlencode({"query": query, "limit": limit})
        with urllib.request.urlopen(f"{self.worker}/api/search/observations?{q}",
                                    timeout=15) as r:
            body = json.load(r)
        text = "".join(c.get("text", "") for c in body.get("content", []))
        return [Hit(text=text, source=self.name)] if text.strip() else []

    def _via_sqlite(self, query: str, limit: int) -> list[Hit]:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        sql = """SELECT id, title, substr(narrative, 1, 500) FROM observations_fts
                 JOIN observations ON observations.id = observations_fts.rowid
                 WHERE observations_fts MATCH ?"""
        args: list = [query]
        if self.project:
            sql += " AND project = ?"
            args.append(self.project)
        sql += " ORDER BY rank LIMIT ?"
        args.append(limit)
        rows = con.execute(sql, args).fetchall()
        con.close()
        return [Hit(text=f"#{i} {t}: {n}", source=self.name + ":sqlite", ref=str(i))
                for i, t, n in rows]
