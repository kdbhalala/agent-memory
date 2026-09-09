"""Offline checks: no LLM, no network (except localhost worker for L1 live test)."""
from layers.base import Hit, MemoryLayer
from recall import recall


class FakeL1(MemoryLayer):
    name = "fake-l1"

    def __init__(self, hits):
        self._hits = hits

    def search(self, query, limit=5):
        return self._hits[:limit]


class FakeL2(MemoryLayer):
    name = "fake-l2"
    calls = 0

    def search(self, query, limit=5):
        FakeL2.calls += 1
        return [Hit(text="durable fact", source=self.name)]

    def add(self, text):
        if not hasattr(self, "added"):
            self.added = []
        self.added.append(text)


# L2 skipped when L1 is sufficient
FakeL2.calls = 0
r = recall("q", FakeL1([Hit(text="a", source="x"), Hit(text="b", source="x")]),
           FakeL2())
assert len(r["recent"]) == 2 and r["durable"] == [] and FakeL2.calls == 0

# L2 fires when L1 thin, and on deep=True
FakeL2.calls = 0
r = recall("q", FakeL1([]), FakeL2())
assert len(r["durable"]) == 1 and FakeL2.calls == 1
r = recall("q", FakeL1([Hit(text="a", source="x")] * 5), FakeL2(), deep=True)
assert FakeL2.calls == 2

# L2 missing (RuntimeError) degrades gracefully
class DeadL2(MemoryLayer):
    name = "dead"
    def search(self, query, limit=5):
        raise RuntimeError("nope")
r = recall("q", FakeL1([]), DeadL2())
assert r["durable"] == []

# promote filter + dedupe with fake L2 (state redirected to /tmp)
import promote
from pathlib import Path
promote.STATE = Path("/tmp/promote-test-state.json")
if promote.STATE.exists():
    promote.STATE.unlink()
cands = promote.collect()
print(f"collect candidates from real DB: {len(cands)}")
fake = FakeL2()
fresh = promote.promote(fake)
assert len(fresh) == len(cands) and len(getattr(fake, "added", [])) == len(cands)
assert promote.promote(fake) == [], "second run must promote nothing"

# _bodies_by_id preserves rank order
from layers.claudemem import ClaudeMemLayer
cm = ClaudeMemLayer()
test_ids = ["13891", "13791"]
h_order = cm._bodies_by_id(test_ids)
assert [h.ref for h in h_order] == test_ids, f"Order mismatch: {[h.ref for h in h_order]} vs {test_ids}"
rev_ids = ["13791", "13891"]
h_rev = cm._bodies_by_id(rev_ids)
assert [h.ref for h in h_rev] == rev_ids, f"Reversed order mismatch: {[h.ref for h in h_rev]} vs {rev_ids}"

print("layers OK")
