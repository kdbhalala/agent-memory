"""Tiered recall: L1 (SessionLayer) first, L2 (GraphLayer) only when needed.

Token-efficient by default: L1 returns a compact index; L2 is skipped
unless deep=True or L1 comes back thin.
"""
from layers.base import Hit, MemoryLayer


def recall(query: str, l1: MemoryLayer, l2: MemoryLayer | None = None,
           limit: int = 5, deep: bool = False) -> dict:
    recent = l1.search(query, limit=limit)
    result: dict = {"recent": recent, "durable": []}
    
    if hasattr(l1, "get_pinned_blocks"):
        try:
            pinned = l1.get_pinned_blocks(getattr(l1, "project", None))
            result["core"] = pinned
        except Exception:
            result["core"] = []

    if l2 is None:
        try:
            from layers.graph_layer import GraphLayer
            l2 = GraphLayer(project=getattr(l1, "project", None))
        except Exception:
            l2 = None

    if l2 is not None and (deep or len(recent) < 2):
        try:
            result["durable"] = l2.search(query, limit=limit)
        except Exception as e:  # L2 optional: degrade to L1, say why
            result["note"] = f"durable layer skipped: {type(e).__name__}"
    return result


def main(argv: list[str] | None = None) -> None:
    import argparse
    from layers.session_layer import SessionLayer
    from layers.graph_layer import GraphLayer

    parser = argparse.ArgumentParser(description="Recall from agent session & durable memory.")
    parser.add_argument("query", help="Query text or keywords")
    parser.add_argument("--project", "-p", default=None, help="Filter by project name")
    parser.add_argument("--limit", "-l", type=int, default=5, help="Hit limit (default 5)")
    parser.add_argument("--deep", "-d", action="store_true", help="Force deep recall from durable layer")
    args = parser.parse_args(argv)

    l1 = SessionLayer(project=args.project)
    l2 = GraphLayer(project=args.project)

    res = recall(args.query, l1, l2, limit=args.limit, deep=args.deep)
    if res.get("core"):
        print("## core memory (pinned)")
        for b in res["core"]:
            key = b.get("key") or b.get("block_key", "")
            cat = b.get("category", "system")
            content = b.get("content", "")
            print(f"- [{key}] ({cat}): {content}")
        print()
    print(f"## recent ({len(res['recent'])})")
    for h in res["recent"]:
        print(h.text)
    if res["durable"]:
        print(f"\n## durable ({len(res['durable'])})")
        for h in res["durable"]:
            print(h.text)
    elif res.get("note"):
        print(f"\n({res['note']})")


if __name__ == "__main__":
    main()

