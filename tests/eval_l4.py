"""L4 Structural Code Graph evaluation: indexes a fixture repository whose call
edges are known by construction, then scores the graph against ground truth.

Unlike a smoke test, this measures whether the answers are *correct*: precision
and recall on callers, dependencies and blast radius, across Python, TypeScript
and Go. A parser that silently stops resolving calls shows up as a score drop
rather than as a still-passing assertion.

Zero tokens on the native CodeLayer (stdlib AST + regex, SQLite CTEs).
"""
import argparse
import sys
import tempfile
import time
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agi_memory.layers.code_layer import CodeLayer

# --- Fixture repository. Call edges below are true by construction. ---
FIXTURE = {
    "auth/tokens.py": '''
def decode_token(raw):
    return raw.split(".")

def verify_token(raw):
    parts = decode_token(raw)
    return len(parts) == 3
''',
    "auth/service.py": '''
from auth.tokens import verify_token

class AuthService:
    def __init__(self, secret):
        self.secret = secret

    def authenticate(self, token):
        return verify_token(token)

    def refresh(self, token):
        if self.authenticate(token):
            return issue_token()
        return None

def issue_token():
    return "a.b.c"
''',
    "api/handlers.py": '''
from auth.service import AuthService

def login_handler(request):
    svc = AuthService("secret")
    return svc.authenticate(request["token"])

def refresh_handler(request):
    svc = AuthService("secret")
    return svc.refresh(request["token"])
''',
    "web/client.ts": '''
export function formatUser(user: User): string {
  return user.name;
}

export function renderProfile(user: User): string {
  return formatUser(user);
}

export class ProfilePage {
  render(user: User): string {
    return renderProfile(user);
  }
}
''',
    "svc/worker.go": '''
package svc

func Enqueue(job string) error {
	return persist(job)
}

func persist(job string) error {
	return nil
}
''',
}

# symbol -> callers that must be found (direct or transitive)
EXPECTED_CALLERS = {
    "verify_token": {"authenticate"},
    "decode_token": {"verify_token"},
    "authenticate": {"login_handler", "refresh"},
    "issue_token": {"refresh"},
    "formatUser": {"renderProfile"},
    "renderProfile": {"render"},
    "persist": {"Enqueue"},
}

# symbol -> outbound calls that must be found
EXPECTED_DEPENDENCIES = {
    "verify_token": {"decode_token"},
    "authenticate": {"verify_token"},
    "refresh": {"authenticate", "issue_token"},
    "login_handler": {"AuthService", "authenticate"},
    "Enqueue": {"persist"},
}

# symbol -> symbols that must appear in its blast radius
EXPECTED_IMPACT = {
    "decode_token": {"verify_token", "authenticate"},
    "verify_token": {"authenticate", "login_handler"},
}

EXPECTED_STRUCTURE = {
    "auth/service.py": {"AuthService", "authenticate", "refresh", "issue_token"},
    "web/client.ts": {"formatUser", "renderProfile"},
}


def names(rows, *keys):
    out = set()
    for r in rows:
        for k in keys:
            v = r.get(k)
            if v:
                out.add(str(v).split(".")[-1])
    return out


def score(found: set, expected: set) -> tuple:
    hit = len(found & expected)
    return hit, len(expected)


def main():
    argparse.ArgumentParser(description="Evaluate L4 Structural Code Graph accuracy.").parse_args()

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir) / "repo"
        for rel, body in FIXTURE.items():
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body.lstrip(), encoding="utf-8")

        db = Path(tmp_dir) / "eval_l4.db"
        cl = CodeLayer(db_path=db, project="eval-l4")

        t0 = time.perf_counter()
        res = cl.index_directory(root, project="eval-l4")
        index_ms = (time.perf_counter() - t0) * 1000
        print(f"Indexed {res.get('files_indexed', res.get('indexed', '?'))} files / "
              f"{res.get('symbols', '?')} symbols in {index_ms:.2f}ms\n")

        passes = total = 0
        latencies = []

        for symbol, expected in EXPECTED_CALLERS.items():
            t = time.perf_counter()
            rows = cl.get_callers(symbol, project="eval-l4")
            latencies.append((time.perf_counter() - t) * 1000)
            hit, want = score(names(rows, "caller"), expected)
            passes += hit
            total += want
            print(f"{'PASS' if hit == want else 'FAIL'} {latencies[-1]:6.2f}ms :: "
                  f"callers({symbol}) {hit}/{want}")

        for symbol, expected in EXPECTED_DEPENDENCIES.items():
            t = time.perf_counter()
            rows = cl.get_dependencies(symbol, project="eval-l4")
            latencies.append((time.perf_counter() - t) * 1000)
            hit, want = score(names(rows, "target"), expected)
            passes += hit
            total += want
            print(f"{'PASS' if hit == want else 'FAIL'} {latencies[-1]:6.2f}ms :: "
                  f"dependencies({symbol}) {hit}/{want}")

        for symbol, expected in EXPECTED_IMPACT.items():
            t = time.perf_counter()
            imp = cl.get_impact(symbol, project="eval-l4")
            latencies.append((time.perf_counter() - t) * 1000)
            found = {str(s).split(".")[-1] for s in imp.get("impacted_symbols", [])}
            hit, want = score(found, expected)
            passes += hit
            total += want
            print(f"{'PASS' if hit == want else 'FAIL'} {latencies[-1]:6.2f}ms :: "
                  f"impact({symbol}) {hit}/{want} risk={imp.get('impact_risk', '?')}")

        for rel, expected in EXPECTED_STRUCTURE.items():
            t = time.perf_counter()
            rows = cl.get_structure(rel, project="eval-l4")
            latencies.append((time.perf_counter() - t) * 1000)
            hit, want = score(names(rows, "name", "qualified_name"), expected)
            passes += hit
            total += want
            print(f"{'PASS' if hit == want else 'FAIL'} {latencies[-1]:6.2f}ms :: "
                  f"structure({rel}) {hit}/{want}")

        mean_ms = sum(latencies) / len(latencies)
        print(f"\nL4 Code Graph Score: {passes}/{total} = {passes / total:.0%}, "
              f"mean latency: {mean_ms:.2f}ms")
        sys.exit(0 if passes == total else 1)


if __name__ == "__main__":
    main()
