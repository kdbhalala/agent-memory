"""L2: Native SQLite Semantic Knowledge Graph Layer (zero external dependencies).

Stores durable knowledge as an interconnected graph of entities and relationships
with full-text search (FTS5) and multi-hop recursive graph traversal (CTE).
Replaces heavy graph libraries (Cognee, NetworkX, Chroma) with pure Python stdlib.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .base import Hit, MemoryLayer

DEFAULT_DB = Path.home() / ".agent-memory" / "memory.db"
CLAUDE_MEM_DB = Path.home() / ".claude-mem" / "claude-mem.db"


def get_db_path() -> Path:
    env_path = os.getenv("AGENT_MEMORY_DB") or os.getenv("CLAUDE_MEM_DB")
    if env_path:
        return Path(env_path)
    if CLAUDE_MEM_DB.exists():
        return CLAUDE_MEM_DB
    return DEFAULT_DB


class GraphLayer(MemoryLayer):
    """Native SQLite Semantic Knowledge Graph layer for durable memory."""
    name = "graph"

    def __init__(self, db_path: Path | str | None = None, project: str | None = None):
        self.db_path = Path(db_path) if db_path else get_db_path()
        self.project = project
        self._init_db()

    def _get_con(self, mode: str = "rw") -> sqlite3.Connection:
        if mode == "ro":
            return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = self._get_con(mode="rw")
        cur = con.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS graph_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                entity_type TEXT NOT NULL DEFAULT 'concept',
                description TEXT,
                project TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS graph_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                relation TEXT NOT NULL,
                target TEXT NOT NULL,
                fact TEXT NOT NULL,
                project TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source, relation, target, fact, project)
            )
        """)
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS graph_nodes_fts USING fts5(
                name, entity_type, description, content='graph_nodes', content_rowid='id'
            )
        """)
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS graph_edges_fts USING fts5(
                source, relation, target, fact, content='graph_edges', content_rowid='id'
            )
        """)

        # Sync triggers for nodes
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS graph_nodes_ai AFTER INSERT ON graph_nodes BEGIN
                INSERT INTO graph_nodes_fts(rowid, name, entity_type, description)
                VALUES (new.id, new.name, new.entity_type, new.description);
            END
        """)
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS graph_nodes_ad AFTER DELETE ON graph_nodes BEGIN
                INSERT INTO graph_nodes_fts(graph_nodes_fts, rowid, name, entity_type, description)
                VALUES ('delete', old.id, old.name, old.entity_type, old.description);
            END
        """)
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS graph_nodes_au AFTER UPDATE ON graph_nodes BEGIN
                INSERT INTO graph_nodes_fts(graph_nodes_fts, rowid, name, entity_type, description)
                VALUES ('delete', old.id, old.name, old.entity_type, old.description);
                INSERT INTO graph_nodes_fts(rowid, name, entity_type, description)
                VALUES (new.id, new.name, new.entity_type, new.description);
            END
        """)

        # Sync triggers for edges
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS graph_edges_ai AFTER INSERT ON graph_edges BEGIN
                INSERT INTO graph_edges_fts(rowid, source, relation, target, fact)
                VALUES (new.id, new.source, new.relation, new.target, new.fact);
            END
        """)
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS graph_edges_ad AFTER DELETE ON graph_edges BEGIN
                INSERT INTO graph_edges_fts(graph_edges_fts, rowid, source, relation, target, fact)
                VALUES ('delete', old.id, old.source, old.relation, old.target, old.fact);
            END
        """)
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS graph_edges_au AFTER UPDATE ON graph_edges BEGIN
                INSERT INTO graph_edges_fts(graph_edges_fts, rowid, source, relation, target, fact)
                VALUES ('delete', old.id, old.source, old.relation, old.target, old.fact);
                INSERT INTO graph_edges_fts(rowid, source, relation, target, fact)
                VALUES (new.id, new.source, new.relation, new.target, new.fact);
            END
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges(source)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges(target)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_project ON graph_edges(project)")

        con.commit()
        con.close()

    def add_node(self, name: str, entity_type: str = "concept", description: str = "",
                 project: str | None = None) -> int:
        """Add or update an entity node in the graph."""
        clean_name = name.strip()
        proj = project or self.project or "global"
        con = self._get_con()
        cur = con.cursor()
        cur.execute("""
            INSERT INTO graph_nodes (name, entity_type, description, project)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                entity_type=excluded.entity_type,
                description=COALESCE(excluded.description, graph_nodes.description),
                project=excluded.project
        """, (clean_name, entity_type, description, proj))
        node_id = cur.lastrowid
        con.commit()
        con.close()
        return node_id

    def add_edge(self, source: str, relation: str, target: str, fact: str,
                 project: str | None = None) -> None:
        """Add a directed edge connecting source and target with a relationship and fact."""
        s = source.strip()
        t = target.strip()
        r = relation.strip().upper().replace(" ", "_")
        f = fact.strip()
        proj = project or self.project or "global"

        # Ensure both endpoints exist as nodes
        self.add_node(s, project=proj)
        self.add_node(t, project=proj)

        con = self._get_con()
        cur = con.cursor()
        cur.execute("""
            INSERT INTO graph_edges (source, relation, target, fact, project)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source, relation, target, fact, project) DO UPDATE SET
                created_at=CURRENT_TIMESTAMP
        """, (s, r, t, f, proj))
        con.commit()
        con.close()

        # Fast append to vault (<0.1ms) and trigger debounced background sync
        try:
            from vault import append_edge_to_vault
            from sync import schedule_auto_sync
            append_edge_to_vault({
                "source": s,
                "relation": r,
                "target": t,
                "fact": f,
                "project": proj
            })
            schedule_auto_sync()
        except Exception:
            pass

    def add(self, text: str) -> None:
        """Extract entities and relations from text and ingest into the knowledge graph."""
        proj = self.project or "global"

        # Check if project tag is in text, e.g. "[my-proj] Title: fact"
        proj_match = re.match(r"^\[([a-zA-Z0-9_-]+)\]\s*(.*)", text)
        if proj_match:
            proj = proj_match.group(1)
            content = proj_match.group(2)
        else:
            content = text

        # 1. Try LLM extraction if an API key is available
        extracted = self._extract_with_llm(content, proj)
        if extracted:
            for s, r, t, f in extracted:
                self.add_edge(s, r, t, f, project=proj)
            return

        # 2. Rule-based heuristic extraction (zero-token offline fallback)
        triples = self._extract_heuristic(content, proj)
        for s, r, t, f in triples:
            self.add_edge(s, r, t, f, project=proj)

    def _extract_heuristic(self, text: str, project: str) -> List[Tuple[str, str, str, str]]:
        """Extract relationship triples using linguistic and structural heuristics."""
        results: List[Tuple[str, str, str, str]] = []

        # Patterns like: "Title: Fact" or "Concept: Decision"
        colon_match = re.match(r"^([^:]{3,50}):\s*(.+)$", text)
        if colon_match:
            concept = colon_match.group(1).strip()
            fact = colon_match.group(2).strip()

            # Check for common relationship verbs in fact
            verbs = [
                (r"\b(?:uses|utilizes|relies on)\b\s+([A-Za-z0-9_.-]+)", "USES"),
                (r"\b(?:depends on|requires)\b\s+([A-Za-z0-9_.-]+)", "DEPENDS_ON"),
                (r"\b(?:replaces|deprecated)\b\s+([A-Za-z0-9_.-]+)", "REPLACES"),
                (r"\b(?:implements|provides)\b\s+([A-Za-z0-9_.-]+)", "IMPLEMENTS"),
                (r"\b(?:stored in|persisted in)\b\s+([A-Za-z0-9_.-]+)", "STORED_IN"),
                (r"\b(?:fixed in|resolved by)\b\s+([A-Za-z0-9_.-]+)", "FIXED_BY"),
                (r"\b(?:prohibits|forbidden|never use)\b\s+([A-Za-z0-9_.-]+)", "PROHIBITS"),
            ]
            found = False
            for v_pat, rel in verbs:
                m = re.search(v_pat, fact, re.I)
                if m:
                    target = m.group(1).strip()
                    results.append((concept, rel, target, fact))
                    found = True
                    break
            if not found:
                # Default generic relationship
                results.append((concept, "SPECIFIES", project, fact))
            return results

        # Sentence-level extraction
        for sentence in re.split(r"[.\n]", text):
            sentence = sentence.strip()
            if len(sentence) < 15:
                continue

            patterns = [
                (r"([A-Za-z0-9_-]+)\s+(?:must use|uses|utilize)\s+([A-Za-z0-9_-]+)", "USES"),
                (r"([A-Za-z0-9_-]+)\s+(?:depends on|requires)\s+([A-Za-z0-9_-]+)", "DEPENDS_ON"),
                (r"([A-Za-z0-9_-]+)\s+(?:should not use|avoid|never use)\s+([A-Za-z0-9_-]+)", "PROHIBITS"),
                (r"([A-Za-z0-9_-]+)\s+(?:is stored in|stored in)\s+([A-Za-z0-9_-]+)", "STORED_IN"),
                (r"([A-Za-z0-9_-]+)\s+(?:implements|extends)\s+([A-Za-z0-9_-]+)", "IMPLEMENTS"),
            ]
            for pat, rel in patterns:
                m = re.search(pat, sentence, re.I)
                if m:
                    s, t = m.group(1).strip(), m.group(2).strip()
                    if s.lower() != t.lower():
                        results.append((s, rel, t, sentence))
                        break

        # If nothing matched, store as an observation node connected to project
        if not results and len(text) >= 20:
            words = [w for w in re.findall(r"[A-Za-z0-9_]{3,}", text) if not w.lower().startswith("http")]
            core_term = words[0] if words else "Convention"
            results.append((core_term, "APPLIES_TO", project, text[:250]))

        return results

    def _extract_with_llm(self, text: str, project: str) -> Optional[List[Tuple[str, str, str, str]]]:
        """Optional LLM semantic triple extractor via stdlib urllib (zero packages)."""
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY") or os.getenv("LLM_API_KEY")
        endpoint = os.getenv("LLM_ENDPOINT", "https://api.openai.com/v1/chat/completions")
        model = os.getenv("LLM_MODEL", "gpt-4o-mini" if "api.openai.com" in endpoint else "openrouter/auto")

        if not api_key:
            return None

        prompt = (
            "Extract semantic knowledge graph triples from this technical note.\n"
            "Output ONLY a valid JSON array of objects with keys: source, relation, target, fact.\n"
            "Example: [{\"source\":\"AuthService\",\"relation\":\"USES\",\"target\":\"JWT\",\"fact\":\"AuthService uses JWT\"}]\n\n"
            f"Text: {text}"
        )

        try:
            req_data = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
            }
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(req_data).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                }
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.load(resp)
                raw_out = data["choices"][0]["message"]["content"].strip()
                # Clean code blocks
                raw_out = re.sub(r"^```(?:json)?|```$", "", raw_out, flags=re.MULTILINE).strip()
                parsed = json.loads(raw_out)
                results = []
                for item in parsed:
                    s = item.get("source", "").strip()
                    r = item.get("relation", "").strip().upper()
                    t = item.get("target", "").strip()
                    f = item.get("fact", "").strip()
                    if s and r and t and f:
                        results.append((s, r, t, f))
                return results if results else None
        except Exception:
            return None

    def search(self, query: str, limit: int = 5) -> List[Hit]:
        """Search graph: match starting entities/facts and traverse connected relations."""
        tokens = [t for t in re.findall(r"[a-zA-Z0-9_-]+", query.lower()) if len(t) > 2]
        if not tokens:
            return []

        con = self._get_con(mode="ro")
        cur = con.cursor()

        # Step 1: Find matched nodes via FTS5 or LIKE prefix
        ph_match = " OR ".join(f'"{t}"*' for t in tokens)
        matched_nodes: Set[str] = set()

        try:
            cur.execute("SELECT name FROM graph_nodes_fts WHERE graph_nodes_fts MATCH ? LIMIT 10", (ph_match,))
            for (name,) in cur.fetchall():
                matched_nodes.add(name)
        except Exception:
            pass

        # Fallback LIKE matching
        for t in tokens[:3]:
            cur.execute("SELECT name FROM graph_nodes WHERE name LIKE ? OR description LIKE ? LIMIT 5",
                        (f"%{t}%", f"%{t}%"))
            for (name,) in cur.fetchall():
                matched_nodes.add(name)

        hits: List[Hit] = []
        seen_facts: Set[str] = set()

        # Step 2: Traverse 2-hop graph neighborhood from matched nodes
        if matched_nodes:
            node_list = list(matched_nodes)
            ph = ",".join("?" for _ in node_list)
            args: List[Any] = node_list + node_list

            proj_filter_0 = ""
            proj_filter_1 = ""
            if self.project:
                proj_filter_0 = "AND (e0.project = ? OR e0.project = 'global')"
                proj_filter_1 = "AND (e.project = ? OR e.project = 'global')"
                args = node_list + node_list + [self.project, self.project]

            traversal_sql = f"""
                WITH RECURSIVE graph_path(node, depth, path, fact) AS (
                    SELECT e0.target, 0, e0.source || ' -> ' || e0.relation || ' -> ' || e0.target, e0.fact
                    FROM graph_edges e0
                    WHERE (e0.source IN ({ph}) OR e0.target IN ({ph})) {proj_filter_0}
                    UNION ALL
                    SELECT e.target, gp.depth + 1, gp.path || ' -> ' || e.relation || ' -> ' || e.target, e.fact
                    FROM graph_edges e
                    JOIN graph_path gp ON e.source = gp.node
                    WHERE gp.depth < 2 {proj_filter_1}
                )
                SELECT DISTINCT path, fact FROM graph_path LIMIT ?;
            """
            args.append(limit * 2)

            try:
                for path, fact in cur.execute(traversal_sql, args).fetchall():
                    if fact not in seen_facts:
                        seen_facts.add(fact)
                        hits.append(Hit(text=f"[{path}] {fact}", source=self.name, ref=path))
                        if len(hits) >= limit:
                            break
            except Exception:
                pass

        # Step 3: Direct edge search via FTS5 if graph traversal found few hits
        if len(hits) < limit:
            try:
                cur.execute("""
                    SELECT source, relation, target, fact FROM graph_edges_fts
                    WHERE graph_edges_fts MATCH ? LIMIT ?
                """, (ph_match, limit - len(hits)))
                for s, r, t, f in cur.fetchall():
                    if f not in seen_facts:
                        seen_facts.add(f)
                        path = f"{s} -> {r} -> {t}"
                        hits.append(Hit(text=f"[{path}] {f}", source=self.name, ref=path))
            except Exception:
                pass

        con.close()
        return hits[:limit]

    def stats(self) -> Dict[str, Any]:
        """Return graph statistics (node count, edge count, relation counts)."""
        con = self._get_con(mode="ro")
        cur = con.cursor()
        node_count = cur.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0]
        edge_count = cur.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0]
        relations = [r[0] for r in cur.execute("SELECT DISTINCT relation FROM graph_edges").fetchall()]
        projects = [r[0] for r in cur.execute("SELECT DISTINCT project FROM graph_edges").fetchall()]
        con.close()
        return {
            "nodes": node_count,
            "edges": edge_count,
            "relations": relations,
            "projects": projects,
            "db_path": str(self.db_path)
        }
