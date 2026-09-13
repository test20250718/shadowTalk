# Task 10: Full integration polish and edge cases — Report

## Summary

Task 10 is the final polish pass. The brief's key fix — moving exercise
detection before the work_dir check in `AIWorker._run_tool` — was already
correctly ordered in the current code (exercise check at lines 83–94,
work_dir check at lines 96–100). All five edge cases listed in the brief
were verified to be correctly handled. No code changes were required.

## Verification of each edge case

### 1. Worker recreation on each message ✅
`EnglishRoomWindow._on_send` (english_room.py:546–555) reconnects the
`exercise_requested` signal for every new worker, with a `RuntimeError`
guard for the already-connected case. Correct.

### 2. closeEvent cleanup ✅
`EnglishRoomWindow.closeEvent` (english_room.py:670–674) calls
`deleteLater()` on `_current_card` then chains to the parent. Correct.

### 3. Disable input during exercise ✅
`_on_exercise_requested` disables `input_edit` and `send_btn`
(english_room.py:567–568). Both `_check_answer` (line 628–629) and
`_skip_exercise` (line 647–648) re-enable them. Correct.

### 4. Rapid double-submit guard ✅
Both `_check_answer` (line 593) and `_skip_exercise` (line 633) early-return
when `card._answered` is True, and set it to True before any async work.
Correct.

### 5. Exercise detection before work_dir check ✅ (KEY FIX)
`AIWorker._run_tool` (ai_worker.py:83–100) checks
`reason.startswith("出题: ")` at the very top of the method, before the
`if not self.work_dir:` guard. This means `present_exercise` works even
when the friend has no work_dir configured, since it doesn't execute code.
The ordering has been correct since the exercise feature was first added
(commit dd792ba). No change needed.

## Files changed

None. All edge cases were already correctly implemented.

## Test results

```
python -m pytest tests/ -q --ignore=tests/test_main_window.py
........................................................................ [ 21%]
........................................................................ [ 43%]
........................................................................ [ 65%]
........................................................................ [ 86%]
............................................                             [100%]
332 passed in 76.44s (0:01:16)
```

All 332 tests pass.

## Self-review findings

- The `_run_tool` ordering is correct and matches the brief's required
  final state exactly.
- All five edge cases from the brief are handled with guards that match
  the codebase's defensive-coding style (Chinese comments, early returns,
  flag-based dedup).
- `ExerciseCard._answered` is the single source of truth for the
  double-submit guard; both `_render_exercise_card` (clears old card) and
  `_check_answer`/`_skip_exercise` (set flag) coordinate through it.
- The `QEventLoop` suspend in `_run_tool` is properly cleaned up
  (`self._exercise_loop = None` after `loop.exec()` returns), so a
  subsequent exercise in the same session works correctly.
- No concerns. The English Learning Room feature is complete and robust.
