"""L1: Working session memory via SQLite FTS5 with optional worker HTTP fallback.

Two-step, token-efficient: queries local SQLite FTS5 index directly (<2ms)
or queries local worker HTTP if available. Self-bootstraps schema on first run.
"""
from __future__ import annotations

import json
import re
import sqlite3
import os
from pathlib import Path
from typing import Callable, Optional

from .base import Hit, MemoryLayer, open_db

try:
    from agi_memory.config import CLAUDE_MEM_DB, DEFAULT_DB, get_default_db
except ImportError:
    try:
        from ..config import CLAUDE_MEM_DB, DEFAULT_DB, get_default_db
    except (ImportError, ValueError):
        from config import CLAUDE_MEM_DB, DEFAULT_DB, get_default_db

DB = get_default_db()

OnRecordCallback = Callable[[dict], None]
_RECORD_LISTENERS: list[OnRecordCallback] = []


def add_record_listener(listener: OnRecordCallback) -> None:
    """Register a callback to be invoked when an observation is recorded."""
    if listener not in _RECORD_LISTENERS:
        _RECORD_LISTENERS.append(listener)


def remove_record_listener(listener: OnRecordCallback) -> None:
    """Unregister a previously registered record callback."""
    if listener in _RECORD_LISTENERS:
        _RECORD_LISTENERS.remove(listener)


STOPWORDS = frozenset(
    "what is the a an about does do for of to in on which who how when should "
    "be are was were and or with by from it its s t".split()
)


# FTS5 index schema version. Bump when the tokenizer changes so existing
# databases rebuild instead of silently serving results from the old index.
FTS_SCHEMA_VERSION = 2

# Porter stemming makes "authenticate" find "authentication" -- measured at ~0%
# recall without it. Older SQLite builds may not have it, so we degrade to the
# default tokenizer rather than failing to create the index at all.
_PREFERRED_TOKENIZE = "porter unicode61"
_FALLBACK_TOKENIZE = "unicode61"


def _supported_tokenizer(con: sqlite3.Connection) -> str:
    """Return the best FTS5 tokenizer this SQLite build actually supports."""
    try:
        con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _tok_probe "
                    f"USING fts5(x, tokenize='{_PREFERRED_TOKENIZE}')")
        con.execute("DROP TABLE IF EXISTS _tok_probe")
        return _PREFERRED_TOKENIZE
    except sqlite3.Error:
        return _FALLBACK_TOKENIZE


def _fts_needs_rebuild(con: sqlite3.Connection, tokenize: str) -> bool:
    """True when the stored index was built with a different tokenizer."""
    try:
        row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' "
                          "AND name='observations_fts'").fetchone()
    except sqlite3.Error:
        return False
    if not row or not row[0]:
        return False
    return f"tokenize='{tokenize}'" not in row[0]


