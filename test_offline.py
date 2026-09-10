"""Offline checks: no LLM, no network (except localhost worker for L1 live test)."""
import os
from layers.base import Hit, MemoryLayer
from recall import recall


class FakeL1(MemoryLayer):
    name = "fake-l1"

    def __init__(self, hits):
        self._hits = hits

    def search(self, query, limit=5):
        return self._hits[:limit]


class FakeL2(MemoryLayer):
    name = "fake-l2"
    calls = 0

    def search(self, query, limit=5):
        FakeL2.calls += 1
        return [Hit(text="durable fact", source=self.name)]

    def add(self, text):
        if not hasattr(self, "added"):
            self.added = []
        self.added.append(text)


# L2 skipped when L1 is sufficient
FakeL2.calls = 0
r = recall("q", FakeL1([Hit(text="a", source="x"), Hit(text="b", source="x")]),
           FakeL2())
assert len(r["recent"]) == 2 and r["durable"] == [] and FakeL2.calls == 0

# L2 fires when L1 thin, and on deep=True
FakeL2.calls = 0
r = recall("q", FakeL1([]), FakeL2())
assert len(r["durable"]) == 1 and FakeL2.calls == 1
r = recall("q", FakeL1([Hit(text="a", source="x")] * 5), FakeL2(), deep=True)
assert FakeL2.calls == 2

# L2 missing (RuntimeError) degrades gracefully
class DeadL2(MemoryLayer):
    name = "dead"
    def search(self, query, limit=5):
        raise RuntimeError("nope")
r = recall("q", FakeL1([]), DeadL2())
assert r["durable"] == []

# promote filter + dedupe with fake L2 and rank-order test on isolated mock DB
import promote
from pathlib import Path
import tempfile
import sqlite3
from layers.session_layer import SessionLayer

with tempfile.TemporaryDirectory() as tmp_dir:
    t_path = Path(tmp_dir)
    mock_db = t_path / "mock_session.db"
    con = sqlite3.connect(mock_db)
    con.execute("""CREATE TABLE observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, memory_session_id TEXT, project TEXT,
        type TEXT, title TEXT, subtitle TEXT, facts TEXT, narrative TEXT,
        concepts TEXT, files_read TEXT, files_modified TEXT, prompt_number INT,
        discovery_tokens INT, created_at TEXT, created_at_epoch INT, content_hash TEXT,
        generated_by_model TEXT, relevance_count INT, sync_rev TEXT
    )""")
    con.execute("""CREATE TABLE session_summaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT,
        learned TEXT, completed TEXT, created_at_epoch INT
    )""")
    # Seed sample observations for promote & rank tests
    for idx in range(1, 11):
        con.execute(
            "INSERT INTO observations (id, project, type, title, facts, narrative, concepts, created_at_epoch) "
            "VALUES (?, ?, 'decision', ?, ?, ?, 'pattern', ?)",
            (idx, "test-proj", f"Decision {idx}", f"Facts about decision {idx} with enough characters to count as signal", f"Narrative {idx}", 1000 + idx)
        )
    con.commit()
    con.close()

    orig_promote_db = promote.DB
    orig_promote_state = promote.STATE
    try:
        promote.DB = mock_db
        promote.STATE = t_path / "promote-test-state.json"

        cands = promote.collect()
        assert len(cands) == 10, f"Expected 10 candidates, got {len(cands)}"
        fake = FakeL2()
        fresh = promote.promote(fake)
        assert len(fresh) == len(cands) and len(getattr(fake, "added", [])) == len(cands)
        assert promote.promote(fake) == [], "second run must promote nothing"

        # promote batch limit
        promote.STATE = t_path / "promote-test-limit.json"
        fake_ltd = FakeL2()
        batch = promote.promote(fake_ltd, limit=5)
        assert len(batch) == 5 and len(fake_ltd.added) == 5, f"Expected 5 promoted, got {len(batch)}"

        # _bodies_by_id preserves rank order
        cm = SessionLayer(worker="http://127.0.0.1:99999", db_path=mock_db)
        test_ids = ["5", "2", "8"]
        h_order = cm._bodies_by_id(test_ids)
        assert [h.ref for h in h_order] == test_ids, f"Order mismatch: {[h.ref for h in h_order]} vs {test_ids}"
        rev_ids = ["8", "2", "5"]
        h_rev = cm._bodies_by_id(rev_ids)
        assert [h.ref for h in h_rev] == rev_ids, f"Reverse mismatch: {[h.ref for h in h_rev]} vs {rev_ids}"

        # test record() offline fallback to SQLite on isolated mock DB
        rec = cm.record("Test pattern offline", title="Test Pattern", project="offline-proj")
        assert rec["id"] == 11, f"Expected id 11, got {rec}"
        assert "SQLite" in rec["message"]
    finally:
        promote.DB = orig_promote_db
        promote.STATE = orig_promote_state

