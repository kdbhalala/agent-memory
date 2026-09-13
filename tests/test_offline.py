"""Offline checks: no LLM, no network (except localhost worker for L1 live test)."""
import os
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agi_memory.layers.base import Hit, MemoryLayer
from agi_memory.recall import recall


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
from agi_memory import promote
from pathlib import Path
import tempfile
import sqlite3
from agi_memory.layers.session_layer import SessionLayer

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
from agi_memory import integrate
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
assert len(integrate.INTEGRATIONS) == 13
for tool in integrate.INTEGRATIONS:
    cfg_snip = tool.generate_config("python3", "mcp_server.py")
    assert "agent-memory" in cfg_snip

# tool locations are resolved (env override > existing convention > default),
# never hardcoded to one machine's layout
_env_overrides = {
    "claude": "CLAUDE_CONFIG_DIR", "cursor": "CURSOR_CONFIG_DIR", "codex": "CODEX_HOME",
    "opencode": "OPENCODE_CONFIG_DIR", "goose": "GOOSE_CONFIG_DIR", "crush": "CRUSH_CONFIG_DIR",
    "pi": "PI_HOME", "hermes": "HERMES_HOME", "windsurf": "WINDSURF_CONFIG_DIR",
    "agy": "GEMINI_CONFIG_DIR",
}
with tempfile.TemporaryDirectory() as tmp_dir:
    fake_home = str(Path(tmp_dir) / "toolhome")
    for tname, env_var in _env_overrides.items():
        tool = integrate.INTEGRATION_MAP[tname]
        base_cfg = str(tool.get_config_path("user"))
        os.environ[env_var] = fake_home
        try:
            moved_cfg = str(tool.get_config_path("user"))
            assert moved_cfg.startswith(fake_home), f"{tname}: {env_var} ignored -> {moved_cfg}"
            assert moved_cfg != base_cfg, f"{tname}: config path did not move"
            rules = tool.get_rules_path("user")
            if rules is not None and str(rules).startswith(str(Path.home())) and tname != "claude":
                pass  # project-scope-only rules files legitimately stay outside the tool home
        finally:
            del os.environ[env_var]
        assert str(tool.get_config_path("user")) == base_cfg, f"{tname}: env leak"

import re as _re_mod
# The shared stemmer's failure mode is over-stripping: a stem so short it
# behaves as a wildcard and drags unrelated memories into a fallback search.
from agi_memory.layers.base import stem_word as _stem, stem_terms as _stems
for _a, _b in [("authenticate", "authentication"), ("caching", "cached"),
               ("retrying", "retry"), ("configure", "configuration"),
               ("normalize", "normalized"), ("deploying", "deployed")]:
    _sa, _sb = _stem(_a), _stem(_b)
    assert _sa.startswith(_sb) or _sb.startswith(_sa), f"{_a}/{_b} -> {_sa}/{_sb}"
for _w in ("api", "id", "db", "ci", "os", "cache", "user"):
    assert len(_stem(_w)) >= min(len(_w), 4), f"over-stripped {_w} -> {_stem(_w)}"
# distinct concepts must not collapse into one stem
assert _stem("authorization") != _stem("authentication"), "auth* concepts collapsed"
assert _stem("deployment") != _stem("dependency"), "unrelated words collapsed"
# stems that equal their source add nothing and are dropped
assert "retry" not in _stems(["retry"]) or _stem("retry") != "retry"

# A miss must be legible. "(no hits)" let an agent read an empty result as
# "no such decision exists" and re-decide something already settled.
# Runs against an isolated store so it never depends on the developer's vault.
with tempfile.TemporaryDirectory() as tmp_dir:
    _prev_db = os.environ.get("AGI_MEMORY_DB")
    os.environ["AGI_MEMORY_DB"] = str(Path(tmp_dir) / "miss.db")
    try:
        import importlib
        from agi_memory import config as _cfg, mcp_server as _mcp
        importlib.reload(_cfg)
        importlib.reload(_mcp)
        _empty = _mcp.call_tool("memory_recall", {"query": "anything", "project": "empty-proj"})
        assert "no memories stored yet" in _empty, _empty[:140]
        assert "empty store" in _empty, "must distinguish an empty store from a miss"

        _mcp.call_tool("memory_record", {"text": "We chose SQLite FTS5 for working memory.",
                                         "title": "Storage", "project": "miss-proj"})
        _miss = _mcp.call_tool("memory_recall",
                               {"query": "kubernetes ingress", "project": "miss-proj"})
        assert "no match" in _miss, _miss[:140]
        assert "not proof" in _miss, "a miss must not read as proof of absence"
        assert _empty != _miss, "empty store and miss must not be indistinguishable"
    finally:
        if _prev_db is None:
            os.environ.pop("AGI_MEMORY_DB", None)
        else:
            os.environ["AGI_MEMORY_DB"] = _prev_db
        importlib.reload(_cfg)
        importlib.reload(_mcp)

