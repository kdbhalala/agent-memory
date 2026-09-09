"""Tiered recall: L1 (claude-mem) first, L2 (cognee) only when needed.

Token-efficient by default: L1 returns a compact index; L2 is skipped
unless deep=True or L1 comes back thin.
"""
from layers.base import Hit, MemoryLayer


def recall(query: str, l1: MemoryLayer, l2: MemoryLayer | None = None,
           limit: int = 5, deep: bool = False) -> dict[str, list[Hit]]:
    recent = l1.search(query, limit=limit)
    result: dict[str, list[Hit]] = {"recent": recent, "durable": []}
    if l2 is not None and (deep or len(recent) < 2):
        try:
            result["durable"] = l2.search(query, limit=limit)
        except Exception as e:  # L2 optional: degrade to L1, say why
            result["note"] = f"durable layer skipped: {type(e).__name__}"
    return result


if __name__ == "__main__":
    import argparse
    from layers.claudemem import ClaudeMemLayer

    parser = argparse.ArgumentParser(description="Recall from agent session & durable memory.")
    parser.add_argument("query", help="Query text or keywords")
    parser.add_argument("--project", "-p", default=None, help="Filter by project name")
    parser.add_argument("--limit", "-l", type=int, default=5, help="Hit limit (default 5)")
    parser.add_argument("--deep", "-d", action="store_true", help="Force deep recall from durable layer")
    args = parser.parse_args()

    l1 = ClaudeMemLayer(project=args.project)
    l2 = None
    if args.deep:
        try:
            from layers.cognee_layer import CogneeLayer
            l2 = CogneeLayer()
        except Exception as exc:
            print(f"(note: L2 unavailable: {exc})")

    res = recall(args.query, l1, l2, limit=args.limit, deep=args.deep)
    print(f"## recent ({len(res['recent'])})")
    for h in res["recent"]:
        print(h.text)
    if res["durable"]:
        print(f"\n## durable ({len(res['durable'])})")
        for h in res["durable"]:
            print(h.text)
    elif res.get("note"):
        print(f"\n({res['note']})")
