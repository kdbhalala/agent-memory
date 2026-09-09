"""L1 stress test: 10 questions with answers verified in claude-mem DB.
Local retrieval only — zero LLM calls. Grades substring match + latency.
"""
import json
import re
import time

from layers.claudemem import ClaudeMemLayer

# (project, question, expected substrings) — all verified in DB 2026-09-06
QUESTIONS = [
    ("flutter_tvlr_app", "What was decided about haptics, service or functions?",
     ["haptictap", "haptictoggle"]),
    ("flutter_tvlr_app", "What is the rule about dart format?",
     ["explicitly changed files"]),
    ("flutter_tvlr_app", "What went wrong with bare dart format lib?",
     ["66 files"]),
    ("flutter_tvlr_app", "TapArea for custom widgets, what about lgw primitives?",
     ["haptic callback"]),
    ("flutter_tvlr_app", "What is the audit-agent-stale-baseline pattern?",
     ["pinned", "last commit"]),
    ("ca-statement-processor", "What is Legix phase 1 scope?",
     ["personal income tax filing"]),
    ("ca-statement-processor", "Should Form 16 be a separate screen in Legix?",
     ["single documents screen"]),
    ("ca-statement-processor", "Is Legix the ledger or a feeder into Tally?",
     ["book of record"]),
    ("ca-statement-processor", "What intake file types does Legix accept?",
     ["json", "xlsx", "pdf"]),
    ("ca-statement-processor", "Ledger vs computation: what is the phase-1 artifact?",
     ["computation of income"]),
]


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def main():
    layers = {}
    rows = []
    for proj, q, exp in QUESTIONS:
        layers.setdefault(proj, ClaudeMemLayer(project=proj))
        t = time.perf_counter()
        hits = layers[proj].search(q, limit=5)
        lat = round(time.perf_counter() - t, 2)
        blob = norm(" ".join(h.text for h in hits))
        ok = all(norm(e) in blob for e in exp)
        rows.append({"q": q, "ok": ok, "lat": lat})
        print(f"{'PASS' if ok else 'FAIL'} {lat:5.2f}s :: {q[:60]}", flush=True)

    acc = sum(r["ok"] for r in rows) / len(rows)
    mean = sum(r["lat"] for r in rows) / len(rows)
    print(f"\nL1: {sum(r['ok'] for r in rows)}/{len(rows)} = {acc:.0%}, mean {mean:.2f}s")
    json.dump(rows, open("results_l1.json", "w"), indent=1)
    for r in rows:
        if not r["ok"]:
            print("MISS:", r["q"])


if __name__ == "__main__":
    main()
