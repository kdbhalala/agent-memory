# /fix-issue Playbook

Standard workflow for investigating and fixing issues in `agent-memory`:

1. **Recall Prior Precedents**:
   ```bash
   agi-recall "<keywords>" --project agi-memory --deep
   ```
2. **Reproduce Offline**:
   - Write a minimal failing test case in `tests/test_offline.py`.
3. **Implement Fix**:
   - Apply fix in `src/agi_memory/`.
   - Maintain strict standard-library-only discipline.
4. **Verify**:
   ```bash
   python3 tests/test_offline.py && python3 tests/eval_l1.py && python3 tests/eval_l2.py && agi-integrate test && python3 tests/stress_test.py
   ```
5. **Record Learning**:
   - Call `memory_record(text="...", title="Root cause & fix", project="agent-memory", category="bugfix", supersedes="...", relations=[...])` so all coding assistants recall the fix and knowledge graph is updated.