# test integrate.py logic
import integrate
import tempfile
import json

# test JSONC parsing
sample_jsonc = '{\n  // comment\n  "url": "https://example.com/api",\n  "num": 42\n}'
stripped = integrate.strip_jsonc_comments(sample_jsonc)
parsed = json.loads(stripped)
assert parsed["url"] == "https://example.com/api"
assert parsed["num"] == 42

# test YAML injection & removal
yaml_doc = "other_key: true\n"
injected = integrate.inject_yaml_subdict(yaml_doc, "mcp-servers", "agent-memory", [
    "agent-memory:",
    "  command: test-py",
    "  args:",
    "    - test-srv"
])
assert "mcp-servers:" in injected and "command: test-py" in injected
removed = integrate.remove_yaml_subdict(injected, "mcp-servers", "agent-memory")
assert "agent-memory:" not in removed

# test rules append & remove
with tempfile.TemporaryDirectory() as tmp_dir:
    t_path = Path(tmp_dir) / "test_rules.md"
    t_path.write_text("# Initial Header\n")
    assert integrate.append_rules_safe(t_path, "<!-- AGENT_MEMORY_DISCIPLINE_START -->\nRule\n<!-- AGENT_MEMORY_DISCIPLINE_END -->")
    assert not integrate.append_rules_safe(t_path, "Duplicate"), "Must be idempotent"
    assert "Rule" in t_path.read_text()
    assert integrate.remove_rules_safe(t_path)
    assert "Rule" not in t_path.read_text()
    assert "# Initial Header" in t_path.read_text()

# test tool registry
assert len(integrate.INTEGRATIONS) == 12
for tool in integrate.INTEGRATIONS:
    cfg_snip = tool.generate_config("python3", "mcp_server.py")
    assert "agent-memory" in cfg_snip

# test native GraphLayer
from layers.graph_layer import GraphLayer
with tempfile.TemporaryDirectory() as tmp_dir:
    g_db = Path(tmp_dir) / "graph_test.db"
    gl = GraphLayer(db_path=g_db)
    gl.add_node("ServiceA", "service", "Core API Service", project="p1")
    gl.add_node("JWT", "auth", "JSON Web Tokens", project="p1")
    gl.add_edge("ServiceA", "USES", "JWT", "ServiceA issues JWT for auth", project="p1")
    gl.add_edge("JWT", "STORED_IN", "Keystore", "JWT stored in encrypted keystore", project="p1")
    
    g_hits = gl.search("auth", limit=5)
    assert len(g_hits) >= 1, f"Expected hits for 'auth', got {g_hits}"
    assert "ServiceA" in g_hits[0].text
    
    # Test heuristic extraction via add()
    gl.add("[p1] ServiceB uses Redis for session caching")
    b_hits = gl.search("redis session", limit=5)
    assert len(b_hits) >= 1
    
    st = gl.stats()
    assert st["nodes"] >= 4 and st["edges"] >= 3

