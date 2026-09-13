"""agent-memory MCP server (stdio, stdlib only, zero dependencies).

Exposes the two-layer framework to any MCP-capable coding agent:
  memory_recall        L1 session memory (fast, zero tokens server-side)
  memory_recall_deep   L1 + L2 durable knowledge (falls back to L1 alone)
  memory_record        save decision, pattern, rule, or fix into session/graph
  memory_promote       curate durable items L1 -> L2 (native knowledge graph)
  memory_sync          synchronize memory vault with Git/compaction
  memory_pin           pin critical rule/invariant to core memory
  memory_unpin         unpin a block from core memory
  memory_blocks        list core memory blocks

Run:  python3 mcp_server.py   (spawned by the agent with any cwd)
"""
import json
import sys

try:
    from agi_memory.layers.base import MemoryLayer  # noqa: F401
    from agi_memory.layers.session_layer import SessionLayer
    from agi_memory.layers.episodic_layer import EpisodicLayer
    from agi_memory.layers.code_layer import CodeLayer
    from agi_memory.recall import recall
    from agi_memory import sync, vault
    from agi_memory import __version__
except ImportError:
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    from layers.base import MemoryLayer  # noqa: F401
    from layers.session_layer import SessionLayer
    from layers.episodic_layer import EpisodicLayer
    from layers.code_layer import CodeLayer
    from recall import recall
    import sync
    import vault
    __version__ = "0.4.0"

