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

print("layers OK")
print("integrate tests OK")
print("graph tests OK")
print("vault tests OK")
print("sync tests OK")
print("inflight memory synthesis OK")
