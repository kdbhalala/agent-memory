"""Degraded-query evaluation: how much recall is lost when a question is
phrased the way a real agent phrases it, rather than the way the memory was
written.

This measures a baseline, it does not assert one. Each probe first runs the
EXACT query; only if that hits is the degraded variant counted, so the number
reported is the loss caused by degradation and not a pre-existing miss.

Categories, in increasing distance from string matching:

  morphological  authenticate      <- authentication      (stemming)
  typo           autentication     <- authentication      (edit distance)
  identifier     get_user_by_id    <- getUserById         (tokenization)
  abbreviation   cfg               <- configuration       (alias)
  paraphrase     login             <- authentication      (semantics)

Only the first three are reachable by fuzzy string matching. Paraphrase is
listed to show what fuzz can NOT buy: it needs curated aliases or host-side
query expansion, not a looser matcher.
"""
import argparse
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agi_memory.layers.session_layer import SessionLayer
from agi_memory.layers.graph_layer import GraphLayer
from agi_memory.layers.episodic_layer import EpisodicLayer
from agi_memory.layers.code_layer import CodeLayer

# --- corpus -------------------------------------------------------------------

MEMORIES = [
    ("Auth migration", "Migrated authentication to short-lived JWT tokens issued by the auth service."),
    ("Pricing responses", "Responses are cached in Redis with a 300 second expiration on the pricing endpoint."),
    ("Retry strategy", "Outbound webhooks retry with exponential backoff, capped at five attempts."),
    ("Schema decision", "Subscription records are normalized into a separate billing table."),
    ("Deployment", "Containers are deployed to Kubernetes with a rolling update strategy."),
    ("Configuration", "Environment configuration is loaded from a single settings module at startup."),
]

# (exact query that should hit, {category: degraded variant})
PROBES = [
    # Every degraded query below is checked by test_probe_hygiene() to share no
    # word stem with the corpus, so a hit means the matcher bridged the gap
    # rather than the probe leaking a literal corpus word.
    ("authentication", {
        "morphological": "authenticate",
        "typo": "autentication",
        "paraphrase": "login",
    }),
    ("cached", {
        "morphological": "caching",
        "typo": "cachd",
        "paraphrase": "memoization",
    }),
    ("retry", {
        "morphological": "retrying",
        "typo": "rety",
        "paraphrase": "resend",
    }),
    ("normalized", {
        "morphological": "normalize",
        "typo": "normlized",
        "paraphrase": "decomposition",
    }),
    ("Kubernetes", {
        "typo": "Kubernets",
        "abbreviation": "k8s",
        "paraphrase": "node pool",
    }),
    ("configuration", {
        "morphological": "configure",
        "typo": "configuartion",
        "abbreviation": "cfg",
        "paraphrase": "tunables",
    }),
]

CODE_FIXTURE = {
    # Only snake_case is defined. Querying the camelCase spelling must therefore
    # be a real fuzzy lookup, not a hit on a different symbol that happens to exist.
    "svc/users.py": "def get_user_by_id(uid):\n    return uid\n\n"
                    "def load_profile(uid):\n    return get_user_by_id(uid)\n",
}

# (exact symbol that resolves, {category: degraded spelling})
CODE_PROBES = [
    ("get_user_by_id", {
        "identifier": "getUserById",
        "typo": "get_user_by_i",
        "morphological": "get_users_by_id",
    }),
]


def test_probe_hygiene() -> list:
    """Reject probes that would measure nothing.

    The rule differs by category, because the categories ask different things:

      morphological / typo  a shared stem is THE POINT ("authenticate" vs
                            "authentication"), so only a verbatim corpus word
                            is disqualifying -- that would be an exact match
                            wearing a costume.
      abbreviation /        the matcher has to bridge a gap no stemmer can, so
      paraphrase            sharing any stem with the corpus means a hit proves
                            nothing about semantics.

    The first two runs of this file reported 100% on categories that were in
    fact measuring corpus leakage, which is why this check exists.
    """
    corpus = " ".join(f"{t} {b}" for t, b in MEMORIES).lower()
    corpus_words = set(re.findall(r"[a-z0-9]+", corpus))
    leaks = []
    for exact, variants in PROBES:
        for category, degraded in variants.items():
            tokens = re.findall(r"[a-z0-9]+", degraded.lower())
            if degraded.lower() == exact.lower():
                leaks.append(f"{category}: {degraded!r} is identical to the exact query")
                continue
            if category in ("morphological", "typo"):
                verbatim = [t for t in tokens if t in corpus_words]
                if verbatim:
                    leaks.append(f"{category}: {degraded!r} appears verbatim in the corpus "
                                 f"({verbatim[0]!r}) -- that is an exact match, not a degradation")
                continue
            for token in tokens:
                shared = next((w for w in corpus_words
                               if len(token) >= 4 and len(w) >= 4
                               and (token.startswith(w[:4]) or w.startswith(token[:4]))), None)
                if shared:
                    leaks.append(f"{category}: {degraded!r} shares a stem with corpus word {shared!r}")
                    break
    return leaks