TOOLS = [
    {"name": "memory_recall",
     "description": "Search recent agent session memory (decisions, fixes, context). Fast, local.",
     "inputSchema": {"type": "object",
                     "properties": {"query": {"type": "string", "description": "Search query or keywords to recall"},
                                    "project": {"type": "string", "description": "Optional project name filter"},
                                    "limit": {"type": "integer", "default": 5, "description": "Max hits to return"}},
                     "required": ["query"]}},
    {"name": "memory_recall_deep",
     "description": "Search session memory AND durable long-term knowledge (architecture, reusable fixes).",
     "inputSchema": {"type": "object",
                     "properties": {"query": {"type": "string", "description": "Search query or keywords to recall"},
                                    "project": {"type": "string", "description": "Optional project name filter"},
                                    "limit": {"type": "integer", "default": 5, "description": "Max hits to return"}},
                     "required": ["query"]}},
    {"name": "memory_record",
     "description": "Save a decision, architectural choice, pattern, rule, or bugfix into session memory and optionally long-term knowledge graph so all agents can recall it.",
     "inputSchema": {"type": "object",
                     "properties": {"text": {"type": "string", "description": "The technical observation, decision, or learning to record"},
                                    "title": {"type": "string", "description": "Short descriptive title for this memory"},
                                    "category": {"type": "string", "enum": ["architecture", "pattern", "bugfix", "convention", "decision"],
                                                 "default": "decision", "description": "Category of the memory"},
                                    "project": {"type": "string", "description": "Target project name"},
                                    "supersedes": {"type": "string", "description": "ID (#123) or keywords of an older memory that this decision overrides/replaces"},
                                    "relations": {"type": "array",
                                                  "description": "Knowledge graph triples (source, relation, target) to store in L2 durable memory",
                                                  "items": {"type": "object",
                                                            "properties": {"source": {"type": "string", "description": "Source entity or concept"},
                                                                           "relation": {"type": "string", "description": "Relationship (e.g., uses, replaces, implements, forbids)"},
                                                                           "target": {"type": "string", "description": "Target entity or concept"},
                                                                           "fact": {"type": "string", "description": "Optional brief statement of the fact"}},
                                                            "required": ["source", "relation", "target"]}}},
                     "required": ["text"]}},
    {"name": "memory_promote",
     "description": "Curate durable knowledge from session memory into long-term storage.",
     "inputSchema": {"type": "object",
                     "properties": {"project": {"type": "string", "description": "Optional project filter"},
                                    "limit": {"type": "integer", "default": 20, "description": "Max candidates to promote"}},
                     "required": []}},
    {"name": "memory_sync",
     "description": "Synchronize memory vault with Git/GitHub remote or run periodic compaction.",
     "inputSchema": {"type": "object",
                     "properties": {"action": {"type": "string", "enum": ["sync", "status", "dedupe"], "default": "sync",
                                               "description": "Sync action: 'sync' (bidirectional git sync), 'status' (check sync state), or 'dedupe' (compact and prune redundant memories)"}},
                     "required": []}},
    {"name": "memory_pin",
     "description": "Pin a critical rule, invariant, or architectural constraint to core memory so it is always recalled.",
     "inputSchema": {"type": "object",
                     "properties": {"key": {"type": "string", "description": "Unique identifier for the block"},
                                    "content": {"type": "string", "description": "Rule or constraint text"},
                                    "category": {"type": "string", "default": "system", "description": "Category of the block"},
                                    "project": {"type": "string", "description": "Optional project filter"}},
                     "required": ["key", "content"]}},
    {"name": "memory_unpin",
     "description": "Unpin a block from core memory.",
     "inputSchema": {"type": "object",
                     "properties": {"key": {"type": "string", "description": "Unique identifier of the block to unpin"}},
                     "required": ["key"]}},
    {"name": "memory_blocks",
     "description": "List core memory blocks.",
     "inputSchema": {"type": "object",
                     "properties": {"project": {"type": "string", "description": "Optional project filter"}},
                     "required": []}},
    {"name": "memory_bootstrap",
     "description": "Bootstrap and seed initial project memories from local Git history and README.md (solves cold-start on new projects).",
     "inputSchema": {"type": "object",
                     "properties": {"repo": {"type": "string", "description": "Repository path (default: .)", "default": "."},
                                    "project": {"type": "string", "description": "Optional project name override"},
                                    "max_commits": {"type": "integer", "default": 20, "description": "Max git commits to parse"}},
                     "required": []}},
    {"name": "memory_timeline",
     "description": "Inspect past agent session timelines, goals, touched files, commit deltas, and cross-session recaps (episodic memory).",
     "inputSchema": {"type": "object",
                     "properties": {"project": {"type": "string", "description": "Optional project name filter"},
                                    "limit": {"type": "integer", "default": 5, "description": "Max sessions to return"},
                                    "session_id": {"type": "string", "description": "Specific session ID to inspect"}},
                     "required": []}},
    {"name": "code_structure",
     "description": "Get structural outline of classes, functions, methods, and types in a file or directory (structural code graph).",
     "inputSchema": {"type": "object",
                     "properties": {"path": {"type": "string", "default": ".", "description": "File or directory path to inspect"},
                                    "project": {"type": "string", "description": "Optional project name filter"}},
                     "required": []}},
    {"name": "code_callers",
     "description": "Find all inbound callers and usages of a function, class, or method across the codebase using recursive CTE.",
     "inputSchema": {"type": "object",
                     "properties": {"symbol": {"type": "string", "description": "Target symbol or method name"},
                                    "project": {"type": "string", "description": "Optional project name filter"},
                                    "max_depth": {"type": "integer", "default": 3, "description": "Max recursive traversal depth (hops)"}},
                     "required": ["symbol"]}},
    {"name": "code_dependencies",
     "description": "Find all outbound dependencies, calls, and imports made by a symbol or module using recursive CTE.",
     "inputSchema": {"type": "object",
                     "properties": {"symbol": {"type": "string", "description": "Target symbol, class, or module name"},
                                    "project": {"type": "string", "description": "Optional project name filter"},
                                    "max_depth": {"type": "integer", "default": 3, "description": "Max recursive traversal depth (hops)"}},
                     "required": ["symbol"]}},
    {"name": "code_impact",
     "description": "Calculate transitive blast radius and impact analysis for modifying a symbol or file (up to N hops) using recursive CTE.",
     "inputSchema": {"type": "object",
                     "properties": {"target": {"type": "string", "description": "Target symbol name or file path to analyze"},
                                    "project": {"type": "string", "description": "Optional project name filter"},
                                    "max_depth": {"type": "integer", "default": 5, "description": "Max traversal depth (hops)"}},
                     "required": ["target"]}},
    {"name": "code_index",
     "description": "Scan and index repository code structure, symbols, imports, and calls into zero-dependency SQLite code graph.",
     "inputSchema": {"type": "object",
                     "properties": {"path": {"type": "string", "default": ".", "description": "Repository or directory path to index"},
                                    "project": {"type": "string", "description": "Optional project name override"},
                                    "force": {"type": "boolean", "default": False, "description": "Force re-indexing ignoring file cache"}},
                     "required": []}},
]


def _hits_text(hits):
    return "\n---\n".join(h.text for h in hits) or "(no hits)"


