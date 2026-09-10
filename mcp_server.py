"""agent-memory MCP server (stdio, stdlib only, zero dependencies).

Exposes the two-layer framework to any MCP-capable coding agent:
  memory_recall        L1 session memory (fast, zero tokens server-side)
  memory_recall_deep   L1 + L2 durable knowledge (falls back to L1 alone)
  memory_promote       curate durable items L1 -> L2 (native knowledge graph)

Run:  python3 mcp_server.py   (spawned by the agent with any cwd)
"""
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from layers.base import MemoryLayer  # noqa: F401
from layers.session_layer import SessionLayer
from recall import recall

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
]


def _hits_text(hits):
    return "\n---\n".join(h.text for h in hits) or "(no hits)"


def call_tool(name, args):
    project = args.get("project")
    limit = int(args.get("limit", 5) or 5)
    l1 = SessionLayer(project=project)
    if name == "memory_recall":
        query = str(args.get("query", "")).strip()
        if not query:
            return "(empty query)"
        return _hits_text(l1.search(query, limit))
    if name == "memory_recall_deep":
        query = str(args.get("query", "")).strip()
        if not query:
            return "(empty query)"
        try:
            from layers.graph_layer import GraphLayer
            l2: MemoryLayer | None = GraphLayer(project=project)
        except Exception:
            l2 = None
        r = recall(query, l1, l2, limit=limit, deep=True)
        out = "## recent\n" + _hits_text(r["recent"])
        if r["durable"]:
            out += "\n\n## durable\n" + _hits_text(r["durable"])
        elif r.get("note"):
            out += f"\n\n({r['note']})"
        return out
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
        from layers.graph_layer import GraphLayer
        import promote
        batch_limit = int(args.get("limit", 20) or 20)
        l2 = GraphLayer(project=project)
        fresh = promote.promote(l2, project=project, limit=batch_limit)
        return f"promoted {len(fresh)} items to knowledge graph"
    if name == "memory_sync":
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
    raise ValueError(f"unknown tool {name}")


def reply(mid, result=None, error=None):
    msg: dict = {"jsonrpc": "2.0", "id": mid}
    msg["result" if error is None else "error"] = (
        result if error is None else {"code": -32603, "message": str(error)})
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method, mid = msg.get("method"), msg.get("id")
        try:
            if method == "initialize":
                reply(mid, {"protocolVersion": "2024-11-05",
                            "capabilities": {"tools": {}},
                            "serverInfo": {"name": "agent-memory", "version": "0.1.0"}})
                # Trigger initial background pull to sync multi-device memories
                try:
                    import threading
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
                p = msg.get("params", {})
                try:
                    text = call_tool(p.get("name", ""), p.get("arguments", {}))
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


if __name__ == "__main__":
    main()
