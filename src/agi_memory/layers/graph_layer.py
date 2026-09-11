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
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .base import Hit, MemoryLayer

try:
    from agi_memory.config import CLAUDE_MEM_DB, DEFAULT_DB, get_default_db
except ImportError:
    try:
        from ..config import CLAUDE_MEM_DB, DEFAULT_DB, get_default_db
    except (ImportError, ValueError):
        from config import CLAUDE_MEM_DB, DEFAULT_DB, get_default_db

get_db_path = get_default_db

OnEdgeCallback = Callable[[dict], None]
_EDGE_LISTENERS: list[OnEdgeCallback] = []


def add_edge_listener(listener: OnEdgeCallback) -> None:
    """Register a callback to be invoked when an edge is added to the graph."""
    if listener not in _EDGE_LISTENERS:
        _EDGE_LISTENERS.append(listener)


def remove_edge_listener(listener: OnEdgeCallback) -> None:
    """Unregister a previously registered edge callback."""
    if listener in _EDGE_LISTENERS:
        _EDGE_LISTENERS.remove(listener)

STANDARD_ALIASES: List[Tuple[str, str, str]] = [
    ("fcm", "FirebaseCloudMessaging", "messaging"),
    ("k8s", "Kubernetes", "infra"),
    ("jwt", "JSONWebToken", "auth"),
    ("sqlite", "SQLite", "database"),
    ("postgres", "PostgreSQL", "database"),
    ("postgresql", "PostgreSQL", "database"),
    ("auth", "Authentication", "security"),
    ("ts", "TypeScript", "language"),
    ("py", "Python", "language"),
    ("mcp", "ModelContextProtocol", "protocol"),
    ("db", "Database", "storage"),
    ("api", "API", "interface"),
    ("ui", "UserInterface", "interface"),
    ("ci", "ContinuousIntegration", "devops"),
]

POSITIVE_RELATIONS: Set[str] = {
    "USES", "UTILIZES", "DEPENDS_ON", "REQUIRES",
    "IMPLEMENTS", "ALLOWS", "PERMITS", "ENABLES", "RECOMMENDS", "SUPPORTS"
}

NEGATIVE_RELATIONS: Set[str] = {
    "PROHIBITS", "FORBIDS", "AVOIDS", "DISABLES", "DEPRECATED", "PREVENTS"
}

NON_EXCLUSIVE_RELATIONS: Set[str] = {
    "APPLIES_TO", "SPECIFIES", "RELATES_TO", "TAGGED_WITH", "MENTIONS", "PART_OF"
}


def is_opposing_relation(r1: str, r2: str) -> bool:
    """Determine whether two relationship types are semantically opposing."""
    u1, u2 = r1.strip().upper(), r2.strip().upper()
    if u1 == u2:
        return False
    if u1 == "REPLACES" or u2 == "REPLACES":
        return True
    if u1 in POSITIVE_RELATIONS and u2 in NEGATIVE_RELATIONS:
        return True
    if u1 in NEGATIVE_RELATIONS and u2 in POSITIVE_RELATIONS:
        return True
    if u1.startswith("NOT_") and u1[4:] == u2:
        return True
    if u2.startswith("NOT_") and u2[4:] == u1:
        return True
    return False