def _miss_text(query: str, project, layer) -> str:
    """Explain a miss instead of returning a bare "(no hits)".

    A memory tool whose pitch is "your assistant won't forget" is at its most
    dangerous when it quietly finds nothing: the agent reads an empty result as
    "no such decision was ever made" and proceeds to re-decide it. The reply
    below distinguishes an empty store from a genuine miss and says what to do
    next, so a miss is actionable rather than merely true.
    """
    try:
        total = layer.count_observations(project=project)
    except Exception:
        total = None

    proj = project or "(all projects)"
    if total == 0:
        return (f"(no memories stored yet for {proj})\n"
                f"Nothing has been recorded for this project. This is an empty store, "
                f"not a failed lookup — do not read it as 'no such decision exists'. "
                f"Use memory_record to save decisions worth keeping.")
    scope = f" among {total} stored" if total else ""
    return (f"(no match for {query!r} in {proj}{scope})\n"
            f"Memories exist here but none matched. This is a retrieval miss, not proof "
            f"the information was never recorded — do not conclude the decision was never "
            f"made. Try fewer or different words, or memory_recall_deep for a wider search.")


def _core_text(blocks):
    if not blocks:
        return ""
    lines = ["## core memory (pinned)"]
    for b in blocks:
        k = b.get("key") or b.get("block_key", "")
        cat = b.get("category", "system")
        cnt = b.get("content", "")
        lines.append(f"- [{k}] ({cat}): {cnt}")
    return "\n".join(lines)


