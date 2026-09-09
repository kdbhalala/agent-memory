"""agent-memory MCP server (stdio, stdlib only, zero dependencies).

Exposes the two-layer framework to any MCP-capable coding agent:
  memory_recall        L1 session memory (fast, zero tokens server-side)
  memory_recall_deep   L1 + L2 durable knowledge (falls back to L1 alone)
  memory_promote       curate durable items L1 -> L2 (needs cognee + LLM)

Run:  python3 mcp_server.py   (spawned by the agent with any cwd)
"""
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])

from layers.base import MemoryLayer  # noqa: F401
from layers.claudemem import ClaudeMemLayer
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
    {"name": "memory_promote",
     "description": "Curate durable knowledge from session memory into long-term storage.",
     "inputSchema": {"type": "object",
                     "properties": {"project": {"type": "string", "description": "Optional project filter"},
                                    "limit": {"type": "integer", "default": 20, "description": "Max candidates to promote"}},
                     "required": []}},
]


def _hits_text(hits):
    return "\n---\n".join(h.text for h in hits) or "(no hits)"


def call_tool(name, args):
    project = args.get("project")
    limit = int(args.get("limit", 5) or 5)
    l1 = ClaudeMemLayer(project=project)
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
            from layers.cognee_layer import CogneeLayer
            l2: MemoryLayer | None = CogneeLayer()
        except Exception:
            l2 = None
        r = recall(query, l1, l2, limit=limit, deep=True)
        out = "## recent\n" + _hits_text(r["recent"])
        if r["durable"]:
            out += "\n\n## durable\n" + _hits_text(r["durable"])
        elif r.get("note"):
            out += f"\n\n({r['note']})"
        return out
    if name == "memory_promote":
        from layers.cognee_layer import CogneeLayer
        import promote
        batch_limit = int(args.get("limit", 20) or 20)
        fresh = promote.promote(CogneeLayer(), project=project, limit=batch_limit)
        return f"promoted {len(fresh)} items"
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
            elif method == "ping":
                reply(mid, {})
            elif method == "tools/list":
                reply(mid, {"tools": TOOLS})
            elif method == "tools/call":
                p = msg.get("params", {})
                try:
                    text = call_tool(p.get("name", ""), p.get("arguments", {}))
                    reply(mid, {"content": [{"type": "text", "text": text}]})
                except RuntimeError as e:  # e.g. cognee not installed
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