# test vault, deduplication, and sync
import vault
import sync
with tempfile.TemporaryDirectory() as tmp_dir:
    t_dir = Path(tmp_dir)
    v_dir = t_dir / "vault"
    s_db = t_dir / "test_session.db"
    g_db = t_dir / "test_graph.db"
    
    # 1. init
    vault.init_vault(v_dir)
    assert (v_dir / "observations.jsonl").exists()
    assert (v_dir / "graph.jsonl").exists()
    assert (v_dir / ".gitignore").exists()

    # 2. populate sqlite with duplicate & noisy observations
    from layers.session_layer import SessionLayer
    sl = SessionLayer(worker="http://127.0.0.1:99999", db_path=s_db)
    sl.record("Decision: use sqlite FTS5", title="FTS5", project="p1")
    sl.record("Decision: use sqlite FTS5", title="FTS5", project="p1")  # duplicate
    sl.record("no new patterns", title="None", project="p1")  # noise
    sl.record("What was decided: use sqlite FTS5 with BM25", title="FTS5 BM25", project="p1")

    # 3. populate graph
    from layers.graph_layer import GraphLayer
    gl = GraphLayer(db_path=g_db, project="p1")
    gl.add_edge("App", "CONNECTS", "DB", "App connects to SQLite DB", project="p1")
    gl.add_edge("App", "CONNECTS", "DB", "App connects to SQLite DB", project="p1")  # duplicate edge

    # 4. export & simulate incoming duplicate from remote device
    exp = vault.export_dirty_to_vault(vault_dir=v_dir, session_db=s_db, graph_db=g_db)
    assert exp["observations"] >= 2
    assert exp["graph"] >= 1

    # simulate a remote machine syncing an edge that duplicates local one
    with open(v_dir / "graph.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": "edge", "source": "App", "relation": "CONNECTS", "target": "DB", "fact": "App connects to SQLite DB", "project": "p1"}) + "\n")

    # 5. deduplicate and compact
    d_res = vault.deduplicate_and_compact(vault_dir=v_dir, session_db=s_db, graph_db=g_db)
    assert d_res["observations_pruned"] >= 1, f"Expected pruned observations, got {d_res}"
    assert d_res["graph_pruned"] >= 1, f"Expected pruned graph items, got {d_res}"

    # 6. test git sync offline with local bare remote
    remote_dir = t_dir / "remote.git"
    import subprocess
    subprocess.run(["git", "init", "--bare", str(remote_dir)], check=True, capture_output=True)
    
    sync.SYNC_CONFIG_FILE = t_dir / "sync.json"
    ok, msg = sync.setup_git_remote(str(remote_dir), vault_dir=v_dir)
    assert ok, f"Setup git remote failed: {msg}"
    
    sync_res = sync.sync(vault_dir=v_dir, push=True, pull=True)
    assert sync_res["status"] == "synced"
    assert sync_res["pushed"] is True

# 7. Test In-Flight Knowledge Graph Synthesis & Conflict Steering
with tempfile.TemporaryDirectory() as inflight_tmp:
    if_dir = Path(inflight_tmp)
    if_db = if_dir / "if_test.db"
    orig_env_db = os.environ.get("AGENT_MEMORY_DB")
    os.environ["AGENT_MEMORY_DB"] = str(if_db)
    try:
        import mcp_server
        from layers.session_layer import SessionLayer
        from layers.graph_layer import GraphLayer

        sl_if = SessionLayer(worker="http://127.0.0.1:99999", db_path=if_db, project="inflight-proj")

        # 7a. Record initial decision
        r1 = sl_if.record(
            text="Use PostgreSQL for primary database storage",
            title="Database Architecture",
            project="inflight-proj",
            category="architecture"
        )
        obs1_id = r1["id"]
        assert obs1_id is not None
        assert r1["category"] == "architecture"

        # 7b. Record similar decision without supersedes -> conflict alert detected
        r2 = sl_if.record(
            text="Use SQLite FTS5 for local search and storage engine",
            title="Database Architecture Engine",
            project="inflight-proj",
            category="architecture"
        )
        obs2_id = r2["id"]
        assert any(c["id"] == obs1_id for c in r2["conflicts"]), f"Expected conflict with #{obs1_id}, got {r2['conflicts']}"

        # 7c. Record decision explicitly superseding obs1_id
        r3 = sl_if.record(
            text="Use SQLite FTS5 exclusively; PostgreSQL is deprecated",
            title="Final DB Architecture",
            project="inflight-proj",
            category="architecture",
            supersedes=f"#{obs1_id}"
        )
        assert obs1_id in r3["superseded_ids"], f"Expected #{obs1_id} to be superseded, got {r3['superseded_ids']}"

        # 7d. Verify search ranks active decision first and tags superseded record
        hits = sl_if.search("PostgreSQL", limit=5)
        assert any("[SUPERSEDED]" in h.text for h in hits), f"Expected [SUPERSEDED] tag in hits: {[h.text for h in hits]}"

        # 7e. Test MCP memory_record with in-flight relations -> verifies L2 GraphLayer ingestion
        mcp_res = mcp_server.call_tool("memory_record", {
            "text": "Antigravity uses SQLite FTS5 for fast zero-latency local memory",
            "title": "Agent Memory Architecture",
            "project": "inflight-proj",
            "category": "architecture",
            "relations": [
                {"source": "Antigravity", "relation": "USES", "target": "SQLite FTS5", "fact": "Antigravity uses SQLite FTS5"}
            ]
        })
        assert "Added 1 relation(s) directly to L2 Knowledge Graph" in mcp_res, f"Unexpected MCP response: {mcp_res}"

        # 7f. Verify graph node and edge creation in L2
        gl_check = GraphLayer(db_path=if_db, project="inflight-proj")
        g_stats = gl_check.stats()
        assert g_stats["edges"] >= 1, f"Expected at least 1 edge in L2 graph, got {g_stats}"
        g_hits = gl_check.search("Antigravity")
        assert any("SQLite FTS5" in h.text for h in g_hits), f"Expected triple in graph search hits: {[h.text for h in g_hits]}"

    finally:
        if orig_env_db is not None:
            os.environ["AGENT_MEMORY_DB"] = orig_env_db
        else:
            os.environ.pop("AGENT_MEMORY_DB", None)

