"""L2 Knowledge Graph evaluation: ingests curated durable items, quizzes single and multi-hop.
Zero tokens on native GraphLayer (SQLite CTEs).
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

from agi_memory.layers.graph_layer import GraphLayer

ITEMS = [
    "[mobile-app] Haptics Architecture: decided to use two tiny free functions (hapticTap, hapticToggle) rather than a service provider.",
    "[mobile-app] Code Format Rule: code format must target only explicitly changed files; bare repo format once rewrote 66 untouched files.",
    "[mobile-app] TapArea is for custom widgets only; primitive and platform components receive only a haptic callback.",
    "[mobile-app] Stale baseline pattern: pinned audit agents to last commit; fix by refreshing baselines after landing.",
    "[tax-processor] TaxEngine phase 1 scope is personal income tax filing; business bookkeeping deferred.",
    "[tax-processor] TaxEngine becomes the book of record (ledger), not a feeder into external systems.",
    "[tax-processor] Form 16 must not be a separate screen; all documents upload to a single documents screen with OCR.",
    "[tax-processor] TaxEngine intake accepts JSON, XLSX, and PDF files.",
    "[tax-processor] Phase-1 artifact is computation of income feeding tax schedules, not a double-entry ledger.",
    "[tax-processor] Document directive: form-16 is not a separate screen, all client documents go to single documents screen.",
]

QUESTIONS = [
    ("What haptics pattern was chosen?", ["haptictap", "haptictoggle"]),
    ("What is the code format rule?", ["explicitly changed files"]),
    ("What is the TaxEngine phase 1 scope?", ["personal income tax"]),
    ("Should Form 16 be a separate screen?", ["documents screen"]),
    ("The project that chose free haptic functions also had a format incident. What rule resulted?",
     ["explicitly changed files"]),
    ("TaxEngine is the book of record, not a feeder. A feeder into what?",
     ["external systems"]),
]


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def main():
    parser = argparse.ArgumentParser(description="Evaluate L2 Durable Knowledge Graph retrieval.")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp_dir:
        eval_db = Path(tmp_dir) / "eval_l2.db"
        gl = GraphLayer(db_path=eval_db)

        # Ingest items
        t_ingest_start = time.perf_counter()
        for item in ITEMS:
            gl.add(item)
        ingest_time = (time.perf_counter() - t_ingest_start) * 1000

        print(f"Ingested {len(ITEMS)} items into native Knowledge Graph in {ingest_time:.2f}ms\n")

        passes = 0
        latencies = []
        for q, exp in QUESTIONS:
            t0 = time.perf_counter()
            hits = gl.search(q, limit=5)
            lat_ms = (time.perf_counter() - t0) * 1000
            latencies.append(lat_ms)

            blob = norm(" ".join(h.text for h in hits))
            ok = any(norm(e) in blob for e in exp)
            if ok:
                passes += 1
            status = "PASS" if ok else "FAIL"
            print(f"{status} {lat_ms:6.2f}ms :: {q[:65]}")

        acc = passes / len(QUESTIONS)
        mean_ms = sum(latencies) / len(latencies)
        print(f"\nL2 Knowledge Graph Score: {passes}/{len(QUESTIONS)} = {acc:.0%}, mean latency: {mean_ms:.2f}ms")


if __name__ == "__main__":
    main()