# Two machines both recording between syncs must converge, not diverge.
# Before the union merge policy this produced a rebase conflict that sync()
# aborted and mislabelled "pull_offline", leaving both vaults permanently
# out of step with no error surfaced.
import subprocess as _sp
from agi_memory.sync import ensure_merge_attributes as _ensure_attrs
def _git(*a, cwd):
    return _sp.run(["git", *a], cwd=cwd, capture_output=True, text=True)
with tempfile.TemporaryDirectory() as tmp_dir:
    _base = Path(tmp_dir)
    _remote = _base / "remote.git"
    _git("init", "-q", "--bare", str(_remote), cwd=_base)
    for _m in ("m1", "m2"):
        _sp.run(["git", "clone", "-q", str(_remote), str(_base / _m)], capture_output=True)
        _git("config", "user.email", "t@t", cwd=_base / _m)
        _git("config", "user.name", "t", cwd=_base / _m)
    _d1 = _base / "m1"
    assert _ensure_attrs(_d1), "merge attributes not installed"
    assert "merge=union" in (_d1 / ".gitattributes").read_text()
    (_d1 / "observations.jsonl").write_text('{"id": 1}\n')
    _git("add", "-A", cwd=_d1); _git("commit", "-qm", "init", cwd=_d1)
    _git("push", "-q", "origin", "HEAD:main", cwd=_d1)
    _git("fetch", "-q", "origin", cwd=_base / "m2")
    _git("checkout", "-qB", "main", "origin/main", cwd=_base / "m2")
    for _m, _line in (("m1", '{"id": 2}'), ("m2", '{"id": 3}')):
        _f = _base / _m / "observations.jsonl"
        _f.write_text(_f.read_text() + _line + "\n")
        _git("add", "-A", cwd=_base / _m); _git("commit", "-qm", _m, cwd=_base / _m)
    _git("push", "-q", "origin", "HEAD:main", cwd=_base / "m1")
    _pull = _git("pull", "--rebase", "origin", "main", cwd=_base / "m2")
    assert _pull.returncode == 0, f"concurrent vault writes still conflict: {_pull.stderr[-160:]}"
    assert _git("push", "origin", "HEAD:main", cwd=_base / "m2").returncode == 0, "push rejected"
    _git("pull", "-q", "--rebase", "origin", "main", cwd=_base / "m1")
    _lines1 = (_base / "m1" / "observations.jsonl").read_text().splitlines()
    _lines2 = (_base / "m2" / "observations.jsonl").read_text().splitlines()
    assert sorted(_lines1) == sorted(_lines2) == ['{"id": 1}', '{"id": 2}', '{"id": 3}'], \
        f"vaults diverged: {_lines1} vs {_lines2}"

# Homebrew formulae must track the packaged version. They shipped a v0.2.0
# sha256 against a v0.4.0 tarball for two releases because nothing checked.
_pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
_pkg_version = _re_mod.search(r'^version\s*=\s*"([^"]+)"', _pyproject, _re_mod.M).group(1)
for _formula in sorted((Path(__file__).resolve().parent.parent / "Formula").glob("*.rb")):
    _text = _formula.read_text(encoding="utf-8")
    assert f"tags/v{_pkg_version}.tar.gz" in _text, \
        f"{_formula.name} does not point at v{_pkg_version}; run packaging/update_formula.py"
    assert _re_mod.search(rf'assert_match "[a-z-]+ {_re_mod.escape(_pkg_version)}"', _text), \
        f"{_formula.name} version assertion is stale; run packaging/update_formula.py"
    _sha = _re_mod.search(r'sha256 "([0-9a-f]{64})"', _text)
    assert _sha, f"{_formula.name} has no sha256"

# an existing database built with the old tokenizer must be migrated on open,
# or every upgraded user keeps querying the old index and never sees the fix
with tempfile.TemporaryDirectory() as tmp_dir:
    from agi_memory.layers.session_layer import SessionLayer as _SL
    _db = Path(tmp_dir) / "mig.db"
    _l1 = _SL(db_path=_db, project="migproj")
    _l1.record("Migrated authentication to short-lived JWT tokens.", title="Auth", project="migproj")
    _con = sqlite3.connect(_db)
    _con.execute("DROP TABLE observations_fts")
    _con.execute("""CREATE VIRTUAL TABLE observations_fts USING fts5(
        title, subtitle, facts, narrative, concepts,
        content='observations', content_rowid='id', tokenize='unicode61')""")
    _con.execute("INSERT INTO observations_fts(observations_fts) VALUES('rebuild')")
    _con.commit()
    _con.close()
    _l2 = _SL(db_path=_db, project="migproj")   # construction must migrate
    _con = sqlite3.connect(_db)
    _sql = _con.execute("SELECT sql FROM sqlite_master WHERE name='observations_fts'").fetchone()[0]
    _rows = _con.execute("SELECT count(*) FROM observations_fts").fetchone()[0]
    _con.close()
    assert "porter" in _sql, f"FTS index not migrated to stemming tokenizer: {_sql}"
    assert _rows == 1, f"rebuilt index not repopulated: {_rows} rows"
    assert _l2.search("authentication", limit=3), "exact term lost after migration"
    assert _l2.search("authenticate", limit=3), "stemming not active after migration"

