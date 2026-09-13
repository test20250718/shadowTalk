# Task 10: Background Scanner — Report

## Status

DONE_WITH_CONCERNS

## Commits

- `581b6dc` feat(shadowtalk): add BackgroundScanner for expired summary merging

## Files Created

- `shadowtalk/core/background_scanner.py` (implementation)
- `tests/test_background_scanner.py` (test)

## Test Summary

1 test, 1 passed. `test_scan_merges_expired_summaries` verifies that an expired
batch summary (40 days old, valid_days=30) gets merged into a new L2
high-level summary via the mocked summarizer.

Full suite: 44 passed (44 teardown errors are a pre-existing Windows
file-locking issue in `conftest.py` — `os.remove(test_shadowtalk.db)` fails
because the connection is still open; unrelated to this task).

## Concerns

**Brief's verbatim code had a deadlock bug.** The `_scan_friend` and
`_enforce_l2_limit` methods opened an outer `Database.transaction()`
(acquiring the non-reentrant `_write_lock`), then called repository methods
(`save_high_level_summary`, `mark_summaries_archived`) that each open their
OWN transaction — re-acquiring the same lock → deadlock. The test hung
indefinitely (confirmed with a minimal reproduction: nested
`Database.transaction()` calls time out).

**Fix applied:** Replaced the nested repository calls with inlined SQL using
the transaction's `conn` directly. This preserves the original intent (atomic
save + mark-archived in one transaction) and matches the established pattern
in `summarizer.py::generate_batch_summary`, which also inlines SQL within a
single transaction rather than calling repository methods.

This is a deviation from the brief's "use verbatim" instruction, but the
verbatim code cannot pass the test. The fix is minimal and idiomatic to the
codebase.

## Verification

- [x] Failing test written first (ModuleNotFoundError on import)
- [x] Test confirmed FAIL before implementation
- [x] Test confirmed PASS after implementation
- [x] No PySide6 imports in core/
- [x] Uses `Settings.get_int()` for valid_days and l2_limit
- [x] Uses `Database.transaction()` for atomic writes
- [x] Full suite passes (44/44)
