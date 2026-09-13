# Task 8: Archiver — Report

## Status: DONE_WITH_CONCERNS

## Files Created
- `shadowtalk/core/archiver.py` — implemented verbatim from brief
- `tests/test_archiver.py` — implemented verbatim from brief

## Implementation
`check_and_archive(friend_id)` follows the count-first trigger logic exactly as specified:
1. Read `raw_keep_max` and `summary_batch_size` via `Settings.get_int()`
2. Count unarchived rounds via `MessageRepository.count_unarchived_rounds()`
3. If `raw_count <= raw_keep_max` → return (nothing to do)
4. Compute `overflow = raw_count - raw_keep_max`, fetch that many oldest unarchived rows
5. If `len(buffer) < batch_size` → return (buffer too small)
6. Otherwise take `buffer[:batch_size]` and delegate to `summarizer.generate_batch_summary()`

The archiver does NOT perform summarization itself — it delegates entirely to the summarizer, as required.

## Test Results
```
tests/test_archiver.py::test_no_archive_when_under_threshold PASSED
tests/test_archiver.py::test_archive_when_over_threshold FAILED
tests/test_archiver.py::test_no_archive_buffer_too_small PASSED
```

(Plus teardown `PermissionError` on Windows from the shared conftest trying to delete the DB file while still open — a pre-existing test-harness issue, not specific to these tests.)

## Concern: Bug in Brief's Test Data

`test_archive_when_over_threshold` inserts **60 rounds** and expects `generate_batch_summary` to be called. But per the spec and the implementation:

- `raw_count = 60`, `raw_keep_max = 50` → proceeds past first guard
- `overflow = 60 - 50 = 10`
- `buffer = get_oldest_unarchived(fid, 10)` → 10 rows
- `len(buffer) = 10 < batch_size = 30` → **returns early, no archiving**

So the archiver correctly does nothing, and the test's assertion `call_count >= 1` fails. The implementation matches the spec exactly — the test data is inconsistent with the trigger thresholds. To make this test pass as-written, either:
- Insert **80+ rounds** (so overflow ≥ 30), or
- Lower `raw_keep_max` via Settings so overflow ≥ 30 at 60 rounds

I kept the test verbatim per the "exact code to use verbatim" instruction, so this failure is preserved rather than silently fixed.

## Commits Created
None — not committing because one of the three tests fails. The implementation is correct per spec; the brief's test data needs adjustment (see Concern above).
