"""L2: Cognee durable knowledge via Python SDK (lazy import).

Works without cognee installed: search/add raise a clear error instead of
ImportError at module load, so L1 keeps working standalone. SDK coroutines
run in a worker thread so the layer stays sync-callable from async code.
"""
import asyncio
import json
import os
import threading
from pathlib import Path

from .base import Hit, MemoryLayer

_CMEM_SETTINGS = Path.home() / ".claude-mem" / "settings.json"


def ensure_llm_env() -> None:
    """Agents spawn MCP servers with a bare env. Fill missing LLM settings
    from the machine's claude-mem config (same user, same purpose).
    Key material stays in-process, never logged."""
    if os.getenv("LLM_API_KEY"):
        return
    try:
        cfg = json.loads(_CMEM_SETTINGS.read_text())
    except Exception:
        return
    key = cfg.get("CLAUDE_MEM_OPENROUTER_API_KEY", "")
    if not key:
        return
    os.environ.setdefault("LLM_API_KEY", key)
    os.environ.setdefault("LLM_PROVIDER", "custom")
    os.environ.setdefault("LLM_MODEL", "openrouter/openai/gpt-4o-mini")
    os.environ.setdefault("LLM_ENDPOINT", "https://openrouter.ai/api/v1")
    os.environ.setdefault("EMBEDDING_PROVIDER", "custom")
    os.environ.setdefault("EMBEDDING_MODEL", "openrouter/openai/text-embedding-3-small")
    os.environ.setdefault("EMBEDDING_API_KEY", key)
    os.environ.setdefault("EMBEDDING_DIMENSIONS", "1536")

_loop: asyncio.AbstractEventLoop | None = None


def _cognee_loop() -> asyncio.AbstractEventLoop:
    """Single background loop for all SDK calls: cognee caches engines and
    locks process-wide, so every coroutine must run on the same loop."""
    global _loop
    if _loop is None:
        _loop = asyncio.new_event_loop()
        threading.Thread(target=_loop.run_forever, daemon=True).start()
    return _loop


def _run(coro, timeout: int = 900):
    return asyncio.run_coroutine_threadsafe(coro, _cognee_loop()).result(timeout)


class CogneeLayer(MemoryLayer):
    name = "cognee"

    def __init__(self, dataset: str = "durable"):
        self.dataset = dataset

    def _sdk(self):
        ensure_llm_env()
        try:
            import cognee
            from cognee.modules.search.types import SearchType
        except ImportError as e:
            raise RuntimeError("cognee not installed: pip install cognee") from e
        return cognee, SearchType

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        cognee, SearchType = self._sdk()
        out = _run(cognee.search(query, query_type=SearchType.GRAPH_COMPLETION,
                                 datasets=[self.dataset], top_k=limit))
        return [Hit(text=getattr(r, "text", str(r)) or "", source=self.name)
                for r in out]

    def add(self, text: str) -> None:
        cognee, _ = self._sdk()
        _run(cognee.remember(text, dataset_name=self.dataset))
