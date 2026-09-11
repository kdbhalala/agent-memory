# /review Playbook

Review proposed changes against repository invariants:

1. **Zero External Dependencies**:
   - Check `pyproject.toml` and new imports. Ensure no third-party libraries were added.
2. **Third-Party Naming Check**:
   - Ensure no files or variables use legacy third-party package names.
3. **Data/Code Decoupling**:
   - Verify that no runtime databases (`*.db`), secrets, or user state are committed to the repository.
4. **Byte-for-Byte Assistant Parity**:
   - Ensure `CLAUDE.md` and `AGENTS.md` remain 100% byte-for-byte identical (`diff -u CLAUDE.md AGENTS.md` must be empty).
5. **Offline Test Suite**:
   - Run `python3 test_offline.py && python3 eval_l1.py && python3 eval_l2.py && python3 integrate.py test && python3 stress_test.py`.
