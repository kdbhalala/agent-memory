"""Vault storage and compaction engine for agent-memory.

Decouples framework code from user memory data.
Maintains canonical, Git-friendly append-only JSONL files in ~/.agent-memory/vault/
and synchronizes with local high-performance SQLite indexes (<2ms).
Provides periodic deduplication and compaction to prevent unbounded data growth.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional, Set, Tuple

DATA_DIR = Path(os.environ.get("AGENT_MEMORY_DIR", Path.home() / ".agent-memory"))
VAULT_DIR = Path(os.environ.get("AGENT_MEMORY_VAULT", DATA_DIR / "vault"))
SESSION_DB = Path(os.environ.get("AGENT_MEMORY_DB", DATA_DIR / "memory.db"))
GRAPH_DB = Path(os.environ.get("AGENT_MEMORY_GRAPH_DB", DATA_DIR / "memory.db"))
LEGACY_CLAUDE_MEM_DB = Path.home() / ".claude-mem" / "claude-mem.db"

NO_SIGNAL_PATTERN = re.compile(
    r"^(none[\s,]*)+$|no (?:new |technical )*(patterns|learnings|work|changes)|"
    r"nothing (new|learned)|not (yet |currently )?(identified|performed|introduced)|"
    r"no work has been performed",
    re.I
)


def get_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def get_vault_dir(vault_dir: Path | str | None = None) -> Path:
    target = Path(vault_dir) if vault_dir else VAULT_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def compute_guid(project: str, title: str, text: str, extra: str = "") -> str:
    """Generate a deterministic GUID for conflict-free cross-device syncing."""
    raw = f"{project.strip().lower()}:{title.strip()}:{text.strip()}:{extra.strip()}"
    return "obs_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def init_vault(vault_dir: Path | str | None = None) -> Path:
    """Initialize vault directory, standard files, and .gitignore."""
    v_dir = get_vault_dir(vault_dir)
    obs_file = v_dir / "observations.jsonl"
    graph_file = v_dir / "graph.jsonl"
    promoted_file = v_dir / "promoted.json"
    gitignore_file = v_dir / ".gitignore"
    readme_file = v_dir / "README.md"

    if not obs_file.exists():
        obs_file.touch()
    if not graph_file.exists():
        graph_file.touch()
    if not promoted_file.exists():
        promoted_file.write_text("[]\n")
    if not gitignore_file.exists():
        gitignore_file.write_text(
            "# agent-memory vault gitignore\n"
            "*.tmp\n"
            "*.bak\n"
            ".DS_Store\n"
            "*.sqlite\n"
            "*.db\n"
        )
    if not readme_file.exists():
        readme_file.write_text(
            "# Agent Memory Vault\n\n"
            "Canonical cross-device memory vault for your AI coding assistants.\n"
            "- `observations.jsonl`: Working session memories and precedents.\n"
            "- `graph.jsonl`: Multi-hop knowledge graph (triples and entities).\n"
            "- `promoted.json`: Curated durable items.\n\n"
            "Managed automatically by `agent-memory`.\n"
        )
    return v_dir


def bootstrap_from_existing_claudemem(
    vault_dir: Path | str | None = None,
    session_db: Path | str | None = None
) -> int:
    """Migrate observations from legacy claude-mem.db if present and not yet imported."""
    if not LEGACY_CLAUDE_MEM_DB.exists():
        return 0

    v_dir = init_vault(vault_dir)
    s_db = Path(session_db) if session_db else SESSION_DB
    s_db.parent.mkdir(parents=True, exist_ok=True)

    con_target = sqlite3.connect(s_db)
    con_target.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, memory_session_id TEXT, project TEXT,
            type TEXT, title TEXT, subtitle TEXT, facts TEXT, narrative TEXT,
            concepts TEXT, files_read TEXT, files_modified TEXT, prompt_number INT,
            discovery_tokens INT, created_at TEXT, created_at_epoch INT, content_hash TEXT,
            generated_by_model TEXT, relevance_count INT, sync_rev TEXT
        )
    """)
    cur_dst = con_target.execute("PRAGMA table_info(observations)")
    dst_cols = [r[1] for r in cur_dst.fetchall()]

    con_src = sqlite3.connect(f"file:{LEGACY_CLAUDE_MEM_DB}?mode=ro", uri=True)
    con_src.row_factory = sqlite3.Row
    try:
        rows = con_src.execute("SELECT * FROM observations").fetchall()
    except Exception:
        con_src.close()
        con_target.close()
        return 0

    if not rows:
        con_src.close()
        con_target.close()
        return 0

    cols_str = ", ".join(dst_cols)
    ph = ", ".join("?" for _ in dst_cols)

    batch = []
    for r in rows:
        row_dict = dict(r)
        if not row_dict.get("narrative") and row_dict.get("text"):
            row_dict["narrative"] = row_dict["text"]
        vals = [row_dict.get(c) for c in dst_cols]
        batch.append(vals)

    con_target.executemany(f"INSERT OR IGNORE INTO observations ({cols_str}) VALUES ({ph})", batch)

    con_target.execute("""
        CREATE TABLE IF NOT EXISTS session_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT, memory_session_id TEXT, project TEXT,
            learned TEXT, completed TEXT, next_steps TEXT, created_at TEXT, created_at_epoch INT
        )
    """)
    try:
        s_rows = con_src.execute("SELECT * FROM session_summaries").fetchall()
        s_cols = ["id", "memory_session_id", "project", "learned", "completed", "next_steps", "created_at", "created_at_epoch"]
        s_batch = []
        for sr in s_rows:
            sd = dict(sr)
            s_batch.append([sd.get(c) for c in s_cols])
        s_cols_str = ", ".join(s_cols)
        s_ph = ", ".join("?" for _ in s_cols)
        con_target.executemany(f"INSERT OR IGNORE INTO session_summaries ({s_cols_str}) VALUES ({s_ph})", s_batch)
    except Exception:
        pass

    con_target.commit()
    con_src.close()
    con_target.close()

    export_dirty_to_vault(vault_dir=v_dir, session_db=s_db)
    return len(batch)