# identifier folding is a FALLBACK for the code graph: it must bridge naming
# conventions without ever outranking an exact symbol match
from agi_memory.layers.code_layer import fold_identifier as _fold
assert _fold("getUserById") == _fold("get_user_by_id") == _fold("get-user-by-id") == "getuserbyid"
assert _fold("AuthService") != _fold("authservices")

# code graph paths are stored POSIX-style so an index built on Windows answers
# the same "src/foo.py" query as one built on Linux, and either separator works
with tempfile.TemporaryDirectory() as tmp_dir:
    _repo = Path(tmp_dir) / "r"
    (_repo / "pkg").mkdir(parents=True)
    (_repo / "pkg" / "mod.py").write_text("def alpha():\n    return 1\n")
    from agi_memory.layers.code_layer import CodeLayer as _CL
    _cl = _CL(db_path=Path(tmp_dir) / "cg.db", project="pathproj")
    _cl.index_directory(_repo, project="pathproj")
    _all = _cl.get_structure(".", project="pathproj")
    assert _all, "nothing indexed"
    for _row in _all:
        assert "\\" not in _row["file_path"], f"non-posix path stored: {_row['file_path']}"
    assert _cl.get_structure("pkg/mod.py", project="pathproj"), "posix path lookup failed"
    assert _cl.get_structure("pkg\\mod.py", project="pathproj"), "windows path lookup failed"

# the code parser must survive input no version of ast agrees on:
# NUL bytes are a ValueError on 3.10 and a SyntaxError from 3.12 on
import ast as _ast
from agi_memory.layers import code_layer as _cl
assert _cl.parse_source_code("x = 1\x00\x00", "a.py", "python") == ([], [])
_orig_parse = _ast.parse
def _raise_valueerror(*_a, **_k):
    raise ValueError("source code string cannot contain null bytes")
_ast.parse = _raise_valueerror
try:  # simulate the 3.10 behaviour on any interpreter
    assert _cl.parse_source_code("x = 1\x00", "a.py", "python") == ([], [])
finally:
    _ast.parse = _orig_parse
assert len(_cl.parse_source_code("def f():\n    pass\n", "a.py", "python")[0]) == 1

# every layer connection is WAL + busy_timeout, or concurrent agents lose writes
from agi_memory.layers.base import open_db, BUSY_TIMEOUT_S
assert BUSY_TIMEOUT_S >= 5, BUSY_TIMEOUT_S
with tempfile.TemporaryDirectory() as tmp_dir:
    _db = Path(tmp_dir) / "wal.db"
    _con = open_db(_db)
    assert _con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert _con.execute("PRAGMA busy_timeout").fetchone()[0] == int(BUSY_TIMEOUT_S * 1000)
    _con.execute("CREATE TABLE t(x)")
    _con.commit()
    _con.close()
    # readonly connections must carry the timeout too
    _ro = open_db(_db, readonly=True)
    assert _ro.execute("PRAGMA busy_timeout").fetchone()[0] == int(BUSY_TIMEOUT_S * 1000)
    _ro.close()
# no layer may bypass the helper with a bare sqlite3.connect
_src_root = Path(__file__).resolve().parent.parent / "src" / "agi_memory"
for _f in list((_src_root / "layers").glob("*.py")) + [_src_root / "vault.py"]:
    if _f.name == "base.py":
        continue
    # A throwaway :memory: database is exempt: it is never shared between
    # processes, so WAL and busy_timeout are meaningless for it. Every
    # connection to a real file must still go through open_db().
    _direct = [ln for ln in _f.read_text(encoding="utf-8").splitlines()
               if "sqlite3.connect(" in ln and '":memory:"' not in ln]
    assert not _direct, \
        f"{_f.name} opens a file-backed SQLite connection directly; use open_db() " \
        f"so WAL/busy_timeout apply: {_direct[0].strip()}"

# analyze reads real project facts, never placeholder prose
from agi_memory import analyze as _an
from agi_memory import init_command as _ic
with tempfile.TemporaryDirectory() as tmp_dir:
    proj = Path(tmp_dir) / "svc"
    (proj / "src" / "__tests__").mkdir(parents=True)
    (proj / "migrations").mkdir()
    (proj / "package.json").write_text(
        '{"name":"billing-svc","scripts":{"build":"tsc","test":"vitest run","dev":"vite"}}')
    (proj / "pnpm-lock.yaml").write_text("")
    (proj / "src" / "app.ts").write_text("export const a = 1\n")
    (proj / "src" / "__tests__" / "app.test.ts").write_text("test('a',()=>{})\n")
    (proj / "migrations" / "001.sql").write_text("CREATE TABLE t(id int);\n")
    (proj / "README.md").write_text("# Billing\n\nUsage metering and invoicing.\n")
    facts = _an.analyze_project(proj)
    assert facts["name"] == "billing-svc", facts["name"]
    assert facts["package_manager"] == "pnpm", facts["package_manager"]
    assert "pnpm run test" in facts["test_commands"], facts["test_commands"]
    assert "pnpm run build" in facts["build_commands"], facts["build_commands"]
    assert "pnpm run dev" in facts["run_commands"], facts["run_commands"]
    assert ("TypeScript", 2) in facts["languages"], facts["languages"]
    assert any("__tests__" in t for t in facts["test_layout"]), facts["test_layout"]
    assert any("SQL DDL" in s_ for s_ in facts["schema_surfaces"]), facts["schema_surfaces"]

