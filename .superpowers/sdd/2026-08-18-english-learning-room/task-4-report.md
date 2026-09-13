# Task 4 Report: AIWorker — exercise suspend/resume mechanism

## Status: ✅ Complete

## TDD Evidence

**Red phase (tests fail before implementation):**
```
tests/test_ai_worker.py::test_exercise_signals_exist FAILED
tests/test_ai_worker.py::test_resume_exercise_method_exists FAILED
tests/test_ai_worker.py::test_exercise_suspends_and_returns_result FAILED  (TypeError: unexpected kwarg 'word_range')
tests/test_ai_worker.py::test_exercise_resume_before_signal_is_safe FAILED
```

**Green phase (after implementation):**
```
tests/test_ai_worker.py::test_exercise_signals_exist              PASSED
tests/test_ai_worker.py::test_resume_exercise_method_exists       PASSED
tests/test_ai_worker.py::test_exercise_suspends_and_returns_result PASSED
tests/test_ai_worker.py::test_exercise_resume_before_signal_is_safe PASSED
tests/test_ai_worker.py::test_regular_tool_not_misdetected_as_exercise PASSED

5 passed in 2.16s
```

**Full suite:** `292 passed in 78.14s` (excluding test_main_window.py per project convention)

## Files Changed

| File | Change |
|------|--------|
| `shadowtalk/ui/threads/ai_worker.py` | Added `exercise_requested`/`exercise_answered` signals, `word_range` param, exercise state fields, `present_exercise` interception in `_run_tool`, `resume_exercise` method |
| `tests/test_ai_worker.py` | Added 5 new tests covering signals, suspend/resume round-trip, idempotent resume, and misdetection guard |

## Implementation Notes

1. **Pattern consistency**: Mirrors the existing approval-flow pattern (lines 107-125) — nested `QEventLoop` + signal emission. Reuses the same architectural idiom already proven in the codebase.

2. **Detection heuristic**: `reason.startswith("出题: ")` AND `code.strip().startswith("{")` — dual condition avoids false positives. The `reason` prefix is set by `ai_client.py` (Task 3) when routing `present_exercise`; the JSON guard catches edge cases where a non-exercise tool might coincidentally have a similar reason string.

3. **Graceful degradation**: If `resume_exercise` is never called (e.g., UI crash), `_last_exercise_result` defaults to a synthetic "skip" JSON rather than hanging forever. The thread unblocks via `quit()` and returns the skip result.

4. **Cross-thread signal fix**: The suspend/resume test uses `Qt.DirectConnection` because PySide6 defaults to `QueuedConnection` across threads, which would deadlock in a test without a running main event loop. In production (MainWindow scenario), the default queued connection is correct and desired.

5. **`exercise_answered` signal**: Declared but not yet emitted — reserved per plan for future tool-call-id tracking. No-op for this task.

## Self-Review Findings

- **No concerns on correctness**: The QEventLoop suspend/resume is the same pattern already used for approval flow; battle-tested.
- **Minor: `json` import added at module level** — consistent with existing `time`/`logging` imports; no lazy import needed since it's used in the hot path.
- **Minor: `exercise_answered` signal unused** — intentional per plan (future use). Could be removed to satisfy a strict "no dead code" lint, but keeping it avoids a future breaking change to the public signal API.
- **Test dependency on `QT_QPA_PLATFORM=offscreen`**: Required for `QEventLoop` in CI/headless environments. The existing test suite already relies on this for other Qt tests (e.g., `test_chat_area.py`), so no new infrastructure needed.

## Commit

```
dd792ba feat: add exercise suspend/resume to AIWorker
```
