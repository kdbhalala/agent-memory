"""Shared contract for memory layers. Either layer must stay replaceable."""
from dataclasses import dataclass, field


@dataclass
class Hit:
    text: str
    source: str  # layer name, e.g. "session" / "graph"
    ref: str = ""  # id / dataset pointer for follow-up fetch
    score: float = 0.0
    meta: dict = field(default_factory=dict)


class MemoryLayer:
    name = "base"

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        raise NotImplementedError

    def health(self) -> bool:
        try:
            self.search("__health__", limit=1)
            return True
        except Exception:
            return False
