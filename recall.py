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
