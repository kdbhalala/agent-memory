"""L2: Cognee durable knowledge via Python SDK (lazy import).

Works without cognee installed: search/add raise a clear error instead of
ImportError at module load, so L1 keeps working standalone.
"""
import asyncio

from .base import Hit, MemoryLayer


class CogneeLayer(MemoryLayer):
    name = "cognee"

    def __init__(self, dataset: str = "durable"):
        self.dataset = dataset

    def _sdk(self):
        try:
            import cognee
            from cognee.modules.search.types import SearchType
        except ImportError as e:
            raise RuntimeError("cognee not installed: pip install cognee") from e
        return cognee, SearchType

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        cognee, SearchType = self._sdk()
        out = asyncio.run(cognee.search(query, query_type=SearchType.GRAPH_COMPLETION,
                                        datasets=[self.dataset], top_k=limit))
        return [Hit(text=getattr(r, "text", str(r)) or "", source=self.name)
                for r in out]

    def add(self, text: str) -> None:
        cognee, _ = self._sdk()
        asyncio.run(cognee.remember(text, dataset_name=self.dataset))