# an empty directory must degrade honestly, not invent facts
with tempfile.TemporaryDirectory() as tmp_dir:
    bare = _an.analyze_project(Path(tmp_dir))
    assert bare["languages"] == [] and bare["test_commands"] == []
    assert "Not detected" in _an.render_architecture(bare)

# /agi-init renders in every assistant's own command format
try:
    import tomllib  # 3.11+; the TOML parse check is skipped on 3.10
except ModuleNotFoundError:
    tomllib = None
for _fmt in _ic.RENDERERS:
    _out = _ic.render(_fmt, project="billing-svc")
    assert "rules/architecture.md" in _out and "<project>" not in _out, _fmt
if tomllib is not None:
    _toml_cmd = tomllib.loads(_ic.render("toml", "billing-svc"))
    assert "{{args}}" in _toml_cmd["prompt"] and _toml_cmd["description"], _toml_cmd
with tempfile.TemporaryDirectory() as tmp_dir:
    res = _ic.install_init_command(tmp_dir, project="billing-svc")
    assert len(res) == len(_ic.PROJECT_TARGETS) >= 9, res
    assert all(v.startswith("written") for v in res.values()), res
    # every emitted command file must land where that tool actually looks
    for _label, _rel, _f in _ic.PROJECT_TARGETS:
        assert (Path(tmp_dir) / _rel).is_file(), _rel
    assert all(v.startswith("skipped") for v in
               _ic.install_init_command(tmp_dir, project="billing-svc").values())

# scaffold is gone; init replaces it
assert not hasattr(integrate, "cmd_scaffold"), "cmd_scaffold should be removed"
assert hasattr(integrate, "cmd_init"), "cmd_init missing"

# XDG_CONFIG_HOME relocates XDG-convention tools (path shape differs per OS)
with tempfile.TemporaryDirectory() as tmp_dir:
    _xdg = Path(tmp_dir) / "xdg"
    os.environ["XDG_CONFIG_HOME"] = str(_xdg)
    try:
        for _tname in ("goose", "crush"):
            _cfg = integrate.INTEGRATION_MAP[_tname].get_config_path("user")
            assert _xdg in _cfg.parents, f"{_tname}: XDG_CONFIG_HOME ignored -> {_cfg}"
    finally:
        del os.environ["XDG_CONFIG_HOME"]

# test native GraphLayer
from agi_memory.layers.graph_layer import GraphLayer
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
from agi_memory import vault
from agi_memory import sync
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
    from agi_memory.layers.session_layer import SessionLayer
    sl = SessionLayer(worker="http://127.0.0.1:99999", db_path=s_db)
    sl.record("Decision: use sqlite FTS5", title="FTS5", project="p1")
    sl.record("Decision: use sqlite FTS5", title="FTS5", project="p1")  # duplicate
    sl.record("no new patterns", title="None", project="p1")  # noise
    sl.record("What was decided: use sqlite FTS5 with BM25", title="FTS5 BM25", project="p1")

    # 3. populate graph
    from agi_memory.layers.graph_layer import GraphLayer
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
        from agi_memory import mcp_server
        from agi_memory.layers.session_layer import SessionLayer
        from agi_memory.layers.graph_layer import GraphLayer

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
        from agi_memory import mcp_server
        from agi_memory.layers.session_layer import SessionLayer
        from agi_memory.layers.graph_layer import GraphLayer
        from agi_memory import recall
        from agi_memory import promote

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
    exp = vault.export_dirty_to_vault(vault_dir=bt_vault, session_db=bt_dir / "session.db", graph_db=bt_db)
    assert exp["graph"] >= 3

    # Check exported lines in graph.jsonl have bi-temporal fields
    with open(bt_vault / "graph.jsonl", "r", encoding="utf-8") as f:
        exported_edges = [json.loads(line) for line in f if json.loads(line).get("kind") == "edge"]
    assert len(exported_edges) >= 3
    has_inactive = any(e.get("is_active") == 0 and e.get("superseded_by") for e in exported_edges)
    assert has_inactive, f"Expected exported inactive edge with superseded_by: {exported_edges}"

    # Import into fresh DB and verify fields are preserved
    fresh_db = bt_dir / "fresh_graph.db"
    fresh_session_db = bt_dir / "fresh_session.db"
    vault.import_from_vault(vault_dir=bt_vault, session_db=fresh_session_db, graph_db=fresh_db)
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
    from agi_memory import hooks

    # 10a. Test Claude Code hook installation & uninstallation in custom scope
    claude_settings = h_dir / ".claude" / "settings.json"
    hooks.REPO_DIR = Path(__file__).resolve().parent.parent / "src" / "agi_memory"
    orig_home = Path.home()
    
    # Test installation directly on json with legacy permission format
    data = {"permissions": {"allow": ["mcp:agent-memory:*", "bash:*"]}}
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
        # Verify permissions allow rules were sanitized
        allow_rules = saved_claude.get("permissions", {}).get("allow", [])
        assert "mcp__agent-memory__*" in allow_rules
        assert "mcp__agi-memory__*" in allow_rules
        assert "mcp:agent-memory:*" not in allow_rules
        assert "bash:*" in allow_rules

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

