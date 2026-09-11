# /test Playbook

Run the complete offline test suite for `agi-memory`:

```bash
python3 tests/test_offline.py && python3 tests/eval_l1.py && python3 tests/eval_l2.py && agi-integrate test
python3 tests/stress_test.py
```

Expected outcome:
- Unit & layer tests: 0 errors (all 14 test suites passing)
- L1 Score: 10/10 (100%), latency < 2ms
- L2 Score: 6/6 (100%), latency < 0.5ms
- MCP Handshake: 15/15 tools registered
- Stress test: All 12 evaluation tiers passing (>500 QPS peak throughput)