def call_tool(name, args):
    project = args.get("project")
    limit = int(args.get("limit", 5) or 5)
    l1 = SessionLayer(project=project)
    if name == "memory_recall":
        query = str(args.get("query", "")).strip()
        if not query:
            return "(empty query)"
        pinned = l1.get_pinned_blocks(project=project) if hasattr(l1, "get_pinned_blocks") else []
        core_block = _core_text(pinned)
        hits = l1.search(query, limit)
        recent_text = _hits_text(hits) if hits else _miss_text(query, project, l1)
        if core_block:
            return f"{core_block}\n\n## recent\n{recent_text}"
        return recent_text
    if name == "memory_recall_deep":
        query = str(args.get("query", "")).strip()
        if not query:
            return "(empty query)"
        try:
            try:
                from agi_memory.layers.graph_layer import GraphLayer
            except ImportError:
                from layers.graph_layer import GraphLayer
            l2: MemoryLayer | None = GraphLayer(project=project)
        except Exception:
            l2 = None
        r = recall(query, l1, l2, limit=limit, deep=True)
        out = ""
        core_block = _core_text(r.get("core") or (l1.get_pinned_blocks(project=project) if hasattr(l1, "get_pinned_blocks") else []))
        if core_block:
            out += core_block + "\n\n"
        if not r["recent"] and not r.get("durable"):
            out += _miss_text(query, project, l1)
            return out
        out += "## recent\n" + _hits_text(r["recent"])
        if r["durable"]:
            out += "\n\n## durable\n" + _hits_text(r["durable"])
        elif r.get("note"):
            out += f"\n\n({r['note']})"
        return out
    if name == "memory_pin":
        key = str(args.get("key", "")).strip()
        content = str(args.get("content", "")).strip()
        if not key or not content:
            return "error: 'key' and 'content' parameters are required"
        category = str(args.get("category", "system") or "system").strip()
        res = l1.pin_block(key=key, content=content, category=category, project=project)
        return f"Pinned block [{res['key']}] ({res['category']}) to core memory."
    if name == "memory_unpin":
        key = str(args.get("key", "")).strip()
        if not key:
            return "error: 'key' parameter is required"
        ok = l1.unpin_block(key)
        if ok:
            return f"Unpinned block [{key}] from core memory."
        return f"Block [{key}] not found or already unpinned."
    if name == "memory_blocks":
        blocks = l1.list_blocks(project=project)
        if not blocks:
            return "(no core memory blocks)"
        lines = []
        for b in blocks:
            pinned_str = "pinned" if b.get("pinned") else "unpinned"
            key = b.get("key") or b.get("block_key", "")
            cat = b.get("category", "system")
            p = b.get("project", "global")
            content = b.get("content", "")
            lines.append(f"- [{key}] ({cat}, {p}, {pinned_str}): {content}")
        return "\n".join(lines)
    if name == "memory_record":
        text = str(args.get("text", "")).strip()
        if not text:
            return "error: 'text' parameter is required"
        title = args.get("title")
        category = args.get("category", "decision")
        supersedes = args.get("supersedes")
        relations = args.get("relations") or []

        res = l1.record(
            text=text,
            title=title,
            project=project,
            category=category,
            supersedes=supersedes
        )
        msg = res.get("message", f"Memory saved as observation #{res.get('id')}")

        # Ingest relations into L2 GraphLayer directly
        added_edges = 0
        if relations and isinstance(relations, list):
            try:
                try:
                    from agi_memory.layers.graph_layer import GraphLayer
                except ImportError:
                    from layers.graph_layer import GraphLayer
                l2 = GraphLayer(project=project)
                for item in relations:
                    if isinstance(item, dict) and "source" in item and "relation" in item and "target" in item:
                        src = str(item["source"]).strip()
                        rel = str(item["relation"]).strip()
                        tgt = str(item["target"]).strip()
                        fact = str(item.get("fact", "")).strip() or f"{src} {rel} {tgt}"
                        if src and rel and tgt:
                            l2.add_edge(source=src, relation=rel, target=tgt, fact=fact, project=project)
                            added_edges += 1
            except Exception as e:
                msg += f" (Note: graph edge insertion failed: {e})"

        if added_edges:
            msg += f"\nAdded {added_edges} relation(s) directly to L2 Knowledge Graph."

        if res.get("superseded_ids"):
            msg += f"\nMarked older observation(s) {', '.join(f'#{i}' for i in res['superseded_ids'])} as superseded."

        if res.get("conflicts"):
            conflict_strs = [f"#{c['id']} '{c['title']}': {c['text'][:80]}" for c in res["conflicts"]]
            msg += f"\n\n[Notice - Potential Overlap Found]:\n" + "\n".join(conflict_strs)
            msg += "\nIf this new record replaces any of the above, call memory_record with supersedes='#<id>'."

        return msg
    if name == "memory_promote":
        try:
            from agi_memory.layers.graph_layer import GraphLayer
            from agi_memory import promote
        except ImportError:
            from layers.graph_layer import GraphLayer
            import promote
        batch_limit = int(args.get("limit", 20) or 20)
        l2 = GraphLayer(project=project)
        fresh = promote.promote(l2, project=project, limit=batch_limit)
        return f"promoted {len(fresh)} items to knowledge graph"
    if name == "memory_sync":
        try:
            from agi_memory import sync, vault
        except ImportError:
            import sync
            import vault
        action = str(args.get("action", "sync")).lower()
        if action == "status":
            st = sync.sync_status()
            return (f"Vault: {st['vault_dir']}\n"
                    f"Remote: {st['remote_url'] or '(none)'}\n"
                    f"Status: {st['last_sync_status']}\n"
                    f"Auto-sync: {st['auto_sync']}")
        elif action == "dedupe":
            d = vault.deduplicate_and_compact()
            sync.schedule_auto_sync()
            return f"Compacted vault: {d['observations_pruned']} observations pruned, {d['graph_pruned']} graph items pruned."
        else:
            r = sync.sync(push=True, pull=True)
            return f"Sync complete. Status: {r['status']}. Committed: {r['committed']}, Pulled: {r['pulled']}, Pushed: {r['pushed']}."
    if name == "memory_bootstrap":
        try:
            from agi_memory import bootstrap
        except ImportError:
            import bootstrap
        repo = str(args.get("repo", ".") or ".")
        max_commits = int(args.get("max_commits", 20) or 20)
        proj = args.get("project")
        res = bootstrap.bootstrap_project(repo_dir=repo, max_commits=max_commits, project=proj)
        cnt = res["created_count"]
        p = res["project"]
        if cnt == 0:
            return f"Project '{p}' is already bootstrapped (no new memories added)."
        parts = []
        if res["readme_bootstrapped"]:
            parts.append("1 README architecture")
        if res["commits_bootstrapped"]:
            parts.append(f"{res['commits_bootstrapped']} git commits")
        detail = f" ({', '.join(parts)})" if parts else ""
        return f"Bootstrapped {cnt} memories for project '{p}'{detail}."
    if name == "memory_timeline":
        try:
            from agi_memory.layers.episodic_layer import EpisodicLayer
        except ImportError:
            from layers.episodic_layer import EpisodicLayer
        ep = EpisodicLayer(project=project)
        sid = args.get("session_id")
        if sid:
            sess = ep.get_session(sid)
            if not sess:
                return f"Session '{sid}' not found."
            out = EpisodicLayer.format_timeline([sess])
            if sess.get("events"):
                out += "\n\n### Session Events\n"
                for ev in sess["events"]:
                    out += f"- [{ev['timestamp']}] ({ev['event_type']}): {ev['summary']}\n"
            return out
        sessions = ep.get_timeline(project=project, limit=limit)
        return EpisodicLayer.format_timeline(sessions)
    if name == "code_structure":
        try:
            from agi_memory.layers.code_layer import CodeLayer
        except ImportError:
            from layers.code_layer import CodeLayer
        cl = CodeLayer(project=project)
        target_path = args.get("path", ".") or "."
        syms = cl.get_structure(target_path=target_path, project=project)
        return CodeLayer.format_structure(syms)
    if name == "code_callers":
        try:
            from agi_memory.layers.code_layer import CodeLayer
        except ImportError:
            from layers.code_layer import CodeLayer
        cl = CodeLayer(project=project)
        sym = str(args.get("symbol", "")).strip()
        if not sym:
            return "error: 'symbol' parameter is required"
        depth = int(args.get("max_depth", 3) or 3)
        callers = cl.get_callers(sym, project=project, max_depth=depth)
        return CodeLayer.format_callers(callers, sym)
    if name == "code_dependencies":
        try:
            from agi_memory.layers.code_layer import CodeLayer
        except ImportError:
            from layers.code_layer import CodeLayer
        cl = CodeLayer(project=project)
        sym = str(args.get("symbol", "")).strip()
        if not sym:
            return "error: 'symbol' parameter is required"
        depth = int(args.get("max_depth", 3) or 3)
        deps = cl.get_dependencies(sym, project=project, max_depth=depth)
        return CodeLayer.format_dependencies(deps, sym)
    if name == "code_impact":
        try:
            from agi_memory.layers.code_layer import CodeLayer
        except ImportError:
            from layers.code_layer import CodeLayer
        cl = CodeLayer(project=project)
        target = str(args.get("target", "")).strip()
        if not target:
            return "error: 'target' parameter is required"
        depth = int(args.get("max_depth", 5) or 5)
        impact = cl.get_impact(target, project=project, max_depth=depth)
        return CodeLayer.format_impact(impact)
    if name == "code_index":
        try:
            from agi_memory.layers.code_layer import CodeLayer
        except ImportError:
            from layers.code_layer import CodeLayer
        cl = CodeLayer(project=project)
        p = str(args.get("path", ".") or ".")
        force = bool(args.get("force", False))
        res = cl.index_directory(p, project=project, force=force)
        return f"Indexed {res['files_indexed']} new/modified files ({res['files_cached']} cached) for project '{res['project']}': {res['total_symbols']} symbols, {res['total_edges']} edges in {res['elapsed_ms']}ms."
    raise ValueError(f"unknown tool {name}")