# 11. Test Modularity, Config SSoT, and Event Listener Decoupling
with tempfile.TemporaryDirectory() as mod_tmp:
    m_dir = Path(mod_tmp)
    m_db = m_dir / "mod_test.db"
    m_vault = m_dir / "mod_vault"

    from agi_memory import config
    assert hasattr(config, "DATA_DIR")
    assert hasattr(config, "VAULT_DIR")
    assert hasattr(config, "DEFAULT_DB")
    assert hasattr(config, "get_default_db")
    assert hasattr(config, "get_vault_dir")

    # Verify layers source code contains no imports of vault or sync
    import inspect
    import agi_memory.layers.session_layer as sl_mod
    import agi_memory.layers.graph_layer as gl_mod

    sl_src = inspect.getsource(sl_mod)
    gl_src = inspect.getsource(gl_mod)
    assert "import vault" not in sl_src and "from vault" not in sl_src, "session_layer must not import vault"
    assert "import sync" not in sl_src and "from sync" not in sl_src, "session_layer must not import sync"
    assert "import vault" not in gl_src and "from vault" not in gl_src, "graph_layer must not import vault"
    assert "import sync" not in gl_src and "from sync" not in gl_src, "graph_layer must not import sync"

    # Test SessionLayer on_record callback and listeners
    from agi_memory.layers.session_layer import SessionLayer, add_record_listener, remove_record_listener
    rec_events = []
    global_events = []

    def test_listener(payload: dict) -> None:
        global_events.append(payload)

    add_record_listener(test_listener)
    sl = SessionLayer(db_path=m_db, on_record=lambda p: rec_events.append(p))
    res = sl.record("Modularity test observation", title="Mod Title", project="mod-proj")
    assert len(rec_events) == 1
    assert rec_events[0]["title"] == "Mod Title"
    assert rec_events[0]["id"] == res["id"]
    assert len(global_events) == 1

    remove_record_listener(test_listener)
    sl.record("Second observation after remove", title="Mod Title 2", project="mod-proj")
    assert len(global_events) == 1  # Unregistered listener not called

    # Test GraphLayer on_edge callback and listeners
    from agi_memory.layers.graph_layer import GraphLayer, add_edge_listener, remove_edge_listener
    edge_events = []
    global_edges = []

    def test_edge_listener(payload: dict) -> None:
        global_edges.append(payload)

    add_edge_listener(test_edge_listener)
    gl = GraphLayer(db_path=m_db, on_edge=lambda p: edge_events.append(p))
    gl.add_edge("ModA", "CONNECTS", "ModB", "ModA connects to ModB", project="mod-proj")
    assert len(edge_events) == 1
    assert edge_events[0]["source"] == "ModA"
    assert len(global_edges) == 1

    remove_edge_listener(test_edge_listener)
    gl.add_edge("ModB", "CONNECTS", "ModC", "ModB connects to ModC", project="mod-proj")
    assert len(global_edges) == 1  # Unregistered listener not called

