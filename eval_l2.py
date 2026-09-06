"""L2 stress test: ingest 10 curated durable items, quiz 6 (4 single + 2 multi-hop).
Costs ~$0.001 on paid mini. Needs LLM_API_KEY + OpenRouter endpoint in env.
"""
import asyncio
import json
import os
import re
import time

ITEMS = [
    "[flutter_tvlr_app] Haptics decision: use two tiny free functions (hapticTap, hapticToggle) rather than a haptics service or provider.",
    "[flutter_tvlr_app] Format rule: dart format must target only explicitly changed files; bare dart format lib once rewrote 66 untouched files.",
    "[flutter_tvlr_app] TapArea is for custom widgets only; lgw primitives and platform widgets get only a haptic callback.",
    "[flutter_tvlr_app] Stale-baseline pattern: mid-session agents re-report landed work because baselines pin to last commit; fix by refreshing baselines after landing.",
    "[ca-statement-processor] Legix phase 1 scope is personal income tax filing; business bookkeeping deferred.",
    "[ca-statement-processor] Legix becomes the book of record (the ledger), not a feeder into Tally.",
    "[ca-statement-processor] Form 16 must not be a separate screen; CAs upload everything to one Documents screen with OCR and categorization stages.",
    "[ca-statement-processor] Legix intake accepts JSON, XLSX, TXT and PDF files.",
    "[ca-statement-processor] Phase-1 artifact is a computation of income feeding ITR schedules, not a double-entry ledger.",
    "[ca-statement-processor] CA directive: form-16 is not a separate screen, all client documents go to Documents.",
]

QUESTIONS = [
    ("What haptics pattern was chosen?", ["haptictap", "haptictoggle"]),
    ("What is the dart format rule?", ["explicitly changed files"]),
    ("What is the Legix phase 1 scope?", ["personal income tax"]),
    ("Should Form 16 be a separate screen?", ["documents screen"]),
    ("The project that chose free haptic functions also had a format incident. What rule resulted?",
     ["explicitly changed files"]),
    ("Legix is the book of record, not a feeder. A feeder into what?",
     ["tally"]),
]


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


async def main():
    from layers.cognee_layer import CogneeLayer
    l2 = CogneeLayer(dataset="durable_eval")
    import cognee
    try:
        await cognee.forget(dataset="durable_eval")
    except Exception:
        pass
    t = time.perf_counter()
    for it in ITEMS:
        l2.add(it)
    print(f"ingested {len(ITEMS)} items in {time.perf_counter()-t:.0f}s", flush=True)
    rows = []
    for q, exp in QUESTIONS:
        t = time.perf_counter()
        try:
            hits = l2.search(q, limit=5)
            ans = " ".join(h.text for h in hits)
            ok, err = all(norm(e) in norm(ans) for e in exp), None
        except Exception as e:
            ans, ok, err = "", False, type(e).__name__
        lat = round(time.perf_counter() - t, 1)
        rows.append({"q": q, "ok": ok, "lat": lat, "err": err,
                     "ans": ans[:300]})
        print(f"{'PASS' if ok else 'FAIL'} {lat:.0f}s :: {q[:60]}", flush=True)
    acc = sum(r["ok"] for r in rows) / len(rows)
    print(f"\nL2: {sum(r['ok'] for r in rows)}/{len(rows)} = {acc:.0%}")
    out = os.getenv("EVAL_OUT", "results_l2.json")
    json.dump(rows, open(out, "w"), indent=1)
    await cognee.forget(dataset="durable_eval")


if __name__ == "__main__":
    asyncio.run(main())
