"""Shared contract for memory layers. Either layer must stay replaceable."""
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

# Multiple agent processes (a session hook, an MCP server, a CLI call) write the
# same SQLite file concurrently. Two settings make that safe, and both must be
# set on every connection or the weakest one becomes the failure:
#   - WAL: readers never block the writer, writers never block readers.
#   - busy_timeout: a writer waits for the lock instead of raising immediately.
# The sqlite3 default is 5s with rollback-journal locking, which loses writes
# under fan-out on slower filesystems (Windows CI reproduces this at 8 writers).
BUSY_TIMEOUT_S = float(os.environ.get("AGI_MEMORY_BUSY_TIMEOUT", "30"))


def open_db(db_path: Path | str, readonly: bool = False) -> sqlite3.Connection:
    """Open the memory database with WAL and a real busy timeout.

    Every connection in every layer goes through here — a single unconfigured
    connection is enough to reintroduce "database is locked" for all of them.
    """
    if readonly:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True,
                              timeout=BUSY_TIMEOUT_S)
    else:
        con = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_S)
    try:
        con.execute(f"PRAGMA busy_timeout = {int(BUSY_TIMEOUT_S * 1000)}")
        if not readonly:
            # WAL is a persistent property of the file, but setting it is cheap
            # and self-heals a database created before this helper existed.
            con.execute("PRAGMA journal_mode = WAL")
            con.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.Error:
        # A corrupt or locked file must still return a connection: callers
        # degrade to no hits rather than raising out of a read path.
        pass
    return con


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

# --- Query expansion -----------------------------------------------------------
# L1 gets stemming from SQLite's porter tokenizer. L2/L3 match with LIKE and
# prefix queries against no such index, so they stem in Python instead. Used
# only as a FALLBACK after exact matching finds nothing, so a loosened term can
# never outrank a real one.

# Longest first: "authentication" must lose "ation", not "ion".
_SUFFIXES = (
    "izations", "isations", "ization", "isation", "ements", "ations", "ement",
    "ments", "ation", "ition", "ingly", "edly", "ness", "ment", "tion", "sion",
    "able", "ible", "ance", "ence", "ate", "ing", "ers", "ies", "ed", "es",
    "ly", "er", "or", "al", "s", "e",
)
_MIN_STEM = 4


def stem_word(word: str, min_stem: int = _MIN_STEM) -> str:
    """Strip one common suffix, conservatively.

    Deliberately crude and shared by L2/L3: "authenticate" and "authentication"
    both reduce to "authentic", which is all a prefix match needs. A stem
    shorter than min_stem is rejected, because over-stripping turns a precise
    query into a wildcard.
    """
    w = str(word).lower()
    if len(w) <= min_stem:
        return w
    for suffix in _SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= min_stem:
            return w[: -len(suffix)]
    return w


def stem_terms(terms) -> list:
    """Stems that differ from their source term, de-duplicated, order preserved."""
    out = []
    for t in terms:
        st = stem_word(t)
        if st != str(t).lower() and st not in out:
            out.append(st)
    return out