class SessionLayer(MemoryLayer):
    name = "session"

    def __init__(self, worker: str | None = None, project: str | None = None,
                 db_path: Path | str | None = None,
                 on_record: OnRecordCallback | None = None):
        self.worker = worker
        self.project = project
        self.db_path = Path(db_path) if db_path else get_default_db()
        self.on_record = on_record
        self._migrate_fts_if_needed()


    def _migrate_fts_if_needed(self) -> None:
        """Upgrade an existing database's FTS index when the tokenizer changes.

        _init_db only ran for brand-new databases, so without this every
        existing user would keep querying an index built with the old matching
        rules and never see the improvement.
        """
        if not self.db_path.exists():
            return
        try:
            con = open_db(self.db_path)
            tokenize = _supported_tokenizer(con)
            if _fts_needs_rebuild(con, tokenize):
                con.execute("DROP TABLE IF EXISTS observations_fts")
                con.execute(f"""
                    CREATE VIRTUAL TABLE observations_fts USING fts5(
                        title, subtitle, facts, narrative, concepts,
                        content='observations', content_rowid='id',
                        tokenize='{tokenize}'
                    )
                """)
                con.execute("INSERT INTO observations_fts(observations_fts) VALUES('rebuild')")
                con.commit()
            con.close()
        except sqlite3.Error:
            # A corrupt or locked database must not break construction; reads
            # degrade to no hits, per the existing robustness invariant.
            pass

    @staticmethod
    def _init_db(db_path: Path) -> None:
        """Self-bootstrap local SQLite FTS5 schema if running standalone."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = open_db(db_path)
        con.execute("""
            CREATE TABLE IF NOT EXISTS observations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, memory_session_id TEXT, project TEXT,
                type TEXT, title TEXT, subtitle TEXT, facts TEXT, narrative TEXT,
                concepts TEXT, files_read TEXT, files_modified TEXT, prompt_number INT,
                discovery_tokens INT, created_at TEXT, created_at_epoch INT, content_hash TEXT,
                generated_by_model TEXT, relevance_count INT, sync_rev TEXT
            )
        """)
        tokenize = _supported_tokenizer(con)
        rebuilt = _fts_needs_rebuild(con, tokenize)
        if rebuilt:
            # Tokenizer changed since this database was created. The FTS table is
            # a derived index over `observations`, so dropping and rebuilding it
            # loses nothing -- and leaving it stale would silently serve results
            # from the old matching rules forever.
            con.execute("DROP TABLE IF EXISTS observations_fts")
        con.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts USING fts5(
                title, subtitle, facts, narrative, concepts,
                content='observations', content_rowid='id',
                tokenize='{tokenize}'
            )
        """)
        if rebuilt:
            # An external-content FTS table starts empty; repopulate from
            # `observations`, which is the real data.
            try:
                con.execute("INSERT INTO observations_fts(observations_fts) VALUES('rebuild')")
            except sqlite3.Error:
                pass
        con.execute("""
            CREATE TRIGGER IF NOT EXISTS observations_ai AFTER INSERT ON observations BEGIN
                INSERT INTO observations_fts(rowid, title, subtitle, facts, narrative, concepts)
                VALUES (new.id, new.title, new.subtitle, new.facts, new.narrative, new.concepts);
            END
        """)
        con.execute("""
            CREATE TRIGGER IF NOT EXISTS observations_ad AFTER DELETE ON observations BEGIN
                INSERT INTO observations_fts(observations_fts, rowid, title, subtitle, facts, narrative, concepts)
                VALUES ('delete', old.id, old.title, old.subtitle, old.facts, old.narrative, old.concepts);
            END
        """)
        con.execute("""
            CREATE TRIGGER IF NOT EXISTS observations_au AFTER UPDATE ON observations BEGIN
                INSERT INTO observations_fts(observations_fts, rowid, title, subtitle, facts, narrative, concepts)
                VALUES ('delete', old.id, old.title, old.subtitle, old.facts, old.narrative, old.concepts);
                INSERT INTO observations_fts(rowid, title, subtitle, facts, narrative, concepts)
                VALUES (new.id, new.title, new.subtitle, new.facts, new.narrative, new.concepts);
            END
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS core_memory_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_key TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'system',
                project TEXT DEFAULT 'global',
                pinned INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_core_blocks_pinned ON core_memory_blocks(pinned, project)
        """)
        con.commit()
        con.close()

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        """Search working memory using SQLite FTS5 with prefix wildcard fallback."""
        try:
            return self._via_sqlite(query, limit)
        except sqlite3.Error:
            # Unreadable DB (corrupt, truncated, or schema not yet created by a
            # peer layer sharing the file) degrades to "no hits", never a crash.
            return []

    def _bodies_by_id(self, ids: list[str]) -> list[Hit]:
        if not ids or not self.db_path.exists():
            return []
        con = open_db(self.db_path, readonly=True)
        ph = ",".join("?" for _ in ids)
        sql = ("SELECT id, project, title, facts, narrative, type FROM observations "
               f"WHERE id IN ({ph})")
        args: list = [int(i) for i in ids]
        if self.project in ("agi-memory", "agent-memory"):
            sql += " AND (project = 'agi-memory' OR project = 'agent-memory')"
        elif self.project:
            sql += " AND project = ?"
            args.append(self.project)
        rows = con.execute(sql, args).fetchall()
        con.close()
        by_id = {}
        for row in rows:
            i, p, t, f, n = row[0], row[1], row[2], row[3], row[4]
            typ = row[5] if len(row) > 5 else "decision"
            tag = "[SUPERSEDED] " if typ == "superseded" else ""
            by_id[str(i)] = Hit(text=f"#{i} {tag}[{p}] {t}: {f} {n}".replace("  ", " "),
                                source=self.name, ref=str(i))
        return [by_id[str(i)] for i in ids if str(i) in by_id]

    def _via_sqlite(self, query: str, limit: int) -> list[Hit]:
        if not self.db_path.exists():
            return []
        tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower())
                  if len(t) > 2 and t not in STOPWORDS] or re.findall(
                      r"[a-z0-9]+", query.lower())
        if not tokens:
            return []
        con = open_db(self.db_path, readonly=True)
        sql = """SELECT observations.id FROM observations_fts
                 JOIN observations ON observations.id = observations_fts.rowid
                 WHERE observations_fts MATCH ?"""
        args: list = [" OR ".join(tokens)]
        if self.project in ("agi-memory", "agent-memory"):
            sql += " AND (project = 'agi-memory' OR project = 'agent-memory')"
        elif self.project:
            sql += " AND project = ?"
            args.append(self.project)
        sql += " ORDER BY (CASE WHEN observations.type = 'superseded' THEN 1 ELSE 0 END) ASC, rank LIMIT ?"
        args.append(limit)
        rows = con.execute(sql, args).fetchall()

        # Fallback: prefix wildcard matching if standard query returned 0 rows
        if not rows and tokens:
            prefix_tokens = [f'"{t}"*' for t in tokens if len(t) >= 3]
            if prefix_tokens:
                sql_pfx = """SELECT observations.id FROM observations_fts
                             JOIN observations ON observations.id = observations_fts.rowid
                             WHERE observations_fts MATCH ?"""
                args_pfx = [" OR ".join(prefix_tokens)]
                if self.project in ("agi-memory", "agent-memory"):
                    sql_pfx += " AND (project = 'agi-memory' OR project = 'agent-memory')"
                elif self.project:
                    sql_pfx += " AND project = ?"
                    args_pfx.append(self.project)
                sql_pfx += " ORDER BY (CASE WHEN observations.type = 'superseded' THEN 1 ELSE 0 END) ASC, rank LIMIT ?"
                args_pfx.append(limit)
                rows = con.execute(sql_pfx, args_pfx).fetchall()

        con.close()
        return self._bodies_by_id([str(i) for (i,) in rows])

    def record(self, text: str, title: str | None = None,
               project: str | None = None, metadata: dict | None = None,
               category: str = "decision", supersedes: str | None = None) -> dict:
        """Record an observation/decision into L1 memory via direct SQLite FTS5 insertion."""
        proj = project or self.project or "global"
        tit = title or (text[:60].strip() + ("..." if len(text) > 60 else ""))
        cat = (category or "decision").strip().lower()

        # Direct SQLite insertion (self-bootstraps schema if needed)
        if not self.db_path.exists():
            self._init_db(self.db_path)
        else:
            try:
                con_trig = open_db(self.db_path)
                con_trig.execute("""
                    CREATE TRIGGER IF NOT EXISTS observations_ad AFTER DELETE ON observations BEGIN
                        INSERT INTO observations_fts(observations_fts, rowid, title, subtitle, facts, narrative, concepts)
                        VALUES ('delete', old.id, old.title, old.subtitle, old.facts, old.narrative, old.concepts);
                    END
                """)
                con_trig.execute("""
                    CREATE TRIGGER IF NOT EXISTS observations_au AFTER UPDATE ON observations BEGIN
                        INSERT INTO observations_fts(observations_fts, rowid, title, subtitle, facts, narrative, concepts)
                        VALUES ('delete', old.id, old.title, old.subtitle, old.facts, old.narrative, old.concepts);
                        INSERT INTO observations_fts(rowid, title, subtitle, facts, narrative, concepts)
                        VALUES (new.id, new.title, new.subtitle, new.facts, new.narrative, new.concepts);
                    END
                """)
                con_trig.commit()
                con_trig.close()
            except Exception:
                pass

        import hashlib
        import time
        import uuid

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        now_epoch = int(time.time() * 1000)
        session_id = str(uuid.uuid4())
        content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]

        con = open_db(self.db_path)
        cur = con.cursor()

        # 1. Conflict / Overlap Detection
        conflicts = []
        search_tokens = [t for t in re.findall(r"[a-z0-9]+", (tit + " " + text).lower())
                         if len(t) > 2 and t not in STOPWORDS]
        if search_tokens:
            try:
                sql_check = """
                    SELECT observations.id, observations.title, observations.facts, observations.narrative
                    FROM observations_fts
                    JOIN observations ON observations.id = observations_fts.rowid
                    WHERE observations_fts MATCH ? AND observations.type != 'superseded'
                """
                params_check = [" OR ".join(search_tokens[:5])]
                if proj and proj != "global":
                    sql_check += " AND observations.project = ?"
                    params_check.append(proj)
                sql_check += " ORDER BY rank LIMIT 3"
                rows_check = cur.execute(sql_check, params_check).fetchall()
                for r_id, r_tit, r_facts, r_narr in rows_check:
                    c_text = r_narr or r_facts or ""
                    conflicts.append({"id": r_id, "title": r_tit or "", "text": c_text[:120]})
            except Exception:
                pass

        # 2. Insert new observation
        cur.execute("""
            INSERT INTO observations (
                memory_session_id, project, type, title, subtitle,
                facts, narrative, concepts, files_read, files_modified,
                prompt_number, discovery_tokens, created_at, created_at_epoch,
                content_hash, generated_by_model, relevance_count, sync_rev
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id, proj, cat, tit, "Recorded via agent-memory",
            json.dumps([text]), text, json.dumps([cat, "pattern"]),
            "[]", "[]", 1, 0, now_iso, now_epoch, content_hash, "agent-memory", 0, "1"
        ))
        obs_id = cur.lastrowid

        # 3. Process supersedes if provided
        superseded_ids = []
        if supersedes:
            explicit_ids = [int(m) for m in re.findall(r"#?(\d+)", str(supersedes))]
            if explicit_ids:
                for eid in explicit_ids:
                    if eid != obs_id:
                        cur.execute("""
                            UPDATE observations
                            SET type = 'superseded',
                                subtitle = COALESCE(subtitle, '') || ' [SUPERSEDED by #' || ? || ']'
                            WHERE id = ?
                        """, (obs_id, eid))
                        if cur.rowcount > 0:
                            superseded_ids.append(eid)
            else:
                sup_tokens = [t for t in re.findall(r"[a-z0-9]+", str(supersedes).lower())
                              if len(t) > 2 and t not in STOPWORDS]
                if sup_tokens:
                    sql_sup = """
                        SELECT observations.id FROM observations_fts
                        JOIN observations ON observations.id = observations_fts.rowid
                        WHERE observations_fts MATCH ? AND observations.id != ?
                    """
                    p_sup = [" AND ".join(sup_tokens[:4]), obs_id]
                    if proj and proj != "global":
                        sql_sup += " AND observations.project = ?"
                        p_sup.append(proj)
                    sql_sup += " ORDER BY rank LIMIT 1"
                    found = cur.execute(sql_sup, p_sup).fetchall()
                    for (fid,) in found:
                        cur.execute("""
                            UPDATE observations
                            SET type = 'superseded',
                                subtitle = COALESCE(subtitle, '') || ' [SUPERSEDED by #' || ? || ']'
                            WHERE id = ?
                        """, (obs_id, fid))
                        if cur.rowcount > 0:
                            superseded_ids.append(fid)

        con.commit()
        con.close()

        obs_payload = {
            "id": obs_id,
            "memory_session_id": session_id,
            "project": proj,
            "type": cat,
            "title": tit,
            "subtitle": "Recorded via agent-memory",
            "facts": json.dumps([text]),
            "narrative": text,
            "concepts": json.dumps([cat, "pattern"]),
            "files_read": "[]",
            "files_modified": "[]",
            "prompt_number": 1,
            "discovery_tokens": 0,
            "created_at": now_iso,
            "created_at_epoch": now_epoch,
            "content_hash": content_hash,
            "generated_by_model": "agent-memory",
            "relevance_count": 0,
            "sync_rev": "1"
        }

        # Dispatch to instance callback and registered listeners
        if self.on_record:
            try:
                self.on_record(obs_payload)
            except Exception:
                pass
        for listener in _RECORD_LISTENERS:
            try:
                listener(obs_payload)
            except Exception:
                pass

        filtered_conflicts = [
            c for c in conflicts
            if c["id"] != obs_id and c["id"] not in superseded_ids
        ]

        return {
            "id": obs_id,
            "title": tit,
            "project": proj,
            "category": cat,
            "superseded_ids": superseded_ids,
            "conflicts": filtered_conflicts,
            "message": f"Memory saved directly to SQLite as observation #{obs_id}"
        }

    def add(self, text: str) -> None:
        self.record(text)

    @staticmethod
    def _ensure_core_table(con: sqlite3.Connection) -> None:
        con.execute("""
            CREATE TABLE IF NOT EXISTS core_memory_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                block_key TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'system',
                project TEXT DEFAULT 'global',
                pinned INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_core_blocks_pinned ON core_memory_blocks(pinned, project)
        """)

    def pin_block(self, key: str, content: str, category: str = "system", project: str | None = None) -> dict:
        """Pin a critical rule, invariant, or architectural constraint to core memory."""
        proj = project or self.project or "global"
        cat = (category or "system").strip()
        if not self.db_path.exists():
            self._init_db(self.db_path)
        con = open_db(self.db_path)
        self._ensure_core_table(con)
        con.execute("""
            INSERT INTO core_memory_blocks (block_key, content, category, project, pinned, updated_at)
            VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(block_key) DO UPDATE SET
                content = excluded.content,
                category = excluded.category,
                project = excluded.project,
                pinned = 1,
                updated_at = CURRENT_TIMESTAMP
        """, (key, content, cat, proj))
        con.commit()
        con.close()
        return {
            "key": key,
            "block_key": key,
            "content": content,
            "category": cat,
            "project": proj,
            "pinned": True,
        }

    def unpin_block(self, key: str) -> bool:
        """Unpin a block from core memory."""
        if not self.db_path.exists():
            return False
        con = open_db(self.db_path)
        self._ensure_core_table(con)
        cur = con.cursor()
        cur.execute("""
            UPDATE core_memory_blocks
            SET pinned = 0, updated_at = CURRENT_TIMESTAMP
            WHERE block_key = ?
        """, (key,))
        con.commit()
        updated = cur.rowcount > 0
        con.close()
        return updated

    def get_pinned_blocks(self, project: str | None = None) -> list[dict]:
        """Return all active pinned blocks (pinned = 1) where project = ? OR project = 'global' (or all if project is None)."""
        if not self.db_path.exists():
            return []
        con = open_db(self.db_path)
        self._ensure_core_table(con)
        if project:
            sql = ("SELECT id, block_key, content, category, project, pinned, created_at, updated_at "
                   "FROM core_memory_blocks WHERE pinned = 1 AND (project = ? OR project = 'global') "
                   "ORDER BY id ASC")
            rows = con.execute(sql, [project]).fetchall()
        else:
            sql = ("SELECT id, block_key, content, category, project, pinned, created_at, updated_at "
                   "FROM core_memory_blocks WHERE pinned = 1 ORDER BY id ASC")
            rows = con.execute(sql).fetchall()
        con.close()
        return [
            {
                "id": r[0],
                "key": r[1],
                "block_key": r[1],
                "content": r[2],
                "category": r[3],
                "project": r[4],
                "pinned": bool(r[5]),
                "created_at": r[6],
                "updated_at": r[7],
            }
            for r in rows
        ]

    def list_blocks(self, project: str | None = None) -> list[dict]:
        """Return all blocks."""
        if not self.db_path.exists():
            return []
        con = open_db(self.db_path)
        self._ensure_core_table(con)
        if project:
            sql = ("SELECT id, block_key, content, category, project, pinned, created_at, updated_at "
                   "FROM core_memory_blocks WHERE project = ? OR project = 'global' ORDER BY id ASC")
            rows = con.execute(sql, [project]).fetchall()
        else:
            sql = ("SELECT id, block_key, content, category, project, pinned, created_at, updated_at "
                   "FROM core_memory_blocks ORDER BY id ASC")
            rows = con.execute(sql).fetchall()
        con.close()
        return [
            {
                "id": r[0],
                "key": r[1],
                "block_key": r[1],
                "content": r[2],
                "category": r[3],
                "project": r[4],
                "pinned": bool(r[5]),
                "created_at": r[6],
                "updated_at": r[7],
            }
            for r in rows
        ]

    def get_observation(self, obs_id: int) -> dict | None:
        """Fetch a single observation by ID, returning a structured dictionary."""
        if not self.db_path.exists():
            return None
        con = open_db(self.db_path)
        cur = con.cursor()
        try:
            row = cur.execute("""
                SELECT id, memory_session_id, project, type, title, subtitle,
                       facts, narrative, concepts, files_read, files_modified,
                       created_at, created_at_epoch, content_hash
                FROM observations WHERE id = ?
            """, (obs_id,)).fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "memory_session_id": row[1],
                "project": row[2],
                "type": row[3],
                "title": row[4],
                "subtitle": row[5],
                "facts": json.loads(row[6]) if row[6] and row[6].startswith("[") else [row[6]] if row[6] else [],
                "narrative": row[7],
                "concepts": json.loads(row[8]) if row[8] and row[8].startswith("[") else [] if row[8] else [],
                "files_read": json.loads(row[9]) if row[9] and row[9].startswith("[") else [],
                "files_modified": json.loads(row[10]) if row[10] and row[10].startswith("[") else [],
                "created_at": row[11],
                "created_at_epoch": row[12],
                "content_hash": row[13],
            }
        finally:
            con.close()

    def delete_observation(self, obs_id: int, hard: bool = False) -> bool:
        """Delete an observation by ID. Soft delete (marks superseded) by default, or hard delete."""
        if not self.db_path.exists():
            return False
        con = open_db(self.db_path)
        cur = con.cursor()
        try:
            if hard:
                cur.execute("DELETE FROM observations WHERE id = ?", (obs_id,))
            else:
                cur.execute("""
                    UPDATE observations
                    SET type = 'superseded',
                        subtitle = COALESCE(subtitle, '') || ' [DELETED]'
                    WHERE id = ? AND type != 'superseded'
                """, (obs_id,))
            con.commit()
            return cur.rowcount > 0
        finally:
            con.close()

    def list_observations(self, limit: int = 20, project: str | None = None,
                          include_superseded: bool = False) -> list[dict]:
        """List recent observations ordered by id DESC."""
        if not self.db_path.exists():
            return []
        con = open_db(self.db_path)
        cur = con.cursor()
        try:
            sql = "SELECT id, project, type, title, subtitle, narrative, created_at FROM observations"
            conditions = []
            params: list[object] = []
            if not include_superseded:
                conditions.append("type != 'superseded'")
            if project and project != "global":
                conditions.append("project = ?")
                params.append(project)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(limit)
            rows = cur.execute(sql, params).fetchall()
            return [{
                "id": r[0],
                "project": r[1],
                "type": r[2],
                "title": r[3],
                "subtitle": r[4],
                "narrative": r[5],
                "created_at": r[6],
            } for r in rows]
        finally:
            con.close()


# Backward compatibility alias
ClaudeMemLayer = SessionLayer