# 12. Test Cold-Start Bootstrap, Observation Inspection/Deletion, and Observability CLI
with tempfile.TemporaryDirectory() as boot_tmp:
    b_dir = Path(boot_tmp)
    b_db = b_dir / "boot_test.db"

    # Setup dummy project with README and git repo
    proj_dir = b_dir / "sample_app"
    proj_dir.mkdir()
    (proj_dir / "pyproject.toml").write_text('[project]\nname = "sample-agent-app"\nversion = "0.1.0"\n')
    (proj_dir / "README.md").write_text("# Sample Agent App\n\nHigh-performance zero-dependency coding assistant.\n\n## Architecture\nUses SQLite FTS5 for L1 and recursive CTEs for L2.\n")

    # Initialize git repo with commits
    import subprocess
    subprocess.run(["git", "init"], cwd=proj_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=proj_dir, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=proj_dir, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=proj_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "feat: initial commit with README"], cwd=proj_dir, capture_output=True, check=True)

    # Second commit (bugfix)
    (proj_dir / "fix.txt").write_text("fix")
    subprocess.run(["git", "add", "."], cwd=proj_dir, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "fix: resolve memory leak in worker\n\nDetailed fix explanation."], cwd=proj_dir, capture_output=True, check=True)

    # Test bootstrap module
    from agi_memory import bootstrap
    detected_name = bootstrap.detect_project_name(proj_dir)
    assert detected_name == "sample-agent-app"

    readme_info = bootstrap.extract_readme_context(proj_dir)
    assert readme_info is not None
    assert "Sample Agent App" in readme_info["title"]
    assert readme_info["category"] == "architecture"

    commits = bootstrap.extract_git_commits(proj_dir, max_commits=10)
    assert len(commits) == 2
    assert any(c["category"] == "bugfix" for c in commits)
    assert any(c["category"] == "decision" for c in commits)

    # Run bootstrap_project
    res1 = bootstrap.bootstrap_project(repo_dir=proj_dir, max_commits=10, db_path=b_db)
    assert res1["project"] == "sample-agent-app"
    assert res1["created_count"] == 3  # 1 README + 2 commits
    assert res1["readme_bootstrapped"] is True
    assert res1["commits_bootstrapped"] == 2

    # Verify idempotency
    res2 = bootstrap.bootstrap_project(repo_dir=proj_dir, max_commits=10, db_path=b_db)
    assert res2["created_count"] == 0

    # Test SessionLayer inspection and deletion APIs
    sl_boot = SessionLayer(project="sample-agent-app", db_path=b_db)
    all_obs = sl_boot.list_observations(limit=10, project="sample-agent-app")
    assert len(all_obs) == 3

    # Inspect single observation
    first_id = all_obs[0]["id"]
    obs_detail = sl_boot.get_observation(first_id)
    assert obs_detail is not None
    assert obs_detail["id"] == first_id
    assert obs_detail["project"] == "sample-agent-app"
    assert "facts" in obs_detail
    assert "narrative" in obs_detail

    assert sl_boot.get_observation(999999) is None

    # Test soft delete
    del_id = all_obs[-1]["id"]
    ok_soft = sl_boot.delete_observation(del_id, hard=False)
    assert ok_soft is True
    remaining = sl_boot.list_observations(limit=10, project="sample-agent-app")
    assert len(remaining) == 2  # Soft deleted item excluded from default list
    all_incl = sl_boot.list_observations(limit=10, project="sample-agent-app", include_superseded=True)
    assert len(all_incl) == 3

    # Test hard delete
    ok_hard = sl_boot.delete_observation(del_id, hard=True)
    assert ok_hard is True
    all_after_hard = sl_boot.list_observations(limit=10, project="sample-agent-app", include_superseded=True)
    assert len(all_after_hard) == 2

    # Test mcp_server memory_bootstrap tool
    from agi_memory import mcp_server
    # Test call_tool memory_bootstrap
    tool_out = mcp_server.call_tool("memory_bootstrap", {"repo": str(proj_dir)})
    assert isinstance(tool_out, str)

    # Test mcp_server CLI handlers
    mcp_server.cmd_log(["--limit", "5", "--project", "sample-agent-app"])
    mcp_server.cmd_inspect([str(first_id)])
    mcp_server.cmd_pin(["test_invariant", "Never use external dependencies", "--project", "sample-agent-app"])
    mcp_server.cmd_blocks(["--project", "sample-agent-app"])
    mcp_server.cmd_unpin(["test_invariant"])
    mcp_server.cmd_delete([str(first_id)])

    # ========================================================================
    # EpisodicLayer (L3: Session Lifecycle, Timelines, Touched Files) Tests
    # ========================================================================
    from agi_memory.layers.episodic_layer import EpisodicLayer
    ep_db = t_path / "test_episodic.db"
    os.environ["AGI_MEMORY_DB"] = str(ep_db)
    ep = EpisodicLayer(db_path=ep_db, project="sample-agent-app")

    # 1. Start session
    s1 = ep.start_session(goal="Build zero-dependency code graph", branch="feature-cg", head="a1b2c3d")
    assert s1["session_id"].startswith("sess_")
    assert s1["project"] == "sample-agent-app"
    assert s1["status"] == "active"
    sid = s1["session_id"]

    # 2. Record events
    ep.record_event(sid, "edit", "Edited code_layer.py", details="src/agi_memory/layers/code_layer.py")
    ep.record_event(sid, "commit", "Commit e4f5g6h: add AST parser", details={"hash": "e4f5g6h"})

    # 3. End session
    ended = ep.end_session(sid, summary="Successfully completed code graph implementation", cwd=t_path)
    assert ended is not None
    assert ended["status"] == "completed"
    assert ended["duration_seconds"] >= 1.0
    assert "src/agi_memory/layers/code_layer.py" in ended["touched_files"]
    assert "e4f5g6h" in ended["commits"]

    # 4. Timeline & Recap
    timeline = ep.get_timeline(project="sample-agent-app", limit=5)
    assert len(timeline) == 1
    assert timeline[0]["session_id"] == sid

    last_s = ep.get_last_session(project="sample-agent-app")
    assert last_s is not None
    assert last_s["session_id"] == sid

    recap_str = EpisodicLayer.format_recap(last_s)
    assert "Build zero-dependency code graph" in recap_str
    assert "code_layer.py" in recap_str

    tl_str = EpisodicLayer.format_timeline(timeline)
    assert sid in tl_str

    # 5. Search episodic
    ep_hits = ep.search("code graph", limit=5)
    assert len(ep_hits) == 1
    assert ep_hits[0].ref == sid

    # 6. MCP & CLI for episodic
    mcp_tl_out = mcp_server.call_tool("memory_timeline", {"project": "sample-agent-app"})
    assert sid in mcp_tl_out
    mcp_sess_out = mcp_server.call_tool("memory_timeline", {"project": "sample-agent-app", "session_id": sid})
    assert "Session Events" in mcp_sess_out
    mcp_server.cmd_timeline(["--project", "sample-agent-app", "--limit", "3"])

    # ========================================================================
    # CodeLayer (L4: Structural Code Graph, AST, Callers, Impact) Tests
    # ========================================================================
    from agi_memory.layers.code_layer import CodeLayer, parse_source_code
    code_db = t_path / "test_code.db"
    os.environ["AGI_MEMORY_DB"] = str(code_db)
    cl = CodeLayer(db_path=code_db, project="sample-agent-app")

    # Test Python AST parser
    py_code = '''
"""Sample module for AST testing."""
import os
from math import sqrt

class BaseService:
    def execute(self) -> bool:
        return True

class AuthService(BaseService):
    """Handles authentication logic."""
    def __init__(self, secret: str):
        self.secret = secret

    def authenticate(self, token: str) -> bool:
        return self.verify_token(token)

    def verify_token(self, token: str) -> bool:
        return len(token) > 5
'''
    py_syms, py_edges = parse_source_code(py_code, "auth_service.py", "python")
    sym_names = {s["name"] for s in py_syms}
    assert "BaseService" in sym_names
    assert "AuthService" in sym_names
    assert "authenticate" in sym_names
    assert "verify_token" in sym_names
    # Check inheritance edge
    extends_edges = [e for e in py_edges if e["relation"] == "EXTENDS"]
    assert any(e["source"] == "AuthService" and e["target"] == "BaseService" for e in extends_edges)
    # Check call edge
    call_edges = [e for e in py_edges if e["relation"] == "CALLS"]
    assert any(e["source"] == "AuthService.authenticate" and e["target"] == "verify_token" for e in call_edges)

    # Test JS/TS parser
    ts_code = '''
import { apiClient } from './api';

export interface User {
    id: string;
    name: string;
}

export class UserService extends BaseService {
    async getUser(id: string): Promise<User> {
        return apiClient.fetch(id);
    }
}
'''
    ts_syms, ts_edges = parse_source_code(ts_code, "user_service.ts", "typescript")
    ts_names = {s["name"] for s in ts_syms}
    assert "User" in ts_names
    assert "UserService" in ts_names

    # Test Go parser
    go_code = '''
package main
import "fmt"

type Server struct {
    port int
}

func (s *Server) Start() {
    fmt.Println(s.port)
}
'''
    go_syms, go_edges = parse_source_code(go_code, "server.go", "go")
    go_names = {s["name"] for s in go_syms}
    assert "Server" in go_names
    assert "Start" in go_names

    # Index Python file into CodeLayer
    idx_res = cl.index_file("auth_service.py", project="sample-agent-app", content=py_code, root_dir=t_path)
    assert idx_res["symbols_indexed"] >= 4
    assert idx_res["cached"] is False

    # Verify cached indexing
    idx_res_cached = cl.index_file("auth_service.py", project="sample-agent-app", content=py_code, root_dir=t_path)
    assert idx_res_cached["cached"] is True

    # Test symbol search
    found_syms = cl.search_symbols("AuthService", project="sample-agent-app")
    assert len(found_syms) >= 1
    assert any(s["name"] == "AuthService" for s in found_syms)

    # Test structure
    struct = cl.get_structure("auth_service.py", project="sample-agent-app")
    assert len(struct) >= 4
    struct_txt = CodeLayer.format_structure(struct)
    assert "AuthService" in struct_txt

    # Test callers (AuthService.authenticate calls verify_token)
    callers = cl.get_callers("verify_token", project="sample-agent-app")
    assert len(callers) >= 1
    assert any("authenticate" in c["caller"] for c in callers)
    callers_txt = CodeLayer.format_callers(callers, "verify_token")
    assert "authenticate" in callers_txt

    # Test impact blast radius
    impact = cl.get_impact("verify_token", project="sample-agent-app")
    assert impact["impacted_symbol_count"] >= 1
    assert "AuthService.authenticate" in impact["impacted_symbols"]

    # Test directory indexing on src/agi_memory
    dir_res = cl.index_directory("src/agi_memory", project="sample-agent-app")
    assert dir_res["files_scanned"] >= 10
    assert dir_res["total_symbols"] >= 100

    # Test MCP tools
    tool_struct = mcp_server.call_tool("code_structure", {"path": "auth_service.py", "project": "sample-agent-app"})
    assert "AuthService" in tool_struct

    tool_callers = mcp_server.call_tool("code_callers", {"symbol": "verify_token", "project": "sample-agent-app"})
    assert "authenticate" in tool_callers

    tool_deps = mcp_server.call_tool("code_dependencies", {"symbol": "AuthService.authenticate", "project": "sample-agent-app"})
    assert "verify_token" in tool_deps

    tool_impact = mcp_server.call_tool("code_impact", {"target": "verify_token", "project": "sample-agent-app"})
    assert "Blast Radius" in tool_impact

    tool_index = mcp_server.call_tool("code_index", {"path": "src/agi_memory", "project": "sample-agent-app"})
    assert "Indexed" in tool_index

    # Test CLI commands
    mcp_server.cmd_structure(["auth_service.py", "--project", "sample-agent-app"])
    mcp_server.cmd_callers(["verify_token", "--project", "sample-agent-app"])
    mcp_server.cmd_dependencies(["AuthService.authenticate", "--project", "sample-agent-app"])
    mcp_server.cmd_impact(["verify_token", "--project", "sample-agent-app"])
    mcp_server.cmd_index(["src/agi_memory", "--project", "sample-agent-app"])