def reply(mid, result=None, error=None):
    msg: dict = {"jsonrpc": "2.0", "id": mid}
    msg["result" if error is None else "error"] = (
        result if error is None else {"code": -32603, "message": str(error)})
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def run_mcp_server():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue  # valid JSON but not a JSON-RPC frame (list, null, scalar)
        method, mid = msg.get("method"), msg.get("id")
        if not isinstance(method, str):
            if mid is not None:
                reply(mid, {}, error="missing or invalid 'method'")
            continue
        try:
            if method == "initialize":
                reply(mid, {"protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "agi-memory", "version": __version__}})
                # Trigger initial background pull to sync multi-device memories
                try:
                    import threading
                    try:
                        from agi_memory import sync
                    except ImportError:
                        import sync
                    t = threading.Thread(target=sync.sync, kwargs={"push": False, "pull": True}, daemon=True)
                    t.start()
                except Exception:
                    pass
            elif method == "ping":
                reply(mid, {})
            elif method == "tools/list":
                reply(mid, {"tools": TOOLS})
            elif method == "tools/call":
                p = msg.get("params") or {}
                if not isinstance(p, dict):
                    p = {}
                args = p.get("arguments")
                try:
                    text = call_tool(p.get("name", ""),
                                     args if isinstance(args, dict) else {})
                    reply(mid, {"content": [{"type": "text", "text": text}]})
                except RuntimeError as e:
                    reply(mid, {"content": [{"type": "text", "text": f"unavailable: {e}"}],
                                      "isError": True})
            elif mid is not None and not method.startswith("notifications/"):
                reply(mid, {}, error=f"unknown method {method}")
            # notifications (initialized etc.): no reply
        except Exception as e:
            if mid is not None:
                reply(mid, error=e)


def cmd_log(argv: list[str]) -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="agent-memory log", description="List recent observations")
    parser.add_argument("--limit", "-n", type=int, default=20, help="Max observations to display (default: 20)")
    parser.add_argument("--project", "-p", default=None, help="Filter by project name")
    parser.add_argument("--all", action="store_true", help="Include superseded observations")
    args = parser.parse_args(argv)

    l1 = SessionLayer(project=args.project)
    obs = l1.list_observations(limit=args.limit, project=args.project, include_superseded=args.all)
    if not obs:
        print("(no observations found)")
        return

    print(f"{'ID':<6} {'DATE':<11} {'PROJECT':<16} {'TYPE':<14} {'TITLE'}")
    print("-" * 80)
    for o in obs:
        d = (o.get("created_at") or "")[:10]
        p = (o.get("project") or "")[:15]
        t = (o.get("type") or "")[:13]
        tit = o.get("title") or ""
        if len(tit) > 42:
            tit = tit[:39] + "..."
        print(f"#{o['id']:<5} {d:<11} {p:<16} {t:<14} {tit}")


def cmd_inspect(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        print("Usage: agent-memory inspect <id>")
        return
    raw_id = argv[0].lstrip("#")
    try:
        obs_id = int(raw_id)
    except ValueError:
        print(f"Invalid observation ID: {argv[0]}")
        return

    l1 = SessionLayer()
    o = l1.get_observation(obs_id)
    if not o:
        print(f"Observation #{obs_id} not found.")
        return

    print(f"=== Observation #{o['id']} ===")
    print(f"Title:       {o['title']}")
    print(f"Project:     {o['project']}")
    print(f"Type:        {o['type']}")
    print(f"Created:     {o['created_at']}")
    if o.get("subtitle"):
        print(f"Subtitle:    {o['subtitle']}")
    if o.get("concepts"):
        print(f"Concepts:    {', '.join(o['concepts'])}")
    if o.get("facts"):
        print("\nFacts:")
        for f in o["facts"]:
            print(f"  - {f}")
    if o.get("narrative"):
        print(f"\nNarrative:\n{o['narrative']}")


def cmd_delete(argv: list[str]) -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="agent-memory delete", description="Delete or supersede an observation")
    parser.add_argument("id", help="Observation ID (#123 or 123)")
    parser.add_argument("--hard", action="store_true", help="Permanently delete from database instead of soft-deleting")
    args = parser.parse_args(argv)

    raw_id = args.id.lstrip("#")
    try:
        obs_id = int(raw_id)
    except ValueError:
        print(f"Invalid observation ID: {args.id}")
        return

    l1 = SessionLayer()
    ok = l1.delete_observation(obs_id, hard=args.hard)
    if ok:
        mode = "Permanently deleted" if args.hard else "Marked as superseded/deleted"
        print(f"[✓] {mode} observation #{obs_id}.")
    else:
        print(f"[!] Observation #{obs_id} not found or already deleted.")


def cmd_pin(argv: list[str]) -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="agent-memory pin", description="Pin a critical rule or invariant to core memory")
    parser.add_argument("key", help="Unique identifier for the block")
    parser.add_argument("content", help="Rule or constraint content")
    parser.add_argument("--category", "-c", default="system", help="Category (default: system)")
    parser.add_argument("--project", "-p", default=None, help="Project name (default: global)")
    args = parser.parse_args(argv)

    l1 = SessionLayer(project=args.project)
    res = l1.pin_block(key=args.key, content=args.content, category=args.category, project=args.project)
    print(f"[✓] Pinned block [{res['key']}] ({res['category']}) to core memory.")


