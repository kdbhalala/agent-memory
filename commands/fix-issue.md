# /fix-issue Playbook

Standard workflow for investigating and fixing issues in `agent-memory`:

1. **Recall Prior Precedents**:
   ```bash
   python3 recall.py "<keywords>" --project agent-memory --deep
   ```
2. **Reproduce Offline**:
   - Write a minimal failing test case in `test_offline.py`.
3. **Implement Fix**:
   - Apply fix in `layers/`, `vault.py`, `sync.py`, or `integrate.py`.
   - Maintain strict standard-library-only discipline.
4. **Verify**:
   ```bash
   python3 test_offline.py && python3 eval_l1.py && python3 eval_l2.py && python3 integrate.py test
   ```
5. **Record Learning**:
   - Call `memory_record(text="...", title="Root cause & fix", project="agent-memory")` so other assistants know about the fix.
