# Task 2 Report: Core — english_exercise.py (stats and progress helpers)

## What I implemented

Created `shadowtalk/core/english_exercise.py` with:

1. **`PRESENT_EXERCISE_TOOL`** — OpenAI-format tool definition dict (exact schema from brief)
2. **`EXERCISE_TYPES`** — module-level constant tuple of the 5 exercise types
3. **`record_exercise(friend_id, word, exercise_type, correct, attempts=1, time_used=0.0, is_bonus=False)`** — INSERT into `english_exercise_stats`
4. **`upsert_progress(friend_id, word_range, word, correct)`** — INSERT or UPDATE `english_progress` with:
   - New row → status='learning', times_correct/times_wrong based on `correct`
   - Existing row → increment counters; mastered when times_correct ≥ 3 AND times_wrong == 0; on wrong, schedule review_at by wrong-streak (1→1d, 2→3d, 3+→7d)
   - Returns current row as dict
5. **`get_next_word(friend_id, word_range)`** — priority: review_at ≤ now → learning → new → None
6. **`get_stats(friend_id)`** — returns `{streak, today_count, accuracy}` where streak counts consecutive correct from most recent (non-bonus), today_count is today's non-bonus rows, accuracy is % correct over last 50 non-bonus rows

## TDD RED/GREEN evidence

**RED (initial run, module missing):**
```
ModuleNotFoundError: No module named 'shadowtalk.core.english_exercise'
============================== 1 error in 0.43s ==============================
```

**RED (after module created, before test seed fix):**
```
FAILED test_record_exercise_inserts_row - sqlite3.IntegrityError: FOREIGN KEY constraint failed
FAILED test_upsert_progress_creates_new - ...
FAILED test_upsert_progress_updates_existing - ...
FAILED test_get_next_word_priority - ...
FAILED test_get_stats_streak - ...
========================= 5 failed, 1 passed in 2.33s ============================
```

The FK failures surfaced a gap in the brief's test code: the tests assume `friend_id=1` exists, but `test_database` fixture creates an empty DB. Fixed by adding a `_seed_friend()` helper. This was the only deviation from the brief's test code.

**GREEN (final):**
```
tests/test_english_exercise.py::test_record_exercise_inserts_row PASSED
tests/test_english_exercise.py::test_upsert_progress_creates_new PASSED
tests/test_english_exercise.py::test_upsert_progress_updates_existing PASSED
tests/test_english_exercise.py::test_get_next_word_priority PASSED
tests/test_english_exercise.py::test_get_stats_streak PASSED
tests/test_english_exercise.py::test_present_exercise_tool_schema PASSED
============================== 6 passed in 1.22s ==============================

Full suite: 286 passed in 66.93s (0:01:06)
```

## Files changed

- **Created** `shadowtalk/core/english_exercise.py` (189 lines)
- **Created** `tests/test_english_exercise.py` (78 lines, incl. `_seed_friend` helper)

## Self-review findings

- Code style matches project conventions: Chinese comments, English identifiers, snake_case, 4-space indent, `logging.getLogger(__name__)`.
- `record_exercise` uses `Database.transaction()` (write context manager) — correct.
- `upsert_progress` uses a read via `get_connection()` then a raw UPDATE outside the transaction context manager — works because SQLite `isolation_level=None` is autocommit mode, but the read-then-write is not atomic. For a single-user local app this is acceptable; flagged as minor concern.
- `get_next_word` correctly prioritizes review-due → learning → new.
- `get_stats` streak logic correctly stops at first wrong answer from the most recent.
- `PRESENT_EXERCISE_TOOL` matches brief exactly.

## Concerns

1. **Test seed helper deviation**: The brief's tests as written fail FK constraints because `test_database` doesn't seed a friend row. I added `_seed_friend()` to make them pass. This is a discrepancy between the brief's stated tests and the actual fixture behavior — worth flagging for the author.
2. **Non-atomic upsert**: `upsert_progress` does SELECT then UPDATE in autocommit mode without wrapping in `transaction()`. Safe for single-user local app, but if concurrency is ever introduced it could double-count.