# 15. Documentation Consistency, Parity & Link Integrity Checks
with tempfile.TemporaryDirectory() as doc_tmp:
    import re
    repo_root = Path(__file__).resolve().parent.parent

    # 15a. CLAUDE.md and AGENTS.md byte-for-byte identity
    claude_md = (repo_root / "CLAUDE.md").read_bytes()
    agents_md = (repo_root / "AGENTS.md").read_bytes()
    assert claude_md == agents_md, "CLAUDE.md and AGENTS.md must be 100% byte-for-byte identical!"

    # 15b. Tool parity: all 15 MCP tools registered in mcp_server must be documented
    registered_tools = {t["name"] for t in mcp_server.TOOLS}
    assert len(registered_tools) == 15, f"Expected 15 tools in mcp_server, found {len(registered_tools)}"

    # README is an index; the reference lives under docs/, so parity is checked
    # against the whole published doc set rather than one file.
    doc_files = [repo_root / "README.md", *sorted((repo_root / "docs").glob("*.md"))]
    docs_text = "\n".join(f.read_text(encoding="utf-8") for f in doc_files)
    api_contracts_text = (repo_root / "rules" / "api-contracts.md").read_text(encoding="utf-8")
    for tool_name in registered_tools:
        assert tool_name in docs_text, f"Tool '{tool_name}' not documented in README.md or docs/"
        assert tool_name in api_contracts_text, f"Tool '{tool_name}' not documented in rules/api-contracts.md"

    # Every guide the README indexes must exist, or the split silently loses a page.
    for link in re.findall(r"\]\((docs/[^)#]+)\)", (repo_root / "README.md").read_text(encoding="utf-8")):
        assert (repo_root / link).exists(), f"README links to missing {link}"

    # 15c. Relative link integrity across rules/, context/ and docs/
    link_re = re.compile(r"\]\((?!https?://|mailto:|#)([^)]+)\)")
    for md in [repo_root / "rules" / "architecture.md", *sorted((repo_root / "docs").glob("*.md"))]:
        for link in link_re.findall(md.read_text(encoding="utf-8")):
            target = link.split("#")[0]
            if not target:
                continue
            resolved = (md.parent / target).resolve()
            assert resolved.exists(), f"Broken relative link in {md.name}: {link} (resolved to {resolved})"

    # 15d. Project namespace alias bridging (agent-memory <-> agi-memory)
    alias_db = Path(doc_tmp) / "alias_test.db"
    sl_legacy = SessionLayer(db_path=alias_db, project="agent-memory")
    rec_res = sl_legacy.record("Legacy setting: always use port 8080", title="Legacy Port Rule", project="agent-memory")
    assert rec_res["id"] > 0

    # Query using new project name "agi-memory" should find the legacy "agent-memory" observation!
    sl_new = SessionLayer(db_path=alias_db, project="agi-memory")
    hits = sl_new.search("port 8080")
    assert len(hits) >= 1, "Expected search with project='agi-memory' to recall observations saved under 'agent-memory'"
    assert "port 8080" in hits[0].text

    # And vice versa: saving under "agi-memory" should be recallable when querying "agent-memory"
    sl_new.record("New setting: TLS v1.3 only", title="TLS Rule", project="agi-memory")
    hits_legacy = sl_legacy.search("TLS v1.3")
    assert len(hits_legacy) >= 1, "Expected search with project='agent-memory' to recall observations saved under 'agi-memory'"
    assert "TLS" in hits_legacy[0].text

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
print("modularity & event listener decoupling OK")
print("cold-start bootstrap & observability CLI OK")
print("episodic session timeline & recaps OK")
print("structural code graph AST & impact analysis OK")
print("documentation parity, tool coverage & alias bridging OK")

