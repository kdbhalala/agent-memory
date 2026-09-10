"""Offline checks: no LLM, no network (except localhost worker for L1 live test)."""
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

# promote filter + dedupe with fake L2 (state redirected to /tmp)
import promote
from pathlib import Path
promote.STATE = Path("/tmp/promote-test-state.json")
if promote.STATE.exists():
    promote.STATE.unlink()
cands = promote.collect()
print(f"collect candidates from real DB: {len(cands)}")
fake = FakeL2()
fresh = promote.promote(fake)
assert len(fresh) == len(cands) and len(getattr(fake, "added", [])) == len(cands)
assert promote.promote(fake) == [], "second run must promote nothing"

# promote batch limit
promote.STATE = Path("/tmp/promote-test-limit.json")
if promote.STATE.exists():
    promote.STATE.unlink()
fake_ltd = FakeL2()
batch = promote.promote(fake_ltd, limit=5)
assert len(batch) == 5 and len(fake_ltd.added) == 5, f"Expected 5 promoted, got {len(batch)}"

# _bodies_by_id preserves rank order
from layers.session_layer import SessionLayer
cm = SessionLayer()
test_ids = ["13891", "13791"]
h_order = cm._bodies_by_id(test_ids)
assert [h.ref for h in h_order] == test_ids, f"Order mismatch: {[h.ref for h in h_order]} vs {test_ids}"
rev_ids = ["13791", "13891"]
h_rev = cm._bodies_by_id(rev_ids)
# test record() offline fallback to SQLite on isolated mock DB
import tempfile
import sqlite3
with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
    tmp_db = Path(tmp.name)
    con = sqlite3.connect(tmp_db)
    con.execute("""CREATE TABLE observations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, memory_session_id TEXT, project TEXT,
        type TEXT, title TEXT, subtitle TEXT, facts TEXT, narrative TEXT,
        concepts TEXT, files_read TEXT, files_modified TEXT, prompt_number INT,
        discovery_tokens INT, created_at TEXT, created_at_epoch INT, content_hash TEXT,
        generated_by_model TEXT, relevance_count INT, sync_rev TEXT
    )""")
    con.close()
    import layers.session_layer
    orig_db = layers.session_layer.DB
    layers.session_layer.DB = tmp_db
    mock_cm = SessionLayer(worker="http://127.0.0.1:99999")  # dead worker port forces SQLite
    rec = mock_cm.record("Test pattern offline", title="Test Pattern", project="offline-proj")
    assert rec["id"] == 1, f"Expected id 1, got {rec}"
    assert "SQLite" in rec["message"]
    layers.session_layer.DB = orig_db

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
with tempfile.NamedTemporaryFile(suffix=".md") as tmp:
    t_path = Path(tmp.name)
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

print("layers OK")
print("integrate tests OK")
print("graph tests OK")
print("vault tests OK")
print("sync tests OK")
