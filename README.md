# agent-memory — two-layer AI memory

* **L1 `claude-mem`** (`layers/claudemem.py`): session history, tool actions,
  decisions. Read via local worker HTTP, SQLite FTS fallback. Primary memory.
* **L2 `cognee`** (`layers/cognee_layer.py`): durable knowledge only
  (architecture, decisions, reusable fixes). Lazy import — L1 works without it.

```python
from layers.claudemem import ClaudeMemLayer
from layers.cognee_layer import CogneeLayer
from recall import recall

r = recall("auth bug", ClaudeMemLayer(), CogneeLayer())  # L2 only if L1 thin
r = recall("auth bug", ClaudeMemLayer(), CogneeLayer(), deep=True)  # force L2
```

Promote session learnings to durable storage (dedupe via `promoted.json`):

```python
from layers.cognee_layer import CogneeLayer
from promote import promote
promote(CogneeLayer(), project="my-repo")  # session summaries + durable concepts only
```

Either layer implements `layers/base.py::MemoryLayer` — replaceable.
