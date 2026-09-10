# Architecture Invariants

1. Zero external runtime dependencies (Python standard library + SQLite only).
2. Strict layer separation: SessionLayer (L1 SQLite FTS5) + GraphLayer (L2 SQLite CTEs) + Vault (Git-backed JSONL).
3. Code vs Data decoupling: all user data lives in `~/.agent-memory/vault/`, never inside repo.
4. No legacy third-party package names in files.