def probe(fn, query: str) -> bool:
    try:
        return bool(fn(query))
    except Exception:
        return False


def main():
    argparse.ArgumentParser(description="Measure recall loss on degraded queries.").parse_args()
    leaks = test_probe_hygiene()
    if leaks:
        print("\nPROBE HYGIENE FAILURE -- these would measure nothing:")
        for l in leaks:
            print(f"  - {l}")
        sys.exit(2)

    results = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # layer -> cat -> [hits, eligible]
    skipped = []

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "fuzzy.db"

        l1 = SessionLayer(db_path=db, project="fuzz")
        gl = GraphLayer(db_path=Path(tmp) / "fuzzy_l2.db")
        for title, body in MEMORIES:
            l1.record(body, title=title, project="fuzz")
            gl.add(f"[fuzz] {title}: {body}")

        ep_db = Path(tmp) / "fuzzy_l3.db"
        for title, body in MEMORIES:
            ep = EpisodicLayer(db_path=ep_db, project="fuzz")
            sid = ep.start_session(project="fuzz", goal=title)["session_id"]
            ep.end_session(sid, summary=body, project="fuzz")
        ep = EpisodicLayer(db_path=ep_db, project="fuzz")

        layers = [
            ("L1 epistemic", lambda q: l1.search(q, limit=5)),
            ("L2 semantic", lambda q: gl.search(q, limit=5)),
            ("L3 episodic", lambda q: ep.search(q, limit=5)),
        ]

        for layer_name, fn in layers:
            for exact, variants in PROBES:
                if not probe(fn, exact):
                    skipped.append(f"{layer_name}: exact {exact!r} already misses")
                    continue
                for category, degraded in variants.items():
                    hit = probe(fn, degraded)
                    results[layer_name][category][0] += hit
                    results[layer_name][category][1] += 1

        # L4 works on symbol names, so it gets identifier-shape probes
        root = Path(tmp) / "repo"
        for rel, body in CODE_FIXTURE.items():
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body, encoding="utf-8")
        cl = CodeLayer(db_path=Path(tmp) / "fuzzy_l4.db", project="fuzz")
        cl.index_directory(root, project="fuzz")
        cl_fn = lambda q: cl.get_callers(q, project="fuzz")

        for exact, variants in CODE_PROBES:
            if not probe(cl_fn, exact):
                skipped.append(f"L4 code graph: exact {exact!r} already misses")
                continue
            for category, degraded in variants.items():
                hit = probe(cl_fn, degraded)
                results["L4 code graph"][category][0] += hit
                results["L4 code graph"][category][1] += 1

    categories = ["morphological", "typo", "identifier", "abbreviation", "paraphrase"]
    print("\nRecall on degraded queries (exact form verified to hit first)\n")
    header = f"{'Layer':<16}" + "".join(f"{c[:13]:>15}" for c in categories)
    print(header)
    print("-" * len(header))
    totals = defaultdict(lambda: [0, 0])
    for layer in ("L1 epistemic", "L2 semantic", "L3 episodic", "L4 code graph"):
        row = f"{layer:<16}"
        for cat in categories:
            hits, elig = results[layer][cat]
            if not elig:
                row += f"{'-':>15}"
                continue
            totals[cat][0] += hits
            totals[cat][1] += elig
            row += f"{f'{hits}/{elig} ({hits / elig:.0%})':>15}"
        print(row)
    print("-" * len(header))
    row = f"{'ALL':<16}"
    for cat in categories:
        hits, elig = totals[cat]
        row += f"{f'{hits}/{elig} ({hits / elig:.0%})':>15}" if elig else f"{'-':>15}"
    print(row + "\n")

    if skipped:
        print("Skipped (exact query already missed, degradation not measurable):")
        for s in skipped:
            print(f"  - {s}")
        print()

    overall_hits = sum(h for h, _ in totals.values())
    overall_elig = sum(e for _, e in totals.values())
    print(f"Baseline degraded-query recall: {overall_hits}/{overall_elig} "
          f"= {overall_hits / overall_elig:.0%}\n")
    print("Report-only: this measures the gap, it does not gate CI.")


if __name__ == "__main__":
    main()
