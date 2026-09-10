# /test Playbook

Run the complete offline test suite for `agent-memory`:

```bash
python3 test_offline.py && python3 eval_l1.py && python3 eval_l2.py && python3 integrate.py test
```

Expected outcome:
- Unit & layer tests: 0 errors
- L1 Score: 10/10 (100%), latency < 5ms
- L2 Score: 6/6 (100%), latency < 1ms
- MCP Handshake: 8/8 tools registered

To run the comprehensive 11-tier authentic stress test benchmark:
```bash
python3 stress_test.py
```