def append_observation_to_vault(obs_dict: dict, vault_dir: Path | str | None = None) -> bool:
    """Fast-path append a single newly created observation directly to vault JSONL in <0.1ms."""
    try:
        v_dir = init_vault(vault_dir)
        obs_file = v_dir / "observations.jsonl"
        ch = obs_dict.get("content_hash") or obs_dict.get("guid")
        if not ch:
            ch = compute_guid(
                obs_dict.get("project") or "",
                obs_dict.get("title") or "",
                (obs_dict.get("narrative") or "") + (obs_dict.get("facts") or "")
            )
        d = dict(obs_dict)
        d["guid"] = ch
        d["content_hash"] = ch
        line = json.dumps(d, ensure_ascii=False) + "\n"
        with open(obs_file, "a", encoding="utf-8") as f:
            f.write(line)
        return True
    except Exception:
        return False


def append_edge_to_vault(edge_dict: dict, vault_dir: Path | str | None = None) -> bool:
    """Fast-path append a single newly created graph edge directly to vault JSONL in <0.1ms."""
    try:
        v_dir = init_vault(vault_dir)
        graph_file = v_dir / "graph.jsonl"
        proj = edge_dict.get("project") or "global"
        key = f"edge:{proj}:{edge_dict['source'].lower()}:{edge_dict['relation'].upper()}:{edge_dict['target'].lower()}:{edge_dict.get('fact', '')}"
        d = dict(edge_dict)
        d["kind"] = "edge"
        d["key"] = key
        d["project"] = proj
        d["is_active"] = int(edge_dict.get("is_active", 1) if edge_dict.get("is_active") is not None else 1)
        d["valid_from"] = edge_dict.get("valid_from") or time.strftime("%Y-%m-%d %H:%M:%S")
        d["valid_until"] = edge_dict.get("valid_until")
        d["superseded_by"] = edge_dict.get("superseded_by")
        line = json.dumps(d, ensure_ascii=False) + "\n"
        with open(graph_file, "a", encoding="utf-8") as f:
            f.write(line)
        return True
    except Exception:
        return False