# 8. Test Phase 3: Core Memory Blocks & Phase 4: Auto Promote
with tempfile.TemporaryDirectory() as core_tmp:
    c_dir = Path(core_tmp)
    c_db = c_dir / "core_test.db"
    c_state = c_dir / "promoted.json"
    orig_env_db = os.environ.get("AGENT_MEMORY_DB")
    orig_env_state = os.environ.get("AGENT_MEMORY_STATE")
    os.environ["AGENT_MEMORY_DB"] = str(c_db)
    os.environ["AGENT_MEMORY_STATE"] = str(c_state)
    try:
        import mcp_server
        from layers.session_layer import SessionLayer
        from layers.graph_layer import GraphLayer
        import recall
        import promote

        sl_core = SessionLayer(worker="http://127.0.0.1:99999", db_path=c_db, project="p-core")

        # 8a. pin_block
        b1 = sl_core.pin_block("INVARIANT_1", "Never use external dependencies", category="system", project="global")
        assert b1["key"] == "INVARIANT_1"
        assert b1["pinned"] is True
        assert b1["project"] == "global"

        b2 = sl_core.pin_block("CONVENTION_1", "Project p-core convention", category="convention", project="p-core")
        b3 = sl_core.pin_block("OTHER_1", "Other project rule", category="rule", project="other-proj")

        # 8b. get_pinned_blocks
        pinned = sl_core.get_pinned_blocks("p-core")
        pinned_keys = [b["key"] for b in pinned]
        assert "INVARIANT_1" in pinned_keys
        assert "CONVENTION_1" in pinned_keys
        assert "OTHER_1" not in pinned_keys

        # 8c. unpin_block
        assert sl_core.unpin_block("CONVENTION_1") is True
        assert sl_core.unpin_block("NONEXISTENT") is False
        pinned_after = sl_core.get_pinned_blocks("p-core")
        assert "CONVENTION_1" not in [b["key"] for b in pinned_after]

        # 8d. list_blocks
        all_blocks = sl_core.list_blocks()
        assert len(all_blocks) == 3

        # 8e. recall.py integration
        sl_core.record("Observation about database caching", title="DB Caching", project="p-core")
        r = recall.recall("caching", sl_core)
        assert "core" in r
        assert any(b["key"] == "INVARIANT_1" for b in r["core"])

        # 8f. MCP tools
        pin_res = mcp_server.call_tool("memory_pin", {
            "key": "MCP_PIN_1",
            "content": "MCP pinned rule",
            "category": "rule",
            "project": "p-core"
        })
        assert "Pinned block [MCP_PIN_1]" in pin_res

        blocks_res = mcp_server.call_tool("memory_blocks", {"project": "p-core"})
        assert "MCP_PIN_1" in blocks_res
        assert "INVARIANT_1" in blocks_res

        # memory_recall prepends pinned blocks
        rec_res = mcp_server.call_tool("memory_recall", {"query": "caching", "project": "p-core"})
        assert "## core memory (pinned)" in rec_res
        assert "- [MCP_PIN_1] (rule): MCP pinned rule" in rec_res
        assert "## recent" in rec_res

        # memory_recall_deep prepends pinned blocks
        deep_res = mcp_server.call_tool("memory_recall_deep", {"query": "caching", "project": "p-core"})
        assert "## core memory (pinned)" in deep_res
        assert "## recent" in deep_res

        # memory_unpin
        unpin_res = mcp_server.call_tool("memory_unpin", {"key": "MCP_PIN_1"})
        assert "Unpinned block [MCP_PIN_1]" in unpin_res

        # 8g. Phase 4: auto_promote
        orig_pdb = promote.DB
        orig_pstate = promote.STATE
        try:
            promote.DB = c_db
            promote.STATE = c_state
            # Insert durable observation
            con = sqlite3.connect(c_db)
            con.execute("""
                INSERT INTO observations (
                    memory_session_id, project, type, title, subtitle, facts, narrative,
                    concepts, files_read, files_modified, prompt_number, discovery_tokens,
                    created_at, created_at_epoch, content_hash, generated_by_model, relevance_count, sync_rev
                ) VALUES (
                    'sess1', 'p-core', 'decision', 'Use FTS5', 'sub',
                    'FTS5 is chosen for fast token-efficient session recall', 'narrative',
                    'pattern,why-it-exists', '[]', '[]', 1, 0, '2026-09-10', 5000, 'hash_fts5', 'agent-memory', 0, '1'
                )
            """)
            con.commit()
            con.close()

            promoted = promote.auto_promote(limit=10, project="p-core")
            assert len(promoted) == 1
            assert "Use FTS5" in promoted[0]

            # Idempotent second run
            promoted_again = promote.auto_promote(limit=10, project="p-core")
            assert len(promoted_again) == 0
        finally:
            promote.DB = orig_pdb
            promote.STATE = orig_pstate

    finally:
        if orig_env_db is not None:
            os.environ["AGENT_MEMORY_DB"] = orig_env_db
        else:
            os.environ.pop("AGENT_MEMORY_DB", None)
        if orig_env_state is not None:
            os.environ["AGENT_MEMORY_STATE"] = orig_env_state
        else:
            os.environ.pop("AGENT_MEMORY_STATE", None)

