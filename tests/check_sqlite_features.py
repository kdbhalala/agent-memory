"""Report which SQLite FTS5 tokenizers this interpreter can actually create.

Python builds link wildly different SQLite versions across platforms, and the
`trigram` tokenizer needs 3.34+. Before committing to typo-tolerant search we
need to know whether every supported platform can create these indexes at all,
otherwise the feature fails on a user's machine rather than in CI.

Report-only: prints what it finds and always exits 0. It is a probe, not a gate
-- failing the build here would only tell us what we are trying to learn.
"""
import platform
import sqlite3
import sys

TOKENIZERS = ["unicode61", "porter unicode61", "trigram", "ascii"]


def main() -> None:
    print(f"platform      : {platform.system()} {platform.machine()}")
    print(f"python        : {sys.version.split()[0]}")
    print(f"sqlite3 lib   : {sqlite3.sqlite_version}")

    con = sqlite3.connect(":memory:")
    compile_opts = []
    try:
        compile_opts = [r[0] for r in con.execute("PRAGMA compile_options").fetchall()]
    except sqlite3.Error:
        pass
    print(f"FTS5 compiled : {'ENABLE_FTS5' in compile_opts}")

    supported = []
    for idx, tok in enumerate(TOKENIZERS):
        name = f"probe_{idx}"
        try:
            con.execute(f"CREATE VIRTUAL TABLE {name} USING fts5(x, tokenize='{tok}')")
            con.execute(f"INSERT INTO {name}(x) VALUES ('authentication tokens')")
            # A tokenizer that creates but cannot match is no use to us.
            hit = con.execute(
                f"SELECT count(*) FROM {name} WHERE {name} MATCH ?",
                ("authentication",)).fetchone()[0]
            status = "OK" if hit else "CREATED BUT NO MATCH"
            if hit:
                supported.append(tok)
        except sqlite3.Error as e:
            status = f"UNAVAILABLE ({e})"
        print(f"  {tok:<18} {status}")

    # The two that decide whether stemming and typo-tolerance are viable.
    print()
    print(f"stemming viable (porter) : {'porter unicode61' in supported}")
    print(f"typo-tolerance viable (trigram): {'trigram' in supported}")


if __name__ == "__main__":
    main()
