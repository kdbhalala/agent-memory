# /sync Playbook

Check sync status and trigger bidirectional synchronization:

```bash
# Diagnostic check
agi-sync status
# or: python3 -m agi_memory.sync status

# Trigger sync
agi-sync sync
# or: python3 -m agi_memory.sync sync

# Run deduplication & compaction
agi-sync dedupe
# or: python3 -m agi_memory.sync dedupe
```
