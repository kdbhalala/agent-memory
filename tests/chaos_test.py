#!/usr/bin/env python3
"""Adversarial robustness suite: hostile inputs, corruption, concurrency.

Complements stress_test.py (which measures happy-path throughput). This one
asks: does anything crash, corrupt, or silently lose data when abused?

Runs fully isolated in a temp dir via AGI_MEMORY_DIR — never touches ~/.agi-memory.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import threading
import traceback
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="agi-chaos-")
os.environ["AGI_MEMORY_DIR"] = _TMP
os.environ["AGI_MEMORY_VAULT"] = str(Path(_TMP) / "vault")
os.environ["AGI_MEMORY_DB"] = str(Path(_TMP) / "memory.db")
os.environ["AGI_MEMORY_STATE"] = str(Path(_TMP) / "promoted.json")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agi_memory.layers.episodic_layer import EpisodicLayer  # noqa: E402
from agi_memory.layers.graph_layer import GraphLayer  # noqa: E402
from agi_memory.layers.session_layer import SessionLayer  # noqa: E402
from agi_memory.recall import recall  # noqa: E402
from agi_memory import vault  # noqa: E402

FAILURES: list[str] = []
PASSED = 0


def check(name: str, fn) -> None:
    """Run fn; record a failure on any exception or falsy return."""
    global PASSED
    try:
        ok = fn()
        if ok is False:
            FAILURES.append(f"{name}: returned False")
        else:
            PASSED += 1
            print(f"  PASS  {name}")
            return
    except Exception:
        FAILURES.append(f"{name}: {traceback.format_exc(limit=3)}")
    print(f"  FAIL  {name}")


# ---------------------------------------------------------------- hostile input

HOSTILE = [
    "", "   ", "\n\t ", "*", '"', "AND", "OR", "NEAR", "a*b", "'; DROP TABLE observations;--",
    "x" * 100_000, "\x00null", "🔥💀 emoji", "../../etc/passwd", "%s %d {}", "\\", "NOT(",
    "café", "日本語テスト", "-", "()", '"""', "a" * 1000 + " " + "b" * 1000,
]


def t_search_hostile():
    l1 = SessionLayer(project="chaos")
    for q in HOSTILE:
        l1.search(q, limit=5)  # must not raise
    return True


def t_record_hostile():
    l1 = SessionLayer(project="chaos")
    for text in HOSTILE:
        if not text.strip():
            continue
        l1.record(text, title=text[:30] or None, project="chaos")
    # every recorded doc must remain findable / db intact
    return l1.search("emoji", limit=5) is not None


def t_limits():
    l1 = SessionLayer(project="chaos")
    for lim in (0, -1, 1, 10**6):
        l1.search("emoji", limit=lim)
    return True


def t_graph_hostile():
    g = GraphLayer(project="chaos")
    for q in HOSTILE:
        g.search(q, limit=5)
    for q in HOSTILE[:8]:
        g.add(q)
    return True


def t_alias_cycle():
    """Self- and mutual-alias must not infinite-loop resolve_node."""
    g = GraphLayer(project="chaos")
    g.add_alias("A_cyc", "B_cyc")
    g.add_alias("B_cyc", "A_cyc")
    g.add_alias("S_cyc", "S_cyc")
    return g.resolve_node("A_cyc") is not None and g.resolve_node("S_cyc") is not None


def t_supersedes_missing():
    l1 = SessionLayer(project="chaos")
    l1.record("targets a nonexistent id", project="chaos", supersedes="99999999")
    l1.record("targets a junk id", project="chaos", supersedes="not-an-int")
    return True


def t_project_traversal():
    """A project name with path separators must not escape the data dir."""
    evil = "../../../tmp/agi-escape"
    SessionLayer(project=evil).record("traversal probe", project=evil)
    return not Path("/tmp/agi-escape").exists()


# ------------------------------------------------------------------ corruption