def export_dirty_to_vault(
    vault_dir: Path | str | None = None,
    session_db: Path | str | None = None,
    graph_db: Path | str | None = None
) -> dict[str, int]:
    """Export records from SQLite to vault JSONL files idempotently."""
    v_dir = init_vault(vault_dir)
    s_db = Path(session_db) if session_db else SESSION_DB
    g_db = Path(graph_db) if graph_db else GRAPH_DB

    exported_obs = 0
    exported_graph = 0

    # 1. Export observations
    obs_file = v_dir / "observations.jsonl"
    existing_hashes: Set[str] = set()
    if obs_file.exists():
        with open(obs_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        item = json.loads(line)
                        h = item.get("content_hash") or item.get("guid")
                        if h:
                            existing_hashes.add(h)
                    except json.JSONDecodeError:
                        continue

    if s_db.exists():
        con = sqlite3.connect(f"file:{s_db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            cur = con.execute("""
                SELECT project, type, title, subtitle, facts, narrative,
                       concepts, files_read, files_modified, created_at,
                       created_at_epoch, content_hash
                FROM observations
                ORDER BY created_at_epoch ASC
            """)
            new_lines = []
            for row in cur:
                ch = row["content_hash"]
                if not ch:
                    ch = compute_guid(row["project"] or "", row["title"] or "",
                                      (row["narrative"] or "") + (row["facts"] or ""))
                if ch in existing_hashes:
                    continue

                d = dict(row)
                d["guid"] = ch
                new_lines.append(json.dumps(d, ensure_ascii=False) + "\n")
                existing_hashes.add(ch)
                exported_obs += 1

            if new_lines:
                with open(obs_file, "a", encoding="utf-8") as f:
                    f.writelines(new_lines)
        except Exception:
            pass
        finally:
            con.close()

    # 2. Export graph nodes and edges
    graph_file = v_dir / "graph.jsonl"
    existing_graph_keys: Set[str] = set()
    if graph_file.exists():
        with open(graph_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        item = json.loads(line)
                        k = item.get("key")
                        if k:
                            existing_graph_keys.add(k)
                    except json.JSONDecodeError:
                        continue

    if g_db.exists():
        con = sqlite3.connect(f"file:{g_db}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        try:
            new_graph_lines = []
            # Nodes
            cur = con.execute("SELECT name, entity_type, description, project FROM graph_nodes")
            for row in cur:
                key = f"node:{row['project']}:{row['name'].lower()}"
                if key not in existing_graph_keys:
                    d = dict(row)
                    d["kind"] = "node"
                    d["key"] = key
                    new_graph_lines.append(json.dumps(d, ensure_ascii=False) + "\n")
                    existing_graph_keys.add(key)
                    exported_graph += 1

            # Edges
            cur_cols = [c[1] for c in con.execute("PRAGMA table_info(graph_edges)").fetchall()]
            has_bi_temporal = "is_active" in cur_cols
            if has_bi_temporal:
                cur = con.execute("""
                    SELECT source, relation, target, fact, project,
                           is_active, valid_from, valid_until, superseded_by
                    FROM graph_edges
                """)
            else:
                cur = con.execute("SELECT source, relation, target, fact, project FROM graph_edges")

            for row in cur:
                key = f"edge:{row['project']}:{row['source'].lower()}:{row['relation'].upper()}:{row['target'].lower()}:{row['fact']}"
                if key not in existing_graph_keys:
                    d = dict(row)
                    d["kind"] = "edge"
                    d["key"] = key
                    d["is_active"] = int(row["is_active"] if has_bi_temporal and row["is_active"] is not None else 1)
                    d["valid_from"] = (row["valid_from"] if has_bi_temporal and row["valid_from"] else time.strftime("%Y-%m-%d %H:%M:%S"))
                    d["valid_until"] = row["valid_until"] if has_bi_temporal else None
                    d["superseded_by"] = row["superseded_by"] if has_bi_temporal else None
                    new_graph_lines.append(json.dumps(d, ensure_ascii=False) + "\n")
                    existing_graph_keys.add(key)
                    exported_graph += 1

            if new_graph_lines:
                with open(graph_file, "a", encoding="utf-8") as f:
                    f.writelines(new_graph_lines)
        except Exception:
            pass
        finally:
            con.close()

    return {"observations": exported_obs, "graph": exported_graph}


def import_from_vault(
    vault_dir: Path | str | None = None,
    session_db: Path | str | None = None,
    graph_db: Path | str | None = None
) -> dict[str, int]:
    """Import records from vault JSONL files into local SQLite tables idempotently."""
    v_dir = init_vault(vault_dir)
    s_db = Path(session_db) if session_db else SESSION_DB
    g_db = Path(graph_db) if graph_db else GRAPH_DB

    s_db.parent.mkdir(parents=True, exist_ok=True)
    g_db.parent.mkdir(parents=True, exist_ok=True)

    imported_obs = 0
    imported_graph = 0

    # 1. Import observations into session_db
    obs_file = v_dir / "observations.jsonl"
    if obs_file.exists():
        from layers.session_layer import SessionLayer
        SessionLayer._init_db(s_db)

        con = sqlite3.connect(s_db)
        existing_hashes = set(
            r[0] for r in con.execute("SELECT content_hash FROM observations WHERE content_hash IS NOT NULL").fetchall()
        )

        rows_to_insert = []
        with open(obs_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ch = d.get("content_hash") or d.get("guid")
                if not ch:
                    ch = compute_guid(d.get("project", ""), d.get("title", ""),
                                      d.get("narrative", "") + d.get("facts", ""))
                if ch in existing_hashes:
                    continue

                rows_to_insert.append((
                    d.get("memory_session_id", "sync"),
                    d.get("project"),
                    d.get("type", "observation"),
                    d.get("title", ""),
                    d.get("subtitle", ""),
                    d.get("facts", ""),
                    d.get("narrative", ""),
                    d.get("concepts", ""),
                    d.get("files_read", ""),
                    d.get("files_modified", ""),
                    d.get("prompt_number", 0),
                    d.get("discovery_tokens", 0),
                    d.get("created_at", ""),
                    d.get("created_at_epoch", int(time.time())),
                    ch,
                    d.get("generated_by_model", "sync"),
                    d.get("relevance_count", 0),
                    d.get("sync_rev", "vault")
                ))
                existing_hashes.add(ch)

        if rows_to_insert:
            con.executemany("""
                INSERT OR IGNORE INTO observations (
                    memory_session_id, project, type, title, subtitle, facts,
                    narrative, concepts, files_read, files_modified, prompt_number,
                    discovery_tokens, created_at, created_at_epoch, content_hash,
                    generated_by_model, relevance_count, sync_rev
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows_to_insert)
            con.commit()
            imported_obs = len(rows_to_insert)
        con.close()

    # 2. Import graph nodes and edges into graph_db
    graph_file = v_dir / "graph.jsonl"
    if graph_file.exists():
        from layers.graph_layer import GraphLayer
        gl = GraphLayer(db_path=g_db)

        con = sqlite3.connect(g_db)
        with open(graph_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                kind = d.get("kind")
                if kind == "node":
                    name = gl.resolve_node(d.get("name", "")) if hasattr(gl, "resolve_node") else d.get("name", "")
                    con.execute("""
                        INSERT INTO graph_nodes (name, entity_type, description, project)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(name) DO UPDATE SET
                            description = CASE WHEN excluded.description != '' THEN excluded.description ELSE graph_nodes.description END,
                            project = excluded.project
                    """, (name, d.get("entity_type", "concept"), d.get("description", ""), d.get("project", "")))
                    imported_graph += 1
                elif kind == "edge":
                    src = gl.resolve_node(d.get("source", "")) if hasattr(gl, "resolve_node") else d.get("source", "")
                    tgt = gl.resolve_node(d.get("target", "")) if hasattr(gl, "resolve_node") else d.get("target", "")
                    rel = d.get("relation", "RELATES_TO")
                    fact = d.get("fact", "")
                    proj = d.get("project", "")
                    is_active = int(d.get("is_active", 1) if d.get("is_active") is not None else 1)
                    valid_from = d.get("valid_from")
                    valid_until = d.get("valid_until")
                    superseded_by = d.get("superseded_by")
                    con.execute("""
                        INSERT INTO graph_edges (
                            source, relation, target, fact, project,
                            is_active, valid_from, valid_until, superseded_by
                        )
                        VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), ?, ?)
                        ON CONFLICT(source, relation, target, fact, project) DO UPDATE SET
                            is_active = excluded.is_active,
                            valid_until = excluded.valid_until,
                            superseded_by = excluded.superseded_by
                    """, (src, rel, tgt, fact, proj, is_active, valid_from, valid_until, superseded_by))
                    imported_graph += 1
        con.commit()
        con.close()

    return {"observations": imported_obs, "graph": imported_graph}


def deduplicate_and_compact(
    vault_dir: Path | str | None = None,
    session_db: Path | str | None = None,
    graph_db: Path | str | None = None
) -> dict[str, int]:
    """Deduplicate observations and graph edges, compacting JSONL files and rebuilding indexes.

    Rules applied:
    1. Exact hash deduplication: Discards identical content_hash / guid.
    2. Semantic deduplication: Discards duplicate (project, normalized_title, normalized_text).
    3. Noise pruning: Discards empty observations or those matching NO_SIGNAL.
    4. Graph deduplication: Unifies duplicate node variants and edge facts.
    """
    v_dir = init_vault(vault_dir)
    s_db = Path(session_db) if session_db else SESSION_DB
    g_db = Path(graph_db) if graph_db else GRAPH_DB

    # First, make sure any local SQLite records are dumped into vault
    export_dirty_to_vault(vault_dir=v_dir, session_db=s_db, graph_db=g_db)

    obs_file = v_dir / "observations.jsonl"
    graph_file = v_dir / "graph.jsonl"

    obs_before = 0
    obs_after = 0
    edges_before = 0
    edges_after = 0

    # 1. Compact observations
    if obs_file.exists():
        seen_hashes: Set[str] = set()
        seen_semantic: Dict[str, dict] = {}

        with open(obs_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                obs_before += 1
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                ch = d.get("content_hash") or d.get("guid")
                title = str(d.get("title") or "").strip()
                narrative = str(d.get("narrative") or "").strip()
                facts = str(d.get("facts") or "").strip()
                full_text = f"{narrative} {facts}".strip()
                proj = str(d.get("project") or "").strip().lower()

                # Noise pruning
                if not full_text and not title:
                    continue
                if NO_SIGNAL_PATTERN.search(full_text) or NO_SIGNAL_PATTERN.search(title):
                    continue

                # Hash dedupe
                if ch and ch in seen_hashes:
                    continue

                # Semantic key
                norm_title = re.sub(r"[^a-z0-9]", "", title.lower())
                norm_text = re.sub(r"[^a-z0-9]", "", full_text.lower())
                sem_key = f"{proj}:{norm_title}:{norm_text[:120]}"

                if sem_key in seen_semantic:
                    # Keep the one with higher information or more recent epoch
                    existing = seen_semantic[sem_key]
                    if (d.get("created_at_epoch", 0) or 0) > (existing.get("created_at_epoch", 0) or 0):
                        seen_semantic[sem_key] = d
                else:
                    seen_semantic[sem_key] = d

                if ch:
                    seen_hashes.add(ch)

        # Sort remaining observations chronologically
        compacted_obs = sorted(
            seen_semantic.values(),
            key=lambda x: x.get("created_at_epoch", 0) or 0
        )
        obs_after = len(compacted_obs)

        # Atomic rewrite of observations.jsonl
        tmp_obs = obs_file.with_suffix(".tmp")
        with open(tmp_obs, "w", encoding="utf-8") as f:
            for d in compacted_obs:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        tmp_obs.replace(obs_file)

        # Rebuild local session.db cleanly from compacted observations
        if s_db.exists():
            s_db.unlink(missing_ok=True)
            for suff in ["-wal", "-shm"]:
                Path(str(s_db) + suff).unlink(missing_ok=True)
        import_from_vault(vault_dir=v_dir, session_db=s_db, graph_db=None)

    # 2. Compact graph
    if graph_file.exists():
        seen_nodes: Dict[Tuple[str, str], dict] = {}
        seen_edges: Dict[Tuple[str, str, str, str], dict] = {}

        alias_map: Dict[str, str] = {}
        if g_db.exists():
            try:
                con_g = sqlite3.connect(f"file:{g_db}?mode=ro", uri=True)
                alias_map = {r[0].lower(): r[1].lower() for r in con_g.execute("SELECT alias, canonical_name FROM graph_aliases").fetchall()}
                con_g.close()
            except Exception:
                pass

        with open(graph_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                edges_before += 1
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                kind = d.get("kind")
                proj = str(d.get("project") or "").strip().lower()
                if kind == "node":
                    name = str(d.get("name") or "").strip()
                    canon_name = alias_map.get(name.lower(), name.lower())
                    n_key = (canon_name, proj)
                    if n_key not in seen_nodes or (d.get("description") and not seen_nodes[n_key].get("description")):
                        seen_nodes[n_key] = d
                elif kind == "edge":
                    src = str(d.get("source") or "").strip().lower()
                    rel = str(d.get("relation") or "").strip().upper()
                    tgt = str(d.get("target") or "").strip().lower()
                    canon_src = alias_map.get(src, src)
                    canon_tgt = alias_map.get(tgt, tgt)
                    e_key = (canon_src, rel, canon_tgt, proj)
                    if e_key not in seen_edges:
                        seen_edges[e_key] = d
                    else:
                        existing = seen_edges[e_key]
                        exist_active = int(existing.get("is_active", 1) if existing.get("is_active") is not None else 1)
                        new_active = int(d.get("is_active", 1) if d.get("is_active") is not None else 1)
                        if new_active > exist_active:
                            seen_edges[e_key] = d
                        elif new_active == exist_active and len(str(d.get("fact") or "")) > len(str(existing.get("fact") or "")):
                            seen_edges[e_key] = d

        compacted_graph = list(seen_nodes.values()) + list(seen_edges.values())
        edges_after = len(compacted_graph)

        tmp_graph = graph_file.with_suffix(".tmp")
        with open(tmp_graph, "w", encoding="utf-8") as f:
            for d in compacted_graph:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        tmp_graph.replace(graph_file)

        # Rebuild local graph.db cleanly from compacted graph
        if g_db.exists():
            g_db.unlink(missing_ok=True)
            for suff in ["-wal", "-shm"]:
                Path(str(g_db) + suff).unlink(missing_ok=True)
        import_from_vault(vault_dir=v_dir, session_db=None, graph_db=g_db)

    return {
        "observations_before": obs_before,
        "observations_after": obs_after,
        "observations_pruned": obs_before - obs_after,
        "graph_before": edges_before,
        "graph_after": edges_after,
        "graph_pruned": edges_before - edges_after
    }
