"""L3 Episodic Session History evaluation: seeds a realistic multi-project
session history, then asks the questions a developer actually asks between
sessions -- "what did I do about X", "which session touched this file".

Scored the same way as eval_l1/eval_l2: retrieval accuracy plus latency, so a
regression in episodic recall shows up as a number rather than a pass/fail.
Zero tokens on the native EpisodicLayer (SQLite).
"""
import argparse
import re
import sys
import tempfile
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agi_memory.layers.episodic_layer import EpisodicLayer

# (project, goal, summary, touched_files, commits)
SESSIONS = [
    ("mobile-app", "Replace haptics service with free functions",
     "Removed HapticService provider; shipped hapticTap and hapticToggle as free functions.",
     ["lib/haptics/haptic_functions.dart", "lib/widgets/tap_area.dart"], ["a1b2c3d"]),
    ("mobile-app", "Stop formatter rewriting untouched files",
     "Scoped dart format to changed files only after a bare run rewrote 66 untouched files.",
     ["tools/format.sh", ".github/workflows/ci.yml"], ["b2c3d4e"]),
    ("mobile-app", "Fix stale audit baselines",
     "Audit agents were pinned to an old commit; baselines now refresh after each landing.",
     ["tools/audit/baseline.py"], ["c3d4e5f"]),
    ("tax-processor", "Scope phase 1 to personal income tax",
     "Deferred business bookkeeping; phase 1 covers personal income tax filing only.",
     ["docs/scope.md", "src/engine/schedules.py"], ["d4e5f6a"]),
    ("tax-processor", "Make TaxEngine the book of record",
     "TaxEngine becomes the ledger rather than a feeder into external systems.",
     ["src/engine/ledger.py"], ["e5f6a7b"]),
    ("tax-processor", "Unify document intake",
     "Form 16 is no longer a separate screen; all documents upload to one OCR screen.",
     ["src/ui/documents_screen.py", "src/ocr/intake.py"], ["f6a7b8c"]),
    ("agi-memory", "Harden layers against corrupt databases",
     "Reads now degrade to no hits instead of raising when the SQLite file is corrupt.",
     ["src/agi_memory/layers/graph_layer.py", "src/agi_memory/layers/session_layer.py"], ["a7b8c9d"]),
    ("agi-memory", "Fix vault compaction destroying observations",
     "Semantic dedupe keyed on a truncated prefix and deleted distinct observations.",
     ["src/agi_memory/vault.py"], ["b8c9d0e"]),
]

# (query, project filter, expected substrings -- any one counts as a hit)
QUESTIONS = [
    ("haptics free functions", "mobile-app", ["haptictap", "haptictoggle"]),
    ("formatter rewrote untouched files", "mobile-app", ["changed files only", "66 untouched"]),
    ("audit baselines stale", "mobile-app", ["refresh after each landing", "pinned to an old commit"]),
    ("phase 1 scope personal income tax", "tax-processor", ["personal income tax"]),
    ("is TaxEngine a ledger or a feeder", "tax-processor", ["book of record", "ledger"]),
    ("form 16 separate screen", "tax-processor", ["one ocr screen", "no longer a separate screen"]),
    ("corrupt database reads", "agi-memory", ["degrade to no hits"]),
    ("vault compaction data loss", "agi-memory", ["truncated prefix", "distinct observations"]),
]


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def main():
    argparse.ArgumentParser(description="Evaluate L3 Episodic Session History recall.").parse_args()

    with tempfile.TemporaryDirectory() as tmp_dir:
        eval_db = Path(tmp_dir) / "eval_l3.db"

        t_ingest = time.perf_counter()
        for project, goal, summary, files, commits in SESSIONS:
            ep = EpisodicLayer(db_path=eval_db, project=project)
            sid = ep.start_session(project=project, goal=goal)["session_id"]
            ep.end_session(sid, summary=summary, touched_files=files,
                           commits=commits, project=project)
        ingest_ms = (time.perf_counter() - t_ingest) * 1000
        print(f"Recorded {len(SESSIONS)} sessions into episodic history in {ingest_ms:.2f}ms\n")

        passes = 0
        latencies = []
        for query, project, expected in QUESTIONS:
            ep = EpisodicLayer(db_path=eval_db, project=project)
            t0 = time.perf_counter()
            hits = ep.search(query, limit=5)
            lat_ms = (time.perf_counter() - t0) * 1000
            latencies.append(lat_ms)

            blob = norm(" ".join(h.text for h in hits))
            ok = any(norm(e) in blob for e in expected)
            passes += ok
            print(f"{'PASS' if ok else 'FAIL'} {lat_ms:6.2f}ms :: {query[:60]}")

        # Timelines must stay project-scoped and newest-first, or cross-project
        # history bleeds into a session briefing.
        ep = EpisodicLayer(db_path=eval_db, project="tax-processor")
        timeline = ep.get_timeline(project="tax-processor", limit=10)
        scoped = len(timeline) == 3 and all(s.get("project") == "tax-processor" for s in timeline)
        passes += scoped
        print(f"{'PASS' if scoped else 'FAIL'}          :: timeline is project-scoped "
              f"({len(timeline)} sessions, expected 3)")

        recap = EpisodicLayer.format_recap(timeline[0] if timeline else None)
        has_recap = "Unify document intake" in recap or "documents" in recap.lower()
        passes += has_recap
        print(f"{'PASS' if has_recap else 'FAIL'}          :: latest recap names the most recent session")

        total = len(QUESTIONS) + 2
        mean_ms = sum(latencies) / len(latencies)
        print(f"\nL3 Episodic History Score: {passes}/{total} = {passes / total:.0%}, "
              f"mean latency: {mean_ms:.2f}ms")
        sys.exit(0 if passes == total else 1)


if __name__ == "__main__":
    main()