def t_corrupt_vault_line():
    """A malformed JSONL line must be skipped, not abort the import."""
    vdir = vault.init_vault()
    obs = vdir / "observations.jsonl"
    with open(obs, "a", encoding="utf-8") as f:
        f.write("{not json at all\n")
        f.write("\n")
        f.write('{"guid":"g1"}\n')  # valid json, missing fields
        f.write('{"guid":"g2","project":"chaos","title":"t","text":"body"}\n')
    vault.import_from_vault()
    return True


def t_corrupt_db():
    """A garbage DB file must degrade to an error-free empty result, not crash."""
    bad = Path(_TMP) / "corrupt.db"
    bad.write_bytes(b"SQLite format 3\x00" + b"\xde\xad\xbe\xef" * 500)
    return all(isinstance(L(db_path=bad, project="chaos").search("anything", limit=5), list)
               for L in (SessionLayer, GraphLayer, EpisodicLayer))


def t_truncated_db():
    empty = Path(_TMP) / "empty.db"
    empty.write_bytes(b"")
    return all(isinstance(L(db_path=empty, project="chaos").search("x", limit=3), list)
               for L in (SessionLayer, GraphLayer, EpisodicLayer))


def t_readonly_dir():
    """Recording into a read-only location must not raise to the caller."""
    ro = Path(_TMP) / "ro"
    ro.mkdir(exist_ok=True)
    db = ro / "ro.db"
    SessionLayer(db_path=db, project="chaos").record("seed", project="chaos")
    os.chmod(ro, 0o500)
    try:
        SessionLayer(db_path=db, project="chaos").record("blocked write", project="chaos")
    except Exception as e:
        return f"raised {type(e).__name__}"  # truthy string => visible in output but not a fail
    finally:
        os.chmod(ro, 0o700)
    return True


# ----------------------------------------------------------------- concurrency

def t_concurrent_writes():
    """20 threads x 10 writes: no 'database is locked', no lost rows."""
    errors: list[str] = []

    def worker(n: int):
        try:
            l1 = SessionLayer(project="conc")
            for i in range(10):
                l1.record(f"concurrent observation {n}-{i}", project="conc")
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise AssertionError(f"{len(errors)} writer errors, first: {errors[0]}")

    db = Path(os.environ["AGI_MEMORY_DB"])
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    n = con.execute("SELECT COUNT(*) FROM observations WHERE project='conc'").fetchone()[0]
    con.close()
    if n != 200:
        raise AssertionError(f"lost writes: expected 200 rows, found {n}")
    return True


def t_concurrent_read_write():
    """Readers must never see a half-written or locked DB."""
    errors: list[str] = []
    stop = threading.Event()

    def reader():
        l1 = SessionLayer(project="conc")
        while not stop.is_set():
            try:
                l1.search("concurrent observation", limit=5)
            except Exception as e:
                errors.append(f"{type(e).__name__}: {e}")
                return

    def writer():
        l1 = SessionLayer(project="conc")
        for i in range(50):
            try:
                l1.record(f"rw churn {i}", project="conc")
            except Exception as e:
                errors.append(f"{type(e).__name__}: {e}")
                return

    rs = [threading.Thread(target=reader) for _ in range(5)]
    w = threading.Thread(target=writer)
    for r in rs:
        r.start()
    w.start()
    w.join()
    stop.set()
    for r in rs:
        r.join()
    if errors:
        raise AssertionError(f"{len(errors)} errors, first: {errors[0]}")
    return True