# 9. Test Phase 1 (Bi-Temporal Graph Edges) & Phase 2 (Entity Alias & Canonicalization)
with tempfile.TemporaryDirectory() as bitemp_tmp:
    bt_dir = Path(bitemp_tmp)
    bt_db = bt_dir / "bitemp_test.db"
    bt_vault = bt_dir / "vault"

    # 9a. Test alias resolution and seeding
    gl_bt = GraphLayer(db_path=bt_db, project="p-bt")
    assert gl_bt.resolve_node("fcm") == "FirebaseCloudMessaging"
    assert gl_bt.resolve_node("FCM") == "FirebaseCloudMessaging"
    assert gl_bt.resolve_node("k8s") == "Kubernetes"
    assert gl_bt.resolve_node("jwt") == "JSONWebToken"
    assert gl_bt.resolve_node("sqlite") == "SQLite"
    assert gl_bt.resolve_node("postgres") == "PostgreSQL"
    assert gl_bt.resolve_node("postgresql") == "PostgreSQL"
    assert gl_bt.resolve_node("unknown_entity") == "unknown_entity"

    # Custom alias
    gl_bt.add_alias("gql", "GraphQL", category="api")
    assert gl_bt.resolve_node("gql") == "GraphQL"
    aliases = gl_bt.list_aliases()
    assert "gql" in aliases and aliases["gql"] == "GraphQL"
    assert "fcm" in aliases

    # 9b. Canonicalization on add_edge
    gl_bt.add_edge("fcm", "USES", "jwt", "FCM uses JWT for authorization", project="p-bt")
    con = gl_bt._get_con(mode="ro")
    edge_row = con.execute("SELECT source, target, is_active FROM graph_edges WHERE relation = 'USES'").fetchone()
    assert edge_row[0] == "FirebaseCloudMessaging", f"Expected canonical source, got {edge_row[0]}"
    assert edge_row[1] == "JSONWebToken", f"Expected canonical target, got {edge_row[1]}"
    assert edge_row[2] == 1, "Expected active edge"
    con.close()

    # 9c. Contradiction invalidation: USES vs PROHIBITS
    gl_bt.add_edge("FirebaseCloudMessaging", "PROHIBITS", "JSONWebToken", "FCM prohibits JWT; migrated to OAuth2", project="p-bt")
    con = gl_bt._get_con(mode="ro")
    cur = con.execute("SELECT relation, is_active, superseded_by FROM graph_edges WHERE source = 'FirebaseCloudMessaging' ORDER BY id ASC")
    rows = cur.fetchall()
    assert len(rows) == 2
    # First edge (USES) must be inactive and superseded_by recorded
    assert rows[0][0] == "USES" and rows[0][1] == 0
    assert "PROHIBITS" in rows[0][2]
    # Second edge (PROHIBITS) must be active
    assert rows[1][0] == "PROHIBITS" and rows[1][1] == 1
    con.close()

    # 9d. Contradiction invalidation: same relation with different fact
    gl_bt.add_edge("ServiceA", "USES", "SQLite", "ServiceA uses SQLite v3.39", project="p-bt")
    gl_bt.add_edge("ServiceA", "USES", "SQLite", "ServiceA uses SQLite v3.45 with WAL", project="p-bt")
    con = gl_bt._get_con(mode="ro")
    s_rows = con.execute("SELECT fact, is_active, superseded_by FROM graph_edges WHERE source = 'ServiceA' ORDER BY id ASC").fetchall()
    assert len(s_rows) == 2
    assert s_rows[0][1] == 0 and s_rows[0][2] is not None
    assert s_rows[1][1] == 1
    con.close()

    # 9e. Contradiction invalidation: REPLACES
    gl_bt.add_edge("PostgreSQL", "REPLACES", "SQLite", "PostgreSQL replaces SQLite for high concurrency", project="p-bt")
    con = gl_bt._get_con(mode="ro")
    rep_row = con.execute("SELECT is_active FROM graph_edges WHERE relation = 'REPLACES'").fetchone()
    assert rep_row[0] == 1
    con.close()

    # 9f. Search CTE: returns only active edges by default, returns inactive when include_inactive=True
    hits_active = gl_bt.search("FirebaseCloudMessaging", limit=5)
    assert len(hits_active) >= 1
    assert any("prohibits" in h.text.lower() for h in hits_active)
    assert not any("uses jwt for authorization" in h.text.lower() for h in hits_active), "Inactive edge must NOT appear in default search"

    hits_all = gl_bt.search("FirebaseCloudMessaging", limit=5, include_inactive=True)
    assert any("uses jwt for authorization" in h.text.lower() for h in hits_all), "Inactive edge MUST appear when include_inactive=True"

    # Alias search lookup: searching "fcm" finds "FirebaseCloudMessaging"
    hits_alias = gl_bt.search("fcm", limit=5)
    assert len(hits_alias) >= 1
    assert any("prohibits" in h.text.lower() for h in hits_alias)

    # 9g. Vault export/import retains bi-temporal fields
    vault.init_vault(bt_vault)
    exp = vault.export_dirty_to_vault(vault_dir=bt_vault, graph_db=bt_db)
    assert exp["graph"] >= 3

    # Check exported lines in graph.jsonl have bi-temporal fields
    with open(bt_vault / "graph.jsonl", "r", encoding="utf-8") as f:
        exported_edges = [json.loads(line) for line in f if json.loads(line).get("kind") == "edge"]
    assert len(exported_edges) >= 3
    has_inactive = any(e.get("is_active") == 0 and e.get("superseded_by") for e in exported_edges)
    assert has_inactive, f"Expected exported inactive edge with superseded_by: {exported_edges}"

    # Import into fresh DB and verify fields are preserved
    fresh_db = bt_dir / "fresh_graph.db"
    vault.import_from_vault(vault_dir=bt_vault, graph_db=fresh_db)
    con_fresh = sqlite3.connect(fresh_db)
    imported_rows = con_fresh.execute("SELECT source, relation, target, is_active, superseded_by FROM graph_edges WHERE is_active = 0").fetchall()
    assert len(imported_rows) >= 1, "Expected inactive edges in freshly imported DB"
    assert imported_rows[0][4] is not None
    con_fresh.close()

    # 9h. Backward compatibility PRAGMA migration check on legacy schema DB
    legacy_db = bt_dir / "legacy.db"
    con_leg = sqlite3.connect(legacy_db)
    con_leg.execute("""
        CREATE TABLE graph_edges (
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
    con_leg.execute("INSERT INTO graph_edges (source, relation, target, fact, project) VALUES ('OldSrc', 'USES', 'OldTgt', 'Legacy fact', 'legacy-proj')")
    con_leg.commit()
    con_leg.close()

    # Initializing GraphLayer on legacy_db should cleanly migrate columns
    gl_leg = GraphLayer(db_path=legacy_db, project="legacy-proj")
    con_migrated = gl_leg._get_con(mode="ro")
    leg_cols = [r[1] for r in con_migrated.execute("PRAGMA table_info(graph_edges)").fetchall()]
    assert "is_active" in leg_cols
    assert "valid_from" in leg_cols
    assert "valid_until" in leg_cols
    assert "superseded_by" in leg_cols
    leg_row = con_migrated.execute("SELECT is_active FROM graph_edges WHERE source = 'OldSrc'").fetchone()
    assert leg_row[0] == 1, "Legacy edge should default to is_active = 1"
    con_migrated.close()

# 10. Test Lifecycle Hooks System
with tempfile.TemporaryDirectory() as hook_tmp:
    h_dir = Path(hook_tmp)
    import hooks

    # 10a. Test Claude Code hook installation & uninstallation in custom scope
    claude_settings = h_dir / ".claude" / "settings.json"
    hooks.REPO_DIR = Path(__file__).resolve().parent
    orig_home = Path.home()
    
    # Test installation directly on json
    data = {"permissions": {}}
    claude_settings.parent.mkdir(parents=True, exist_ok=True)
    claude_settings.write_text(json.dumps(data), encoding="utf-8")

    # Install claude hooks in project scope (cwd set to h_dir)
    orig_cwd = os.getcwd()
    os.chdir(h_dir)
    try:
        ok, msg = hooks.install_claude_hooks(scope="project", py_path="/usr/bin/python3")
        assert ok, f"Failed to install claude hooks: {msg}"
        saved_claude = json.loads(claude_settings.read_text())
        assert "hooks" in saved_claude
        assert "SessionStart" in saved_claude["hooks"]
        assert "PreCompact" in saved_claude["hooks"]
        assert "SessionEnd" in saved_claude["hooks"]

        # Uninstall claude hooks
        ok, msg = hooks.uninstall_claude_hooks(scope="project")
        assert ok
        uninstalled_claude = json.loads(claude_settings.read_text())
        assert "SessionStart" not in uninstalled_claude.get("hooks", {})

        # 10b. Test Antigravity hook installation & uninstallation in project scope
        agy_hooks = h_dir / ".agents" / "hooks.json"
        ok, msg = hooks.install_agy_hooks(scope="project", py_path="/usr/bin/python3")
        assert ok
        saved_agy = json.loads(agy_hooks.read_text())
        assert "agent-memory" in saved_agy
        assert "PreInvocation" in saved_agy["agent-memory"]
        assert "Stop" in saved_agy["agent-memory"]

        ok, msg = hooks.uninstall_agy_hooks(scope="project")
        assert ok
        uninstalled_agy = json.loads(agy_hooks.read_text())
        assert "agent-memory" not in uninstalled_agy

        # 10c. Test Git hooks installation & uninstallation
        subprocess.run(["git", "init"], cwd=str(h_dir), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ok, msg = hooks.install_git_hooks(target_dir=h_dir, py_path="/usr/bin/python3")
        assert ok
        assert (h_dir / ".git" / "hooks" / "pre-commit").exists()
        assert (h_dir / ".git" / "hooks" / "post-commit").exists()
        assert (h_dir / ".git" / "hooks" / "pre-push").exists()

        ok, msg = hooks.uninstall_git_hooks(target_dir=h_dir)
        assert ok
        assert not (h_dir / ".git" / "hooks" / "pre-commit").exists()

        # 10d. Test session-start output formatting
        import io
        from contextlib import redirect_stdout
        f_out = io.StringIO()
        with redirect_stdout(f_out):
            hooks.hook_session_start(project="test-proj")
        out_str = f_out.getvalue()
        # session-start runs without error (may be empty if no memories for test-proj)
        assert isinstance(out_str, str)

    finally:
        os.chdir(orig_cwd)

print("layers OK")
print("integrate tests OK")
print("graph tests OK")
print("vault tests OK")
print("sync tests OK")
print("inflight memory synthesis OK")
print("core memory blocks OK")
print("auto promote OK")
print("bi-temporal graph and canonicalization OK")
print("lifecycle hooks OK")