def cmd_unpin(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        print("Usage: agent-memory unpin <key>")
        return
    l1 = SessionLayer()
    ok = l1.unpin_block(argv[0])
    if ok:
        print(f"[✓] Unpinned block [{argv[0]}] from core memory.")
    else:
        print(f"[!] Block [{argv[0]}] not found or already unpinned.")


def cmd_blocks(argv: list[str]) -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="agent-memory blocks", description="List core memory blocks")
    parser.add_argument("--project", "-p", default=None, help="Filter by project")
    args = parser.parse_args(argv)

    l1 = SessionLayer(project=args.project)
    blocks = l1.list_blocks(project=args.project)
    if not blocks:
        print("(no core memory blocks)")
        return
    print(f"{'KEY':<20} {'CATEGORY':<12} {'PROJECT':<14} {'STATUS':<10} {'CONTENT'}")
    print("-" * 80)
    for b in blocks:
        k = b.get("key") or b.get("block_key", "")
        cat = b.get("category", "system")
        p = b.get("project", "global")
        st = "pinned" if b.get("pinned") else "unpinned"
        cnt = (b.get("content") or "").replace("\n", " ")
        if len(cnt) > 35:
            cnt = cnt[:32] + "..."
        print(f"{k:<20} {cat:<12} {p:<14} {st:<10} {cnt}")


