# Python API

```python
from agi_memory.layers.session_layer import SessionLayer
from agi_memory.layers.graph_layer import GraphLayer
from agi_memory.layers.episodic_layer import EpisodicLayer
from agi_memory.layers.code_layer import CodeLayer
from agi_memory.recall import recall
from agi_memory.bootstrap import bootstrap_project

l1 = SessionLayer(project="my-app")
l2 = GraphLayer(project="my-app")
l3 = EpisodicLayer(project="my-app")
l4 = CodeLayer(project="my-app")

# 1. Epistemic: Save a decision with in-flight graph triples and conflict detection
res = l1.record(
    text="Always use secure_storage for JWT tokens on mobile",
    title="JWT Storage Rule",
    category="architecture",
    supersedes="#101"
)

# 2. Semantic: Ingest relations into L2 graph directly
l2.add_edge("AuthService", "USES", "SecureStorage", "AuthService persists tokens in SecureStorage")

# Fast L1 working memory search (<2ms)
search_hits = l1.search("JWT tokens")

# Deep multi-hop graph recall (0.28ms)
deep_res = recall("auth storage", l1, l2, deep=True)

# 3. Episodic: Session timeline & cross-session recap (<0.25ms)
sessions = l3.get_timeline(limit=5)
recap = l3.format_session_recap()

# 4. Structural: Code graph indexing, caller lookups, and blast-radius (<0.5ms)
l4.index_directory("src")
callers = l4.get_callers("SessionLayer")
deps = l4.get_dependencies("recall")
blast_radius = l4.impact_analysis("SessionLayer")

# Cold-start memory bootstrapping from Git history, README, and code symbols
boot_res = bootstrap_project(repo_dir=".", max_commits=20, project="my-app")
```

---