class GraphLayer(MemoryLayer):
    """Native SQLite Semantic Knowledge Graph layer for durable memory."""
    name = "graph"

    def __init__(self, db_path: Path | str | None = None, project: str | None = None,
                 on_edge: OnEdgeCallback | None = None):
        self.db_path = Path(db_path) if db_path else get_db_path()
        self.project = project
        self.on_edge = on_edge
        self._alias_cache: dict[str, str] = {}
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
                is_active INTEGER NOT NULL DEFAULT 1,
                valid_from TEXT DEFAULT CURRENT_TIMESTAMP,
                valid_until TEXT,
                superseded_by TEXT,
                UNIQUE(source, relation, target, fact, project)
            )
        """)

        # Migration for existing graph_edges table
        cur.execute("PRAGMA table_info(graph_edges)")
        existing_cols = {r[1] for r in cur.fetchall()}
        if "is_active" not in existing_cols:
            cur.execute("ALTER TABLE graph_edges ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
        if "valid_from" not in existing_cols:
            cur.execute("ALTER TABLE graph_edges ADD COLUMN valid_from TEXT")
            cur.execute("UPDATE graph_edges SET valid_from = CURRENT_TIMESTAMP WHERE valid_from IS NULL")
        if "valid_until" not in existing_cols:
            cur.execute("ALTER TABLE graph_edges ADD COLUMN valid_until TEXT")
        if "superseded_by" not in existing_cols:
            cur.execute("ALTER TABLE graph_edges ADD COLUMN superseded_by TEXT")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS graph_aliases (
                alias TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                category TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_graph_aliases_canonical ON graph_aliases(canonical_name)")

        # Auto-seed standard aliases if table is empty
        cur.execute("SELECT COUNT(*) FROM graph_aliases")
        if cur.fetchone()[0] == 0:
            cur.executemany("""
                INSERT OR IGNORE INTO graph_aliases (alias, canonical_name, category)
                VALUES (?, ?, ?)
            """, [(a.lower(), c, cat) for a, c, cat in STANDARD_ALIASES])

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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_graph_edges_active ON graph_edges(is_active)")

        cur.execute("SELECT alias, canonical_name FROM graph_aliases")
        self._alias_cache = {r[0].lower(): r[1] for r in cur.fetchall()}

        con.commit()
        con.close()

    def resolve_node(self, name: str) -> str:
        """Canonicalize name by checking lowercased alias against graph_aliases."""
        clean_name = name.strip()
        if not clean_name:
            return clean_name
        if not hasattr(self, "_alias_cache") or self._alias_cache is None:
            self._load_alias_cache()
        return self._alias_cache.get(clean_name.lower(), clean_name)

    def add_alias(self, alias: str, canonical_name: str, category: str = "") -> None:
        """Insert or replace an entity alias mapping in graph_aliases."""
        a = alias.strip().lower()
        c = canonical_name.strip()
        cat = category.strip()
        if not a or not c:
            return
        con = self._get_con(mode="rw")
        cur = con.cursor()
        cur.execute("""
            INSERT INTO graph_aliases (alias, canonical_name, category)
            VALUES (?, ?, ?)
            ON CONFLICT(alias) DO UPDATE SET
                canonical_name = excluded.canonical_name,
                category = excluded.category,
                created_at = CURRENT_TIMESTAMP
        """, (a, c, cat))
        con.commit()
        con.close()
        if not hasattr(self, "_alias_cache") or self._alias_cache is None:
            self._alias_cache = {}
        self._alias_cache[a] = c

    def list_aliases(self) -> dict[str, str]:
        """Return dictionary of alias -> canonical_name."""
        con = self._get_con(mode="ro")
        cur = con.cursor()
        cur.execute("SELECT alias, canonical_name FROM graph_aliases ORDER BY alias ASC")
        res = {r[0]: r[1] for r in cur.fetchall()}
        con.close()
        self._alias_cache = {k.lower(): v for k, v in res.items()}
        return res

    def _load_alias_cache(self) -> None:
        """Load aliases into local in-memory cache for sub-millisecond lookup."""
        try:
            con = self._get_con(mode="ro")
            cur = con.cursor()
            cur.execute("SELECT alias, canonical_name FROM graph_aliases")
            self._alias_cache = {r[0].lower(): r[1] for r in cur.fetchall()}
            con.close()
        except Exception:
            self._alias_cache = {}

    def add_node(self, name: str, entity_type: str = "concept", description: str = "",
                 project: str | None = None) -> int:
        """Add or update an entity node in the graph."""
        clean_name = self.resolve_node(name)
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
        s = self.resolve_node(source)
        t = self.resolve_node(target)
        r = relation.strip().upper().replace(" ", "_")
        f = fact.strip()
        proj = project or self.project or "global"

        # Ensure both endpoints exist as nodes
        self.add_node(s, project=proj)
        self.add_node(t, project=proj)

        superseded_tag = f"{s} -> {r} -> {t}"

        con = self._get_con()
        cur = con.cursor()

        # Invalidation logic:
        # Check active edges connecting source and target with:
        # - opposing relation (e.g. USES vs PROHIBITS/FORBIDS)
        # - relation is REPLACES
        # - same relation with different fact
        cur.execute("""
            SELECT id, source, target, relation, fact FROM graph_edges
            WHERE is_active = 1
              AND ((source = ? AND target = ?) OR (source = ? AND target = ?))
              AND (project = ? OR project = 'global')
        """, (s, t, t, s, proj))
        rows = cur.fetchall()

        to_invalidate = []
        for edge_id, row_src, row_tgt, row_rel, row_fact in rows:
            if row_src == s and row_tgt == t:
                if is_opposing_relation(r, row_rel):
                    to_invalidate.append(edge_id)
                elif row_rel == r and row_fact != f:
                    if row_rel not in NON_EXCLUSIVE_RELATIONS and row_tgt != proj and row_src != proj:
                        to_invalidate.append(edge_id)
            elif row_src == t and row_tgt == s:
                if r == "REPLACES" or row_rel == "REPLACES":
                    to_invalidate.append(edge_id)

        if to_invalidate:
            ph = ",".join("?" for _ in to_invalidate)
            cur.execute(f"""
                UPDATE graph_edges
                SET is_active = 0, valid_until = CURRENT_TIMESTAMP, superseded_by = ?
                WHERE id IN ({ph})
            """, [superseded_tag] + to_invalidate)

        cur.execute("""
            INSERT INTO graph_edges (
                source, relation, target, fact, project,
                is_active, valid_from, valid_until, superseded_by
            )
            VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, NULL, NULL)
            ON CONFLICT(source, relation, target, fact, project) DO UPDATE SET
                is_active = 1,
                valid_until = NULL,
                superseded_by = NULL,
                created_at = CURRENT_TIMESTAMP
        """, (s, r, t, f, proj))
        con.commit()
        con.close()

        edge_payload = {
            "source": s,
            "relation": r,
            "target": t,
            "fact": f,
            "project": proj,
            "is_active": 1,
            "valid_from": time.strftime("%Y-%m-%d %H:%M:%S"),
            "valid_until": None,
            "superseded_by": None
        }

        if self.on_edge:
            try:
                self.on_edge(edge_payload)
            except Exception:
                pass
        for listener in _EDGE_LISTENERS:
            try:
                listener(edge_payload)
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

    def search(self, query: str, limit: int = 5, include_inactive: bool = False) -> List[Hit]:
        """Search graph: match starting entities/facts and traverse connected relations."""
        tokens = [t for t in re.findall(r"[a-zA-Z0-9_-]+", query.lower()) if len(t) > 2]
        if not tokens:
            return []

        con = self._get_con(mode="ro")
        cur = con.cursor()

        # Step 1: Find matched nodes via FTS5 or LIKE prefix, resolving entity aliases
        matched_nodes: Set[str] = set()
        search_terms: List[str] = list(tokens)

        clean_q = query.strip()
        canon_q = self.resolve_node(clean_q)
        if canon_q.lower() != clean_q.lower():
            matched_nodes.add(canon_q)
            for sub_t in re.findall(r"[a-zA-Z0-9_-]+", canon_q.lower()):
                if len(sub_t) > 2 and sub_t not in search_terms:
                    search_terms.append(sub_t)

        for t in tokens:
            canon_t = self.resolve_node(t)
            if canon_t.lower() != t.lower():
                matched_nodes.add(canon_t)
                for sub_t in re.findall(r"[a-zA-Z0-9_-]+", canon_t.lower()):
                    if len(sub_t) > 2 and sub_t not in search_terms:
                        search_terms.append(sub_t)

        ph_match = " OR ".join(f'"{t}"*' for t in search_terms)

        try:
            cur.execute("SELECT name FROM graph_nodes_fts WHERE graph_nodes_fts MATCH ? LIMIT 10", (ph_match,))
            for (name,) in cur.fetchall():
                matched_nodes.add(name)
        except Exception:
            pass

        # Fallback LIKE matching
        for t in search_terms[:3]:
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

            active_filter_0 = "" if include_inactive else "AND e0.is_active = 1"
            active_filter_1 = "" if include_inactive else "AND e.is_active = 1"

            traversal_sql = f"""
                WITH RECURSIVE graph_path(node, depth, path, fact) AS (
                    SELECT e0.target, 0, e0.source || ' -> ' || e0.relation || ' -> ' || e0.target, e0.fact
                    FROM graph_edges e0
                    WHERE (e0.source IN ({ph}) OR e0.target IN ({ph})) {active_filter_0} {proj_filter_0}
                    UNION ALL
                    SELECT e.target, gp.depth + 1, gp.path || ' -> ' || e.relation || ' -> ' || e.target, e.fact
                    FROM graph_edges e
                    JOIN graph_path gp ON e.source = gp.node
                    WHERE gp.depth < 2 {active_filter_1} {proj_filter_1}
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
                active_fts_filter = "" if include_inactive else "AND e.is_active = 1"
                fts_sql = f"""
                    SELECT e.source, e.relation, e.target, e.fact
                    FROM graph_edges_fts fts
                    JOIN graph_edges e ON e.id = fts.rowid
                    WHERE graph_edges_fts MATCH ? {active_fts_filter}
                    LIMIT ?
                """
                cur.execute(fts_sql, (ph_match, limit - len(hits)))
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
        active_edge_count = cur.execute("SELECT COUNT(*) FROM graph_edges WHERE is_active = 1").fetchone()[0]
        relations = [r[0] for r in cur.execute("SELECT DISTINCT relation FROM graph_edges").fetchall()]
        projects = [r[0] for r in cur.execute("SELECT DISTINCT project FROM graph_edges").fetchall()]
        alias_count = cur.execute("SELECT COUNT(*) FROM graph_aliases").fetchone()[0]
        con.close()
        return {
            "nodes": node_count,
            "edges": edge_count,
            "active_edges": active_edge_count,
            "relations": relations,
            "projects": projects,
            "aliases": alias_count,
            "db_path": str(self.db_path)
        }