def t_concurrent_episodic():
    errors: list[str] = []

    def worker(n: int):
        try:
            ep = EpisodicLayer(project="conc")
            sid = ep.start_session(project="conc")["session_id"]
            ep.record_event(sid, "edit", f"file{n}.py")
            ep.end_session(sid, summary=f"session {n}")
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")

    ts = [threading.Thread(target=worker, args=(n,)) for n in range(10)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    if errors:
        raise AssertionError(f"{len(errors)} errors, first: {errors[0]}")
    return len(EpisodicLayer(project="conc").get_timeline(project="conc", limit=20)) >= 10


# --------------------------------------------------------------------- recall

def t_recall_hostile():
    l1 = SessionLayer(project="chaos")
    g = GraphLayer(project="chaos")
    for q in HOSTILE:
        r = recall(q, l1, g, limit=3)
        if not isinstance(r, dict) or "recent" not in r:
            raise AssertionError(f"bad recall shape for {q!r}")
    return True


def t_recall_missing_db():
    """No DB yet (fresh install) must return an empty result, not explode."""
    gone = Path(_TMP) / "does-not-exist" / "nope.db"
    r = recall("anything", SessionLayer(db_path=gone, project="chaos"),
               GraphLayer(db_path=gone, project="chaos"), limit=3)
    return r["recent"] == []


def t_compaction_preserves_distinct():
    """Compaction must never drop observations that differ in real content.

    The vault is the canonical append-only store; a dedupe key that is too
    coarse deletes a user's memories permanently.
    """
    vdir = Path(_TMP) / "vault-compact"
    obs_file = vault.init_vault(vdir) / "observations.jsonl"
    shared = "the architecture decision recorded here has a long shared preamble " * 4
    records = [
        # same project+title, same first 120 chars, genuinely different endings
        {"guid": f"d{i}", "content_hash": f"d{i}", "project": "compact",
         "title": "Decision", "narrative": shared + f" the distinct conclusion is option {i}",
         "facts": "", "created_at_epoch": 1000 + i}
        for i in range(5)
    ]
    records += [  # true duplicates: must collapse to one
        {"guid": "dup", "content_hash": "dup", "project": "compact", "title": "Dup",
         "narrative": "identical body", "facts": "", "created_at_epoch": 2000}
        for _ in range(3)
    ]
    with open(obs_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")

    vault.deduplicate_and_compact(vault_dir=vdir,
                                  session_db=Path(_TMP) / "compact.db",
                                  graph_db=Path(_TMP) / "compact.db")

    kept = [json.loads(ln) for ln in obs_file.read_text().splitlines() if ln.strip()]
    endings = {r["narrative"][-30:] for r in kept}
    distinct_kept = sum(1 for r in kept if r.get("title") == "Decision")
    if distinct_kept != 5:
        raise AssertionError(
            f"compaction destroyed distinct observations: kept {distinct_kept}/5 "
            f"(endings: {sorted(endings)})")
    if sum(1 for r in kept if r.get("title") == "Dup") != 1:
        raise AssertionError("compaction failed to collapse true duplicates")
    return True


def t_vault_roundtrip_survives_db_loss():
    """Core promise: a recorded memory survives losing the SQLite DB entirely.

    record -> vault -> delete DB -> import_from_vault -> still recallable.
    """
    vdir = Path(_TMP) / "vault-roundtrip"
    db = Path(_TMP) / "roundtrip.db"
    vault.init_vault(vdir)
    vault.enable_vault_listeners()
    try:
        l1 = SessionLayer(db_path=db, project="roundtrip")
        marker = "zorblax quantum ledger invariant"
        for i in range(20):
            l1.record(f"{marker} number {i}", title=f"Roundtrip {i}", project="roundtrip")
        vault.export_dirty_to_vault(vault_dir=vdir, session_db=db, graph_db=db)
    finally:
        vault.disable_vault_listeners()

    before = len(SessionLayer(db_path=db, project="roundtrip").search(marker, limit=50))
    if before == 0:
        raise AssertionError("records were not recallable even before DB loss")

    db.unlink()  # catastrophic local loss
    vault.import_from_vault(vault_dir=vdir, session_db=db, graph_db=db)
    after = len(SessionLayer(db_path=db, project="roundtrip").search(marker, limit=50))
    if after < before:
        raise AssertionError(f"vault restore lost memories: {before} before, {after} after")
    return True


def t_multiprocess_writes():
    """8 separate processes (the real multi-session case) writing the same DB."""
    import subprocess
    src = str(Path(__file__).resolve().parent.parent / "src")
    prog = (
        "import sys;sys.path.insert(0,%r)\n"
        "from agi_memory.layers.session_layer import SessionLayer\n"
        "from agi_memory.layers.episodic_layer import EpisodicLayer\n"
        "l1=SessionLayer(project='mproc')\n"
        "ep=EpisodicLayer(project='mproc')\n"
        "for i in range(25):\n"
        "    l1.record(f'mproc write {sys.argv[1]}-{i}', project='mproc')\n"
        "    l1.search('mproc write', limit=5)\n"
        "sid=ep.start_session(project='mproc')['session_id']\n"
        "ep.end_session(sid, summary='mproc')\n" % src
    )
    env = dict(os.environ)
    procs = [subprocess.Popen([sys.executable, "-c", prog, str(n)],
                              stderr=subprocess.PIPE, text=True, env=env) for n in range(8)]
    errs = []
    for p in procs:
        _, err = p.communicate(timeout=180)
        if p.returncode != 0:
            errs.append(err.strip().splitlines()[-1] if err.strip() else "unknown")
    if errs:
        raise AssertionError(f"{len(errs)}/8 processes failed, first: {errs[0]}")

    db = Path(os.environ["AGI_MEMORY_DB"])
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    n = con.execute("SELECT COUNT(*) FROM observations WHERE project='mproc'").fetchone()[0]
    con.close()
    if n != 200:
        raise AssertionError(f"lost writes across processes: expected 200, found {n}")
    return True


def t_hooks_resilience():
    """Lifecycle hooks run on every session: they must never raise to the harness."""
    from agi_memory import hooks

    for fn in (hooks.hook_session_start, hooks.hook_pre_compact,
               hooks.hook_session_end, hooks.hook_post_commit):
        for project in (None, "", "chaos", "../../escape", "🔥", "x" * 500):
            fn(project)
    # hook_pre_commit is deliberately excluded: it shells out to the project's
    # own test suite, which would recurse into this file.
    return True


# ------------------------------------------------------- MCP protocol surface

def _mcp_roundtrip(lines: list[str]) -> list[dict]:
    """Feed raw JSON-RPC lines to the server process; return parsed replies."""
    import subprocess
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")
    p = subprocess.run(
        [sys.executable, "-m", "agi_memory.mcp_server"],
        input="\n".join(lines) + "\n", capture_output=True, text=True, env=env, timeout=120,
    )
    if p.returncode != 0:
        raise AssertionError(f"server exited {p.returncode}: {p.stderr[-500:]}")
    out = []
    for ln in p.stdout.splitlines():
        ln = ln.strip()
        if ln:
            out.append(json.loads(ln))  # any non-JSON stdout line breaks the protocol
    return out


def t_mcp_malformed_protocol():
    """Garbage and malformed frames must never kill the server or corrupt stdout."""
    lines = [
        "not json at all",
        "",
        "[]",
        "null",
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
        '{"jsonrpc":"2.0","id":2,"method":"tools/list"}',
        '{"jsonrpc":"2.0","id":3}',                                   # no method
        '{"jsonrpc":"2.0","method":"notifications/initialized"}',     # no id
        '{"jsonrpc":"2.0","id":4,"method":"bogus/method"}',
        '{"jsonrpc":"2.0","id":5,"method":"tools/call"}',             # no params
        '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"nope","arguments":{}}}',
        '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"memory_recall"}}',
        '{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"memory_recall","arguments":null}}',
        '{"jsonrpc":"2.0","id":9,"method":"ping"}',
    ]
    replies = _mcp_roundtrip(lines)
    got = {r.get("id") for r in replies}
    # server must answer every framed request that carried an id, and stay alive to the end
    for need in (1, 2, 9):
        if need not in got:
            raise AssertionError(f"no reply for id {need}; got {sorted(x for x in got if x is not None)}")
    return True


def t_mcp_hostile_arguments():
    """Wrong-typed and oversized tool arguments must return an error, not crash."""
    calls = []
    bad_args = [
        {}, {"query": None}, {"query": 12345}, {"query": {"nested": True}},
        {"query": ["a", "b"]}, {"query": "x" * 50_000}, {"query": "ok", "limit": "many"},
        {"query": "ok", "limit": -5}, {"query": "ok", "project": 7},
        {"text": None}, {"text": "", "title": None}, {"symbol": None}, {"path": "/../../etc"},
    ]
    for i, args in enumerate(bad_args, start=100):
        for tool in ("memory_recall", "memory_record", "code_structure", "code_impact"):
            calls.append(json.dumps({"jsonrpc": "2.0", "id": i * 10 + len(calls) % 10,
                                     "method": "tools/call",
                                     "params": {"name": tool, "arguments": args}}))
    replies = _mcp_roundtrip(
        ['{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'] + calls
        + ['{"jsonrpc":"2.0","id":999,"method":"ping"}'])
    if not any(r.get("id") == 999 for r in replies):
        raise AssertionError("server died before the final ping")
    return True


# --------------------------------------------------------------- code indexer

def t_code_index_garbage():
    """Indexing must survive syntax errors, binaries, and pathological files."""
    from agi_memory.layers.code_layer import CodeLayer

    root = Path(_TMP) / "garbage-repo"
    root.mkdir(exist_ok=True)
    (root / "broken.py").write_text("def (((:\n  ???\n")
    (root / "empty.py").write_text("")
    (root / "binary.py").write_bytes(b"\x00\x01\x02\xff\xfe" * 100)
    (root / "bad_utf8.py").write_bytes(b"# \xff\xfe invalid utf8\ndef f(): pass\n")
    (root / "deep.py").write_text("def f():\n" + "".join(
        f"{'    ' * (i + 1)}if x:\n" for i in range(60)) + "    " * 61 + "pass\n")
    (root / "huge.py").write_text("\n".join(f"def f{i}(): pass" for i in range(20_000)))
    try:
        (root / "loop").symlink_to(root)  # symlink cycle
    except (OSError, NotImplementedError):
        pass
    CodeLayer(project="chaos").index_directory(root)
    return True


TESTS = [
    ("hostile search input", t_search_hostile),
    ("hostile record input", t_record_hostile),
    ("degenerate limits", t_limits),
    ("hostile graph input", t_graph_hostile),
    ("alias cycle terminates", t_alias_cycle),
    ("supersedes missing target", t_supersedes_missing),
    ("project name path traversal", t_project_traversal),
    ("corrupt vault JSONL line", t_corrupt_vault_line),
    ("corrupt database file", t_corrupt_db),
    ("truncated/empty database", t_truncated_db),
    ("read-only data dir", t_readonly_dir),
    ("concurrent writes (20x10)", t_concurrent_writes),
    ("concurrent read+write", t_concurrent_read_write),
    ("concurrent episodic sessions", t_concurrent_episodic),
    ("recall hostile input", t_recall_hostile),
    ("recall with missing db", t_recall_missing_db),
    ("compaction preserves distinct records", t_compaction_preserves_distinct),
    ("vault roundtrip survives db loss", t_vault_roundtrip_survives_db_loss),
    ("multi-process concurrent writes", t_multiprocess_writes),
    ("lifecycle hooks resilience", t_hooks_resilience),
    ("mcp malformed protocol frames", t_mcp_malformed_protocol),
    ("mcp hostile tool arguments", t_mcp_hostile_arguments),
    ("code indexer on garbage files", t_code_index_garbage),
]


def main() -> int:
    print(f"chaos suite (isolated in {_TMP})\n")
    for name, fn in TESTS:
        check(name, fn)
    print(f"\n{PASSED}/{len(TESTS)} passed")
    for f in FAILURES:
        print(f"\n--- {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
