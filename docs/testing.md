# Running Evaluations & Tests

All tests run completely offline with zero API keys or external services.

## Scored evaluations — one per cognitive pillar

Each layer has its own graded suite reporting retrieval accuracy and latency, so
a regression shows up as a score drop rather than a still-passing assertion.

```bash
python3 tests/eval_l1.py   # L1 Epistemic:  working-memory recall      (10/10)
python3 tests/eval_l2.py   # L2 Semantic:   multi-hop graph traversal  (6/6)
python3 tests/eval_l3.py   # L3 Episodic:   session-history recall     (10/10)
python3 tests/eval_l4.py   # L4 Code Graph: callers/deps/impact vs a
                           #                fixture repo with known edges (25/25)
```

`eval_l3.py` seeds a multi-project session history and asks the questions a
developer asks between sessions ("what did I do about X"), then checks that
timelines stay project-scoped and that the recap names the most recent session.

`eval_l4.py` indexes a fixture repository whose call edges are true by
construction — Python, TypeScript and Go — and scores callers, dependencies,
blast radius and structure against that ground truth. Each eval exits non-zero
on any miss, so CI fails on an accuracy regression.

## Functional, adversarial and load suites

```bash
# Unit & layer tests, doc parity, tool registration
python3 tests/test_offline.py

# Verify stdio MCP server protocol handshake across all 15 tools
agi-integrate test

# Adversarial robustness: corrupt databases, hostile input, concurrency
python3 tests/chaos_test.py

# Comprehensive authentic production stress test
python3 tests/stress_test.py
```

## Full pre-commit chain

```bash
python3 tests/test_offline.py \
  && python3 tests/eval_l1.py && python3 tests/eval_l2.py \
  && python3 tests/eval_l3.py && python3 tests/eval_l4.py \
  && agi-integrate test \
  && python3 tests/chaos_test.py && python3 tests/stress_test.py
```

---
