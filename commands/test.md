# /test Playbook

Run the complete offline test suite for `agent-memory`:

```bash
python3 test_offline.py && python3 eval_l1.py && python3 eval_l2.py && python3 integrate.py test
python3 stress_test.py
```

Expected outcome:
- Unit & layer tests: 0 errors (all 12 test suites passing)
- L1 Score: 10/10 (100%), latency < 2ms
- L2 Score: 6/6 (100%), latency < 0.5ms
- MCP Handshake: 9/9 tools registered
- Stress test: >1,000 QPS peak multi-agent throughput
