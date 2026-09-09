"""L1: claude-mem session memory via local worker HTTP (read-only).

Two-step, token-efficient: worker returns a compact index table first,
then full bodies are fetched from local SQLite by ID. Falls back to
direct SQLite FTS if the worker is down.
"""
import json
import re
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path

from .base import Hit, MemoryLayer

WORKER = "http://127.0.0.1:37777"
DB = Path.home() / ".claude-mem" / "claude-mem.db"


STOPWORDS = frozenset(
    "what is the a an about does do for of to in on which who how when should "
    "be are was were and or with by from it its s t".split()
)


class ClaudeMemLayer(MemoryLayer):
    name = "claude-mem"

    def __init__(self, worker: str = WORKER, project: str | None = None):
        self.worker = worker
        self.project = project

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        # Plain reciprocal rank fusion over both rankers. Measured 9/10 on
        # eval_l1.py; deeper fetch / arm weights overfit that 10-question set.
        arms = [(self._safe_worker(query, limit), 1.0),
                (self._via_sqlite(query, limit), 1.0)]
        scores: dict[str, float] = {}
        by_ref: dict[str, Hit] = {}
        for hits, weight in arms:  # weighted reciprocal rank fusion
            for rank, h in enumerate(hits):
                if not h.ref:
                    continue
                scores[h.ref] = scores.get(h.ref, 0.0) + weight / (60 + rank)
                by_ref.setdefault(h.ref, h)
        ranked = sorted(scores, key=scores.__getitem__, reverse=True)[:limit]
        return [by_ref[r] for r in ranked]

    def _safe_worker(self, query: str, limit: int) -> list[Hit]:
        try:
            return self._via_worker(query, limit)
        except Exception:
            return []

    def _via_worker(self, query: str, limit: int) -> list[Hit]:
        params = {"query": query, "limit": limit}
        if self.project:
            params["project"] = self.project
        q = urllib.parse.urlencode(params)
        with urllib.request.urlopen(f"{self.worker}/api/search/observations?{q}",
                                    timeout=15) as r:
            body = json.load(r)
        index = "".join(c.get("text", "") for c in body.get("content", []))
        ids = re.findall(r"#(\d+)", index)
        if not ids:
            tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower())
                      if len(t) > 2 and t not in STOPWORDS]
            if tokens:
                params["query"] = " ".join(tokens[:5])
                q = urllib.parse.urlencode(params)
                with urllib.request.urlopen(f"{self.worker}/api/search/observations?{q}",
                                            timeout=15) as r:
                    body = json.load(r)
                index = "".join(c.get("text", "") for c in body.get("content", []))
                ids = re.findall(r"#(\d+)", index)
        if not ids:
            return []
        return self._bodies_by_id(ids)

    def _bodies_by_id(self, ids: list[str]) -> list[Hit]:
        if not ids:
            return []
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        ph = ",".join("?" for _ in ids)
        sql = ("SELECT id, project, title, facts, narrative FROM observations "
               f"WHERE id IN ({ph})")
        args: list = [int(i) for i in ids]
        if self.project:
            sql += " AND project = ?"
            args.append(self.project)
        rows = con.execute(sql, args).fetchall()
        con.close()
        by_id = {
            str(i): Hit(text=f"#{i} [{p}] {t}: {f} {n}", source=self.name, ref=str(i))
            for i, p, t, f, n in rows
        }
        return [by_id[str(i)] for i in ids if str(i) in by_id]

    def _via_sqlite(self, query: str, limit: int) -> list[Hit]:
        tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower())
                  if len(t) > 2 and t not in STOPWORDS] or re.findall(
                      r"[a-z0-9]+", query.lower())
        if not tokens:
            return []
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        sql = """SELECT observations.id FROM observations_fts
                 JOIN observations ON observations.id = observations_fts.rowid
                 WHERE observations_fts MATCH ?"""
        args: list = [" OR ".join(tokens)]
        if self.project:
            sql += " AND project = ?"
            args.append(self.project)
        sql += " ORDER BY rank LIMIT ?"
        args.append(limit)
        rows = con.execute(sql, args).fetchall()
        con.close()
        return self._bodies_by_id([str(i) for (i,) in rows])
