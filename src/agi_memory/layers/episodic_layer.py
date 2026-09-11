"""L3: Native SQLite Episodic Session Memory Layer (zero external dependencies).

Replaces heavy external background daemons (claude-mem) with a lightweight,
zero-overhead SQLite episodic store for tracking agent session lifecycles,
timelines, touched files, commit deltas, and cross-session recaps.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from agi_memory.config import DEFAULT_DB, get_default_db
    from agi_memory.layers.base import Hit, MemoryLayer
except ImportError:
    try:
        from ..config import DEFAULT_DB, get_default_db
        from .base import Hit, MemoryLayer
    except (ImportError, ValueError):
        from config import DEFAULT_DB, get_default_db
        from layers.base import Hit, MemoryLayer


def _detect_git_info(cwd: Path | str | None = None) -> Tuple[Optional[str], Optional[str]]:
    """Detect current git branch and commit HEAD hash."""
    root = Path(cwd) if cwd else Path.cwd()
    branch, head = None, None
    try:
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2
        ).strip()
    except Exception:
        pass

    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2
        ).strip()
    except Exception:
        pass

    return branch, head


def _detect_git_touched_files(cwd: Path | str | None = None) -> List[str]:
    """Detect uncommitted or modified files in current git working directory."""
    root = Path(cwd) if cwd else Path.cwd()
    files: List[str] = []
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2
        ).strip()
        for line in out.splitlines():
            line = line.strip()
            if len(line) >= 3:
                # format: XY path or XY "path"
                p = line[2:].strip().strip('"')
                if p and p not in files:
                    files.append(p)
    except Exception:
        pass
    return files


class EpisodicLayer(MemoryLayer):
    """Native SQLite Episodic Memory layer for session timeline and history."""
    name = "episodic"

    def __init__(self, db_path: Path | str | None = None, project: str | None = None):
        self.db_path = Path(db_path) if db_path else get_default_db()
        self.project = project
        self._init_db()

    def _get_con(self, mode: str = "rw") -> sqlite3.Connection:
        if mode == "ro":
            return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        """Initialize SQLite episodic tables and indexes."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = self._get_con(mode="rw")
        cur = con.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS episodic_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT UNIQUE NOT NULL,
                project TEXT NOT NULL,
                goal TEXT,
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                ended_at TEXT,
                duration_seconds REAL DEFAULT 0.0,
                git_branch TEXT,
                git_head_before TEXT,
                git_head_after TEXT,
                summary TEXT,
                touched_files TEXT DEFAULT '[]',
                commits TEXT DEFAULT '[]',
                status TEXT DEFAULT 'active'
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_episodic_project_time
            ON episodic_sessions(project, started_at DESC)
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS episodic_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                project TEXT NOT NULL,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                details TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_episodic_events_sess
            ON episodic_events(session_id, timestamp)
        """)

        con.commit()
        con.close()

    def start_session(
        self,
        session_id: Optional[str] = None,
        project: Optional[str] = None,
        goal: str = "",
        branch: Optional[str] = None,
        head: Optional[str] = None,
        cwd: Path | str | None = None
    ) -> Dict[str, Any]:
        """Start or register an active episodic session."""
        proj = project or self.project or "global"
        now_epoch = int(time.time())
        sid = session_id or f"sess_{now_epoch}_{os.urandom(3).hex()}"

        g_branch, g_head = _detect_git_info(cwd)
        b = branch or g_branch
        h = head or g_head

        con = self._get_con()
        cur = con.cursor()
        cur.execute("""
            INSERT INTO episodic_sessions (
                session_id, project, goal, git_branch, git_head_before, git_head_after, status
            ) VALUES (?, ?, ?, ?, ?, ?, 'active')
            ON CONFLICT(session_id) DO UPDATE SET
                goal = CASE WHEN excluded.goal != '' THEN excluded.goal ELSE goal END,
                git_branch = coalesce(excluded.git_branch, git_branch),
                git_head_after = coalesce(excluded.git_head_after, git_head_after)
        """, (sid, proj, goal, b, h, h))
        con.commit()

        cur.execute("SELECT id, session_id, project, goal, started_at, git_branch, git_head_before, status FROM episodic_sessions WHERE session_id = ?", (sid,))
        row = cur.fetchone()
        con.close()

        return {
            "id": row[0],
            "session_id": row[1],
            "project": row[2],
            "goal": row[3],
            "started_at": row[4],
            "git_branch": row[5],
            "git_head": row[6],
            "status": row[7],
        }

    def end_session(
        self,
        session_id: Optional[str] = None,
        summary: str = "",
        touched_files: Optional[List[str]] = None,
        commits: Optional[List[str]] = None,
        project: Optional[str] = None,
        cwd: Path | str | None = None
    ) -> Optional[Dict[str, Any]]:
        """Mark session as ended, compute duration, and record touched files."""
        proj = project or self.project or "global"
        con = self._get_con()
        cur = con.cursor()

        sid = session_id
        if not sid:
            # Find latest active session for this project
            cur.execute("""
                SELECT session_id FROM episodic_sessions
                WHERE project = ? AND status = 'active'
                ORDER BY started_at DESC LIMIT 1
            """, (proj,))
            row = cur.fetchone()
            if row:
                sid = row[0]
            else:
                # Find the most recent session regardless of status
                cur.execute("""
                    SELECT session_id FROM episodic_sessions
                    WHERE project = ? ORDER BY started_at DESC LIMIT 1
                """, (proj,))
                row2 = cur.fetchone()
                if row2:
                    sid = row2[0]

        if not sid:
            con.close()
            return None

        # Fetch current session start timestamp
        cur.execute("SELECT started_at, touched_files, commits, goal FROM episodic_sessions WHERE session_id = ?", (sid,))
        sess_row = cur.fetchone()
        if not sess_row:
            con.close()
            return None

        started_str, existing_files_raw, existing_commits_raw, existing_goal = sess_row

        existing_files = set(json.loads(existing_files_raw or "[]"))
        if touched_files:
            existing_files.update(touched_files)
        # Also auto-detect any files from git status
        auto_files = _detect_git_touched_files(cwd)
        existing_files.update(auto_files)

        existing_commits = list(json.loads(existing_commits_raw or "[]"))
        if commits:
            for c in commits:
                if c not in existing_commits:
                    existing_commits.append(c)

        _, cur_head = _detect_git_info(cwd)

        # Compute duration seconds via SQLite datetime difference
        cur.execute("""
            UPDATE episodic_sessions
            SET ended_at = CURRENT_TIMESTAMP,
                duration_seconds = max(1.0, ROUND((julianday(CURRENT_TIMESTAMP) - julianday(started_at)) * 86400.0, 1)),
                summary = CASE WHEN ? != '' THEN ? ELSE summary END,
                touched_files = ?,
                commits = ?,
                git_head_after = coalesce(?, git_head_after),
                status = 'completed'
            WHERE session_id = ?
        """, (summary, summary, json.dumps(sorted(list(existing_files))), json.dumps(existing_commits), cur_head, sid))
        con.commit()

        cur.execute("""
            SELECT id, session_id, project, goal, started_at, ended_at, duration_seconds,
                   git_branch, git_head_before, git_head_after, summary, touched_files, commits, status
            FROM episodic_sessions WHERE session_id = ?
        """, (sid,))
        final_row = cur.fetchone()
        con.close()

        if not final_row:
            return None

        return {
            "id": final_row[0],
            "session_id": final_row[1],
            "project": final_row[2],
            "goal": final_row[3],
            "started_at": final_row[4],
            "ended_at": final_row[5],
            "duration_seconds": final_row[6],
            "git_branch": final_row[7],
            "git_head_before": final_row[8],
            "git_head_after": final_row[9],
            "summary": final_row[10],
            "touched_files": json.loads(final_row[11] or "[]"),
            "commits": json.loads(final_row[12] or "[]"),
            "status": final_row[13],
        }

    def record_event(
        self,
        session_id: str,
        event_type: str,
        summary: str,
        details: Any = None,
        project: Optional[str] = None
    ) -> Dict[str, Any]:
        """Record an event during a session (e.g. edit, commit, checkpoint, decision)."""
        proj = project or self.project or "global"
        det_str = json.dumps(details) if isinstance(details, (dict, list)) else (str(details) if details else None)

        con = self._get_con()
        cur = con.cursor()

        cur.execute("""
            INSERT INTO episodic_events (session_id, project, event_type, summary, details)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, proj, event_type, summary, det_str))
        event_id = cur.lastrowid

        # Update touched files or commits on session if applicable
        if event_type == "commit":
            chash = None
            if isinstance(details, dict) and details.get("hash"):
                chash = str(details["hash"]).strip()
            elif summary:
                m = re.search(r"\b([0-9a-fA-F]{7,40})\b", summary)
                if m:
                    chash = m.group(1)
            if chash:
                cur.execute("SELECT commits FROM episodic_sessions WHERE session_id = ?", (session_id,))
                c_row = cur.fetchone()
                if c_row:
                    commits = json.loads(c_row[0] or "[]")
                    if chash not in commits:
                        commits.append(chash)
                        cur.execute("UPDATE episodic_sessions SET commits = ? WHERE session_id = ?", (json.dumps(commits), session_id))

        if event_type in ("edit", "file_edit", "write") and details:
            target_path = str(details).strip()
            if target_path and not target_path.startswith("{"):
                cur.execute("SELECT touched_files FROM episodic_sessions WHERE session_id = ?", (session_id,))
                f_row = cur.fetchone()
                if f_row:
                    files = json.loads(f_row[0] or "[]")
                    if target_path not in files:
                        files.append(target_path)
                        cur.execute("UPDATE episodic_sessions SET touched_files = ? WHERE session_id = ?", (json.dumps(files), session_id))

        con.commit()
        con.close()

        return {
            "id": event_id,
            "session_id": session_id,
            "project": proj,
            "event_type": event_type,
            "summary": summary,
            "details": det_str
        }

    def get_timeline(self, project: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve chronological timeline of past sessions."""
        proj = project or self.project
        con = self._get_con(mode="ro")
        cur = con.cursor()

        if proj:
            cur.execute("""
                SELECT id, session_id, project, goal, started_at, ended_at, duration_seconds,
                       git_branch, git_head_before, git_head_after, summary, touched_files, commits, status
                FROM episodic_sessions
                WHERE project = ?
                ORDER BY started_at DESC
                LIMIT ?
            """, (proj, limit))
        else:
            cur.execute("""
                SELECT id, session_id, project, goal, started_at, ended_at, duration_seconds,
                       git_branch, git_head_before, git_head_after, summary, touched_files, commits, status
                FROM episodic_sessions
                ORDER BY started_at DESC
                LIMIT ?
            """, (limit,))

        rows = cur.fetchall()
        con.close()

        results = []
        for r in rows:
            results.append({
                "id": r[0],
                "session_id": r[1],
                "project": r[2],
                "goal": r[3] or "",
                "started_at": r[4],
                "ended_at": r[5],
                "duration_seconds": r[6] or 0.0,
                "git_branch": r[7] or "",
                "git_head_before": r[8] or "",
                "git_head_after": r[9] or "",
                "summary": r[10] or "",
                "touched_files": json.loads(r[11] or "[]"),
                "commits": json.loads(r[12] or "[]"),
                "status": r[13],
            })
        return results

    def get_last_session(self, project: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve the most recent session for this project."""
        timeline = self.get_timeline(project=project, limit=1)
        return timeline[0] if timeline else None

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve full details of a specific session including events."""
        con = self._get_con(mode="ro")
        cur = con.cursor()
        cur.execute("""
            SELECT id, session_id, project, goal, started_at, ended_at, duration_seconds,
                   git_branch, git_head_before, git_head_after, summary, touched_files, commits, status
            FROM episodic_sessions WHERE session_id = ?
        """, (session_id,))
        row = cur.fetchone()
        if not row:
            con.close()
            return None

        cur.execute("""
            SELECT id, event_type, summary, details, timestamp
            FROM episodic_events
            WHERE session_id = ?
            ORDER BY timestamp ASC
        """, (session_id,))
        event_rows = cur.fetchall()
        con.close()

        events = []
        for er in event_rows:
            events.append({
                "id": er[0],
                "event_type": er[1],
                "summary": er[2],
                "details": er[3],
                "timestamp": er[4]
            })

        return {
            "id": row[0],
            "session_id": row[1],
            "project": row[2],
            "goal": row[3] or "",
            "started_at": row[4],
            "ended_at": row[5],
            "duration_seconds": row[6] or 0.0,
            "git_branch": row[7] or "",
            "git_head_before": row[8] or "",
            "git_head_after": row[9] or "",
            "summary": row[10] or "",
            "touched_files": json.loads(row[11] or "[]"),
            "commits": json.loads(row[12] or "[]"),
            "status": row[13],
            "events": events
        }

    def search(self, query: str, limit: int = 5) -> List[Hit]:
        """Search past session summaries and goals."""
        con = self._get_con(mode="ro")
        cur = con.cursor()
        like_term = f"%{query}%"

        args: list = [like_term, like_term]
        sql = """
            SELECT session_id, project, goal, summary, started_at
            FROM episodic_sessions
            WHERE (goal LIKE ? OR summary LIKE ?)
        """
        if self.project:
            sql += " AND project = ?"
            args.append(self.project)
        sql += " ORDER BY started_at DESC LIMIT ?"
        args.append(limit)

        cur.execute(sql, args)
        rows = cur.fetchall()
        con.close()

        hits = []
        for r in rows:
            sid, proj, goal, summary, started = r
            txt = f"[{proj}] Session {sid} ({started}): Goal: {goal or '(none)'} | Summary: {summary or '(none)'}"
            hits.append(Hit(text=txt, source=self.name, ref=sid, score=1.0))
        return hits

    @staticmethod
    def format_timeline(sessions: List[Dict[str, Any]]) -> str:
        """Format session list into high-density human/agent readable text."""
        if not sessions:
            return "(no prior session history recorded)"

        lines = []
        for s in sessions:
            sid = s["session_id"]
            proj = s["project"]
            dur = f"{s['duration_seconds']:.0f}s" if s['duration_seconds'] < 60 else f"{s['duration_seconds']/60:.1f}m"
            branch_info = f" [{s['git_branch']} @ {s['git_head_after'] or s['git_head_before']}]" if s.get("git_branch") else ""
            status = s.get("status", "completed")

            lines.append(f"### Session `{sid}` ({proj}) - {status} ({dur}){branch_info}")
            if s.get("goal"):
                lines.append(f"- **Goal**: {s['goal']}")
            if s.get("summary"):
                lines.append(f"- **Summary**: {s['summary']}")
            if s.get("touched_files"):
                tf = ", ".join(s["touched_files"][:8])
                if len(s["touched_files"]) > 8:
                    tf += f" (+{len(s['touched_files']) - 8} more)"
                lines.append(f"- **Touched Files**: {tf}")
            if s.get("commits"):
                c_str = ", ".join(s["commits"][:5])
                lines.append(f"- **Commits**: {c_str}")
            lines.append("")

        return "\n".join(lines).strip()

    @staticmethod
    def format_recap(session: Optional[Dict[str, Any]]) -> str:
        """Format a single session recap for injection at session-start."""
        if not session:
            return ""
        sid = session.get("session_id", "previous")
        goal = session.get("goal") or "General development"
        summary = session.get("summary") or "Work in progress"
        touched = session.get("touched_files") or []
        tf_str = f" ({len(touched)} files touched: {', '.join(touched[:4])}{'...' if len(touched) > 4 else ''})" if touched else ""
        commits = session.get("commits") or []
        cm_str = f" [Commit: {', '.join(commits[:2])}]" if commits else ""

        return f"**Last Session (`{sid}`)**: {goal} -> {summary}{tf_str}{cm_str}"