def cmd_recall(argv: list[str]) -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="agent-memory recall", description="Search working & durable memory")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--project", "-p", default=None, help="Project name filter")
    parser.add_argument("--deep", action="store_true", help="Search L2 knowledge graph as well")
    parser.add_argument("--limit", "-n", type=int, default=5, help="Max hits to return (default: 5)")
    args = parser.parse_args(argv)

    tool_name = "memory_recall_deep" if args.deep else "memory_recall"
    res = call_tool(tool_name, {"query": args.query, "project": args.project, "limit": args.limit})
    print(res)


def cmd_timeline(argv: list[str]) -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="agi-memory timeline", description="Show episodic session history")
    parser.add_argument("--project", "-p", default=None, help="Project filter")
    parser.add_argument("--limit", "-n", type=int, default=5, help="Number of sessions")
    parser.add_argument("--session", "-s", default=None, help="Session ID to inspect")
    args = parser.parse_args(argv)
    res = call_tool("memory_timeline", {"project": args.project, "limit": args.limit, "session_id": args.session})
    print(res)


def cmd_structure(argv: list[str]) -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="agi-memory structure", description="Outline code structure & symbols")
    parser.add_argument("path", nargs="?", default=".", help="File or directory path")
    parser.add_argument("--project", "-p", default=None, help="Project filter")
    args = parser.parse_args(argv)
    res = call_tool("code_structure", {"path": args.path, "project": args.project})
    print(res)


def cmd_callers(argv: list[str]) -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="agi-memory callers", description="Find inbound callers & references")
    parser.add_argument("symbol", help="Target symbol or function name")
    parser.add_argument("--project", "-p", default=None, help="Project filter")
    parser.add_argument("--depth", "-d", type=int, default=3, help="Max recursion depth")
    args = parser.parse_args(argv)
    res = call_tool("code_callers", {"symbol": args.symbol, "project": args.project, "max_depth": args.depth})
    print(res)


def cmd_dependencies(argv: list[str]) -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="agi-memory dependencies", description="Find outbound dependencies & calls")
    parser.add_argument("symbol", help="Target symbol or module name")
    parser.add_argument("--project", "-p", default=None, help="Project filter")
    parser.add_argument("--depth", "-d", type=int, default=3, help="Max recursion depth")
    args = parser.parse_args(argv)
    res = call_tool("code_dependencies", {"symbol": args.symbol, "project": args.project, "max_depth": args.depth})
    print(res)


def cmd_impact(argv: list[str]) -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="agi-memory impact", description="Calculate transitive blast radius")
    parser.add_argument("target", help="Target symbol or file path to analyze")
    parser.add_argument("--project", "-p", default=None, help="Project filter")
    parser.add_argument("--depth", "-d", type=int, default=5, help="Max recursion depth")
    args = parser.parse_args(argv)
    res = call_tool("code_impact", {"target": args.target, "project": args.project, "max_depth": args.depth})
    print(res)


