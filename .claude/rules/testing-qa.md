# Testing & QA Verification

Before committing, run:
```bash
python3 tests/test_offline.py && python3 tests/eval_l1.py && python3 tests/eval_l2.py \
  && python3 tests/eval_l3.py && python3 tests/eval_l4.py && agi-integrate test
```
Target: 100% offline, 0 errors, 10/10 L1, 6/6 L2, 10/10 L3, 25/25 L4.