def cmd_index(argv: list[str]) -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="agi-memory index", description="Index repository into structural code graph")
    parser.add_argument("path", nargs="?", default=".", help="Directory to index")
    parser.add_argument("--project", "-p", default=None, help="Project override")
    parser.add_argument("--force", action="store_true", help="Force re-indexing without cache")
    args = parser.parse_args(argv)
    res = call_tool("code_index", {"path": args.path, "project": args.project, "force": args.force})
    print(res)


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    if argv:
        cmd = argv[0].lower()
        if cmd == "integrate":
            try:
                from agi_memory import integrate
            except ImportError:
                import integrate
            sys.argv = [sys.argv[0]] + argv[1:]
            integrate.main()
            return
        elif cmd in ("hooks", "status", "install", "init", "uninstall", "test", "generate"):
            try:
                from agi_memory import integrate
            except ImportError:
                import integrate
            sys.argv = [sys.argv[0]] + argv
            integrate.main()
            return
        elif cmd == "sync":
            if len(argv) > 1 and argv[1] in ("now", "dedupe", "init", "status"):
                try:
                    from agi_memory import sync
                except ImportError:
                    import sync
                sys.argv = [sys.argv[0]] + argv[1:]
                sync.main()
                return
            else:
                try:
                    from agi_memory import integrate
                except ImportError:
                    import integrate
                sys.argv = [sys.argv[0]] + argv
                integrate.main()
                return
        elif cmd == "analyze":
            try:
                from agi_memory import analyze
            except ImportError:
                import analyze
            analyze.main(argv[1:])
            return
        elif cmd == "bootstrap":
            try:
                from agi_memory import bootstrap
            except ImportError:
                import bootstrap
            bootstrap.main(argv[1:])
            return
        elif cmd == "log":
            cmd_log(argv[1:])
            return
        elif cmd == "inspect":
            cmd_inspect(argv[1:])
            return
        elif cmd == "delete":
            cmd_delete(argv[1:])
            return
        elif cmd == "pin":
            cmd_pin(argv[1:])
            return
        elif cmd == "unpin":
            cmd_unpin(argv[1:])
            return
        elif cmd == "blocks":
            cmd_blocks(argv[1:])
            return
        elif cmd == "recall":
            cmd_recall(argv[1:])
            return
        elif cmd == "timeline":
            cmd_timeline(argv[1:])
            return
        elif cmd == "structure":
            cmd_structure(argv[1:])
            return
        elif cmd == "callers":
            cmd_callers(argv[1:])
            return
        elif cmd == "dependencies":
            cmd_dependencies(argv[1:])
            return
        elif cmd == "impact":
            cmd_impact(argv[1:])
            return
        elif cmd == "index":
            cmd_index(argv[1:])
            return
        elif cmd in ("-v", "--version", "version"):
            print(f"agi-memory {__version__}")
            return
        elif cmd in ("-h", "--help", "help"):
            print("agi-memory: Zero-dependency four-pillar cognitive memory framework with MCP server.\n")
            print("Usage:")
            print("  agi-memory                           Start MCP stdio server")
            print("  agi-memory bootstrap [--repo .]      Bootstrap initial memories from Git & README")
            print("  agi-memory timeline [--limit 5]      Inspect past session timelines and recaps")
            print("  agi-memory structure [path]          Show hierarchical symbol structure")
            print("  agi-memory callers <symbol>          Find inbound callers & references across codebase")
            print("  agi-memory dependencies <symbol>     Find outbound dependencies & calls")
            print("  agi-memory impact <target>           Calculate blast radius impact analysis")
            print("  agi-memory index [path]              Index repository into structural code graph")
            print("  agi-memory log [--limit 20]          List recent observations")
            print("  agi-memory inspect <id>              Inspect observation details and facts")
            print("  agi-memory delete <id> [--hard]      Delete/supersede an observation")
            print("  agi-memory recall <query>            Search working & durable memory")
            print("  agi-memory pin <key> <content>       Pin critical invariant to core memory")
            print("  agi-memory unpin <key>               Unpin block from core memory")
            print("  agi-memory blocks                    List pinned core memory blocks")
            print("  agi-memory init [PATH]               Wire a project & install the /agi-init slash command")
            print("  agi-memory analyze [PATH] [--json]   Report detected stack, commands, layout")
            print("  agi-memory integrate [COMMAND ...]   Assistant integration & project wiring")
            print("  agi-memory hooks [TOOLS ...]         Manage automated lifecycle hooks")
            print("  agi-memory status                    Show MCP integration status")
            print("  agi-memory sync [now|dedupe|init]    Manage multi-device vault synchronization")
            print("  agi-memory test                      Verify MCP handshake and registered tools\n")
            print("Note: 'agent-memory' is supported as a 100% backwards-compatible CLI alias.\n")
            return
        else:
            print(f"Unknown command: {cmd}. Run 'agi-memory --help' for usage.", file=sys.stderr)
            sys.exit(1)

    run_mcp_server()


if __name__ == "__main__":
    main()

